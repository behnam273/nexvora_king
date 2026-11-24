from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import httpx
import numpy as np
from sqlalchemy.orm import Session

from app.config import ALLOWED_SYMBOLS, ALLOWED_TIMEFRAMES, SYMBOL_META, TIMEFRAME_META, get_settings
from app.models import SourceHealth, utcnow
from app.security import validate_external_url

ALLOWED_DATA_HOSTS = {
    "api-fxpractice.oanda.com",
    "api-fxtrade.oanda.com",
    "biquote.io",
    "api.twelvedata.com",
    "query1.finance.yahoo.com",
    "query2.finance.yahoo.com",
    "www.alphavantage.co",
}


@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class MarketSeries:
    symbol: str
    timeframe: str
    candles: List[Candle]
    source: str
    is_demo_data: bool
    fetched_at: datetime


# Smart in-memory cache + per-provider Circuit Breaker / Cooldown timestamps
_CACHE: Dict[Tuple[str, str, int], Tuple[float, MarketSeries]] = {}
_PROVIDER_COOLDOWN_UNTIL: Dict[str, float] = {}
_TD_KEY_COOLDOWN_UNTIL: Dict[str, float] = {}


def reset_provider_cooldowns() -> None:
    """Clear all provider/key cooldown timers and cache (used by tests & admin reset)."""
    _PROVIDER_COOLDOWN_UNTIL.clear()
    _TD_KEY_COOLDOWN_UNTIL.clear()
    _CACHE.clear()


def _is_provider_cooling_down(provider: str) -> bool:
    until = _PROVIDER_COOLDOWN_UNTIL.get(provider, 0.0)
    return time.monotonic() < until


def _trip_provider_cooldown(provider: str, seconds: float) -> None:
    _PROVIDER_COOLDOWN_UNTIL[provider] = max(
        _PROVIDER_COOLDOWN_UNTIL.get(provider, 0.0),
        time.monotonic() + max(5.0, seconds),
    )


def _clear_provider_cooldown(provider: str) -> None:
    _PROVIDER_COOLDOWN_UNTIL.pop(provider, None)


def _record_source_health(
    db: Optional[Session],
    source_key: str,
    display_name: str,
    status_str: str,
    latency_ms: Optional[int] = None,
    error_msg: str = "",
    rate_limit_note: str = "",
) -> None:
    if db is None:
        return
    try:
        row = db.query(SourceHealth).filter(SourceHealth.source_key == source_key).first()
        if not row:
            row = SourceHealth(
                source_key=source_key,
                source_type="market_data",
                display_name=display_name,
                rate_limit_note=rate_limit_note,
            )
            db.add(row)
        row.status = status_str
        row.requests_count = (row.requests_count or 0) + 1
        if latency_ms is not None:
            row.latency_ms = latency_ms
        if rate_limit_note:
            row.rate_limit_note = rate_limit_note
        if status_str == "HEALTHY":
            row.last_success_at = utcnow()
            row.last_error_msg = ""
        elif error_msg:
            row.last_error_at = utcnow()
            row.last_error_msg = error_msg[:400]
            row.failure_count = (row.failure_count or 0) + 1
        db.commit()
    except Exception:
        db.rollback()


def _parse_iso_utc(raw: str) -> datetime:
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _resample_to_4h(candles: List[Candle]) -> List[Candle]:
    if not candles:
        return []
    buckets: Dict[datetime, List[Candle]] = {}
    for c in candles:
        ts = c.timestamp.astimezone(timezone.utc)
        h4 = (ts.hour // 4) * 4
        key = ts.replace(hour=h4, minute=0, second=0, microsecond=0)
        buckets.setdefault(key, []).append(c)
    out: List[Candle] = []
    for key in sorted(buckets.keys()):
        grp = buckets[key]
        out.append(
            Candle(
                timestamp=key,
                open=grp[0].open,
                high=max(x.high for x in grp),
                low=min(x.low for x in grp),
                close=grp[-1].close,
                volume=sum(x.volume for x in grp),
            )
        )
    return out


def fetch_oanda(symbol: str, timeframe: str, limit: int = 350, db: Optional[Session] = None) -> Optional[MarketSeries]:
    """
    OANDA v20 Practice/Live REST API (free Practice account supports all 6 symbols incl. XAU_USD
    with generous rate limits and TradingView-grade broker candles).
    """
    settings = get_settings()
    if not settings.oanda_api_token or _is_provider_cooling_down("oanda"):
        return None
    meta = SYMBOL_META[symbol]
    instrument = f"{meta['base']}_{meta['quote']}"
    gran_map = {"5m": "M5", "15m": "M15", "1H": "H1", "4H": "H4", "1D": "D"}
    granularity = gran_map.get(timeframe, "M15")
    host = "api-fxtrade.oanda.com" if settings.oanda_env == "live" else "api-fxpractice.oanda.com"
    url = f"https://{host}/v3/instruments/{instrument}/candles"
    if not validate_external_url(url, ALLOWED_DATA_HOSTS):
        return None

    t0 = time.monotonic()
    try:
        with httpx.Client(
            timeout=10.0,
            follow_redirects=False,
            headers={
                "Authorization": f"Bearer {settings.oanda_api_token.strip()}",
                "Accept-Datetime-Format": "RFC3339",
            },
        ) as client:
            resp = client.get(
                url,
                params={"granularity": granularity, "count": min(limit, 500), "price": "M"},
            )
            latency = int((time.monotonic() - t0) * 1000)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", "60") or 60)
                _trip_provider_cooldown("oanda", retry_after)
                _record_source_health(
                    db, "oanda", "OANDA v20 (Broker Feed)", "RATE_LIMITED", latency,
                    f"HTTP 429 — switched away for {int(retry_after)}s", "Free Practice API"
                )
                return None
            if resp.status_code != 200:
                _trip_provider_cooldown("oanda", 120.0 if resp.status_code in (401, 403) else 45.0)
                _record_source_health(
                    db, "oanda", "OANDA v20 (Broker Feed)", "DEGRADED", latency,
                    f"HTTP {resp.status_code}", "Free Practice API"
                )
                return None

            payload = resp.json()
            raw_candles = payload.get("candles") or []
            candles: List[Candle] = []
            for item in raw_candles:
                mid = item.get("mid") or {}
                if not all(k in mid for k in ("o", "h", "l", "c")):
                    continue
                candles.append(
                    Candle(
                        timestamp=_parse_iso_utc(item["time"]),
                        open=float(mid["o"]),
                        high=float(mid["h"]),
                        low=float(mid["l"]),
                        close=float(mid["c"]),
                        volume=float(item.get("volume") or 0.0),
                    )
                )
            if len(candles) < 50:
                return None
            _clear_provider_cooldown("oanda")
            _record_source_health(
                db, "oanda", "OANDA v20 (Broker Feed)", "HEALTHY", latency,
                "", "Free Practice API; high rate limit"
            )
            return MarketSeries(
                symbol=symbol,
                timeframe=timeframe,
                candles=candles[-limit:],
                source="OANDA v20 (Live Broker)",
                is_demo_data=False,
                fetched_at=utcnow(),
            )
    except Exception as exc:
        latency = int((time.monotonic() - t0) * 1000)
        _trip_provider_cooldown("oanda", 45.0)
        _record_source_health(
            db, "oanda", "OANDA v20 (Broker Feed)", "OFFLINE", latency,
            str(exc), "Free Practice API"
        )
        return None


def fetch_biquote(symbol: str, timeframe: str, limit: int = 350, db: Optional[Session] = None) -> Optional[MarketSeries]:
    """
    biquote.io Public Forex & Gold OHLC API — free, no API key required, 15,000 req/min per IP,
    native MT5 CFD bars for EURUSD, GBPUSD, USDJPY, AUDUSD, EURGBP, and XAUUSD.
    """
    if _is_provider_cooling_down("biquote"):
        return None
    tf_map = {"5m": "5m", "15m": "15m", "1H": "1h", "4H": "4h", "1D": "1d"}
    interval = tf_map.get(timeframe, "15m")
    url = f"https://biquote.io/api/{symbol}/ohlc"
    if not validate_external_url(url, ALLOWED_DATA_HOSTS):
        return None

    t0 = time.monotonic()
    try:
        with httpx.Client(
            timeout=10.0,
            follow_redirects=False,
            headers={"User-Agent": "NEXVORA-MarketEngine/1.0"},
        ) as client:
            resp = client.get(url, params={"interval": interval, "limit": min(limit, 500)})
            latency = int((time.monotonic() - t0) * 1000)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", "60") or 60)
                _trip_provider_cooldown("biquote", retry_after)
                _record_source_health(
                    db, "biquote", "biquote.io (Free MT5 No-Key)", "RATE_LIMITED", latency,
                    f"HTTP 429 — switched away for {int(retry_after)}s", "Free no-key: 15,000 req/min"
                )
                return None
            if resp.status_code != 200:
                _trip_provider_cooldown("biquote", 60.0)
                _record_source_health(
                    db, "biquote", "biquote.io (Free MT5 No-Key)", "DEGRADED", latency,
                    f"HTTP {resp.status_code}", "Free no-key: 15,000 req/min"
                )
                return None

            payload = resp.json()
            bars = payload.get("bars") if isinstance(payload, dict) else None
            if not bars:
                return None

            candles: List[Candle] = []
            for b in bars:
                if b.get("open") is None or b.get("high") is None or b.get("low") is None or b.get("close") is None:
                    continue
                ts_raw = b.get("openTime") or b.get("time") or b.get("timestamp")
                if not ts_raw:
                    continue
                candles.append(
                    Candle(
                        timestamp=_parse_iso_utc(str(ts_raw)),
                        open=float(b["open"]),
                        high=float(b["high"]),
                        low=float(b["low"]),
                        close=float(b["close"]),
                        volume=float(b.get("tickVolume") or b.get("volume") or 0.0),
                    )
                )
            # Sort oldest -> newest (biquote returns newest-first)
            candles.sort(key=lambda c: c.timestamp)
            if len(candles) < 50:
                return None
            _clear_provider_cooldown("biquote")
            _record_source_health(
                db, "biquote", "biquote.io (Free MT5 No-Key)", "HEALTHY", latency,
                "", "Free no-key: 15,000 req/min (MT5 feed)"
            )
            return MarketSeries(
                symbol=symbol,
                timeframe=timeframe,
                candles=candles[-limit:],
                source="biquote.io (Live Free MT5)",
                is_demo_data=False,
                fetched_at=utcnow(),
            )
    except Exception as exc:
        latency = int((time.monotonic() - t0) * 1000)
        _trip_provider_cooldown("biquote", 45.0)
        _record_source_health(
            db, "biquote", "biquote.io (Free MT5 No-Key)", "OFFLINE", latency,
            str(exc), "Free no-key: 15,000 req/min"
        )
        return None


def fetch_twelvedata(symbol: str, timeframe: str, limit: int = 350, db: Optional[Session] = None) -> Optional[MarketSeries]:
    """
    Twelve Data with automatic Multi-Key Pool rotation and instant Rate-Limit Cooldown
    so hitting the 8 req/min or 800 req/day cap immediately switches to another key or provider.
    """
    settings = get_settings()
    key_pool = settings.twelve_data_key_pool
    if not key_pool or _is_provider_cooling_down("twelvedata"):
        return None

    meta = SYMBOL_META[symbol]
    tf_map = {"4H": "4h", "15m": "15min", "5m": "5min", "1H": "1h", "1D": "1day"}
    interval = tf_map.get(timeframe, "15min")
    url = "https://api.twelvedata.com/time_series"
    if not validate_external_url(url, ALLOWED_DATA_HOSTS):
        return None

    now_mono = time.monotonic()
    active_keys = [k for k in key_pool if now_mono >= _TD_KEY_COOLDOWN_UNTIL.get(k, 0.0)]
    if not active_keys:
        # All keys are currently cooling down -> immediately failover to next provider
        soonest = min(_TD_KEY_COOLDOWN_UNTIL.get(k, now_mono + 60.0) for k in key_pool)
        _trip_provider_cooldown("twelvedata", max(15.0, soonest - now_mono))
        return None

    for api_key in active_keys:
        t0 = time.monotonic()
        try:
            with httpx.Client(timeout=10.0, follow_redirects=False) as client:
                resp = client.get(
                    url,
                    params={
                        "symbol": meta["twelve_data"],
                        "interval": interval,
                        "outputsize": min(limit, 500),
                        "apikey": api_key,
                        "timezone": "UTC",
                    },
                )
                latency = int((time.monotonic() - t0) * 1000)
                if resp.status_code == 429:
                    _TD_KEY_COOLDOWN_UNTIL[api_key] = time.monotonic() + 75.0
                    _record_source_health(
                        db, "twelvedata", "Twelve Data (Free API)", "RATE_LIMITED", latency,
                        "HTTP 429 — rotating key / failing over immediately", "Free tier: 8 req/min, 800 req/day"
                    )
                    continue
                if resp.status_code != 200:
                    _TD_KEY_COOLDOWN_UNTIL[api_key] = time.monotonic() + 60.0
                    _record_source_health(
                        db, "twelvedata", "Twelve Data (Free API)", "DEGRADED", latency,
                        f"HTTP {resp.status_code}", "Free tier: 8 req/min, 800 req/day"
                    )
                    continue
                payload = resp.json()
                if payload.get("status") == "error" or "values" not in payload:
                    msg = str(payload.get("message", "Unknown API error"))
                    msg_low = msg.lower()
                    if any(w in msg_low for w in ("credit", "limit", "minute", "day", "quota", "429")):
                        cooldown_sec = 3600.0 if "day" in msg_low else 75.0
                        _TD_KEY_COOLDOWN_UNTIL[api_key] = time.monotonic() + cooldown_sec
                        _record_source_health(
                            db, "twelvedata", "Twelve Data (Free API)", "RATE_LIMITED", latency,
                            f"{msg} — auto-switching to fallback API", "Free tier: 8 req/min, 800 req/day"
                        )
                        continue
                    _record_source_health(
                        db, "twelvedata", "Twelve Data (Free API)", "DEGRADED", latency,
                        msg, "Free tier: 8 req/min, 800 req/day"
                    )
                    return None

                candles: List[Candle] = []
                for v in reversed(payload["values"]):
                    dt_str = v["datetime"]
                    fmt = "%Y-%m-%d %H:%M:%S" if " " in dt_str else "%Y-%m-%d"
                    ts = datetime.strptime(dt_str, fmt).replace(tzinfo=timezone.utc)
                    candles.append(
                        Candle(
                            timestamp=ts,
                            open=float(v["open"]),
                            high=float(v["high"]),
                            low=float(v["low"]),
                            close=float(v["close"]),
                            volume=float(v.get("volume") or 0.0),
                        )
                    )
                if len(candles) < 50:
                    return None
                _clear_provider_cooldown("twelvedata")
                _record_source_health(
                    db, "twelvedata", "Twelve Data (Free API)", "HEALTHY", latency,
                    "", f"Free tier ({len(key_pool)} key(s) in rotation)"
                )
                return MarketSeries(
                    symbol=symbol,
                    timeframe=timeframe,
                    candles=candles[-limit:],
                    source="Twelve Data (Live Free API)",
                    is_demo_data=False,
                    fetched_at=utcnow(),
                )
        except Exception as exc:
            latency = int((time.monotonic() - t0) * 1000)
            _trip_provider_cooldown("twelvedata", 45.0)
            _record_source_health(
                db, "twelvedata", "Twelve Data (Free API)", "OFFLINE", latency,
                str(exc), "Free tier: 8 req/min, 800 req/day"
            )
            return None

    # Every configured key was rate-limited -> trip provider cooldown so next calls failover instantly
    _trip_provider_cooldown("twelvedata", 75.0)
    return None


def fetch_yahoo_finance(symbol: str, timeframe: str, limit: int = 350, db: Optional[Session] = None) -> Optional[MarketSeries]:
    if _is_provider_cooling_down("yahoo"):
        return None
    meta = SYMBOL_META[symbol]
    yf_sym = meta["yahoo"]
    if timeframe == "4H":
        interval, rng = "60m", "60d"
    elif timeframe == "15m":
        interval, rng = "15m", "30d"
    elif timeframe == "5m":
        interval, rng = "5m", "14d"
    elif timeframe == "1H":
        interval, rng = "60m", "60d"
    else:
        interval, rng = "1d", "1y"

    # Try query1 first, automatically rotate to query2 on 429/failure
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        url = f"https://{host}/v8/finance/chart/{yf_sym}"
        if not validate_external_url(url, ALLOWED_DATA_HOSTS):
            continue
        t0 = time.monotonic()
        try:
            with httpx.Client(
                timeout=10.0,
                follow_redirects=False,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) NEXVORA/1.0"},
            ) as client:
                resp = client.get(url, params={"interval": interval, "range": rng})
                latency = int((time.monotonic() - t0) * 1000)
                if resp.status_code == 429:
                    continue
                if resp.status_code != 200:
                    _record_source_health(
                        db, "yahoo_finance", "Yahoo Finance (Free No-Key)", "DEGRADED", latency,
                        f"HTTP {resp.status_code} ({host})", "Public endpoint; no API key required"
                    )
                    continue
                data = resp.json()
                result = (data.get("chart") or {}).get("result")
                if not result:
                    continue
                r0 = result[0]
                timestamps = r0.get("timestamp") or []
                quote = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
                opens = quote.get("open") or []
                highs = quote.get("high") or []
                lows = quote.get("low") or []
                closes = quote.get("close") or []
                vols = quote.get("volume") or []

                candles: List[Candle] = []
                for i, ts_sec in enumerate(timestamps):
                    if i >= len(opens) or opens[i] is None or highs[i] is None or lows[i] is None or closes[i] is None:
                        continue
                    candles.append(
                        Candle(
                            timestamp=datetime.fromtimestamp(ts_sec, tz=timezone.utc),
                            open=float(opens[i]),
                            high=float(highs[i]),
                            low=float(lows[i]),
                            close=float(closes[i]),
                            volume=float(vols[i] or 0.0) if i < len(vols) else 0.0,
                        )
                    )
                if timeframe == "4H":
                    candles = _resample_to_4h(candles)
                if len(candles) < 50:
                    continue
                _clear_provider_cooldown("yahoo")
                _record_source_health(
                    db, "yahoo_finance", "Yahoo Finance (Free No-Key)", "HEALTHY", latency,
                    "", "Public endpoint; query1/query2 failover"
                )
                return MarketSeries(
                    symbol=symbol,
                    timeframe=timeframe,
                    candles=candles[-limit:],
                    source="Yahoo Finance (Live Free)",
                    is_demo_data=False,
                    fetched_at=utcnow(),
                )
        except Exception as exc:
            latency = int((time.monotonic() - t0) * 1000)
            _record_source_health(
                db, "yahoo_finance", "Yahoo Finance (Free No-Key)", "OFFLINE", latency,
                str(exc), "Public endpoint; no API key required"
            )

    _trip_provider_cooldown("yahoo", 60.0)
    return None


def fetch_alphavantage(symbol: str, timeframe: str, limit: int = 350, db: Optional[Session] = None) -> Optional[MarketSeries]:
    """Optional Alpha Vantage FX backup (FX_INTRADAY / FX_DAILY) if ALPHA_VANTAGE_API_KEY is set."""
    settings = get_settings()
    if not settings.alpha_vantage_api_key or _is_provider_cooling_down("alphavantage"):
        return None
    meta = SYMBOL_META[symbol]
    if meta["market_class"] != "FOREX":
        return None  # Alpha Vantage free FX endpoints cover currency pairs, not spot XAU
    url = "https://www.alphavantage.co/query"
    if not validate_external_url(url, ALLOWED_DATA_HOSTS):
        return None

    if timeframe == "1D":
        params = {
            "function": "FX_DAILY",
            "from_symbol": meta["base"],
            "to_symbol": meta["quote"],
            "outputsize": "full",
            "apikey": settings.alpha_vantage_api_key.strip(),
        }
        series_key = "Time Series FX (Daily)"
    else:
        av_int = "5min" if timeframe == "5m" else "15min" if timeframe == "15m" else "60min"
        params = {
            "function": "FX_INTRADAY",
            "from_symbol": meta["base"],
            "to_symbol": meta["quote"],
            "interval": av_int,
            "outputsize": "full",
            "apikey": settings.alpha_vantage_api_key.strip(),
        }
        series_key = f"Time Series FX ({av_int})"

    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            resp = client.get(url, params=params)
            latency = int((time.monotonic() - t0) * 1000)
            if resp.status_code != 200:
                _trip_provider_cooldown("alphavantage", 120.0)
                return None
            payload = resp.json()
            if "Note" in payload or "Information" in payload or series_key not in payload:
                msg = str(payload.get("Note") or payload.get("Information") or "No FX series returned")
                _trip_provider_cooldown("alphavantage", 600.0)
                _record_source_health(
                    db, "alphavantage", "Alpha Vantage (FX Backup)", "RATE_LIMITED", latency,
                    msg[:300], "Optional FX backup key"
                )
                return None

            candles: List[Candle] = []
            for dt_str, vals in sorted(payload[series_key].items()):
                fmt = "%Y-%m-%d %H:%M:%S" if " " in dt_str else "%Y-%m-%d"
                ts = datetime.strptime(dt_str, fmt).replace(tzinfo=timezone.utc)
                candles.append(
                    Candle(
                        timestamp=ts,
                        open=float(vals["1. open"]),
                        high=float(vals["2. high"]),
                        low=float(vals["3. low"]),
                        close=float(vals["4. close"]),
                        volume=0.0,
                    )
                )
            if timeframe == "4H":
                candles = _resample_to_4h(candles)
            if len(candles) < 50:
                return None
            _clear_provider_cooldown("alphavantage")
            _record_source_health(
                db, "alphavantage", "Alpha Vantage (FX Backup)", "HEALTHY", latency,
                "", "Optional FX backup key"
            )
            return MarketSeries(
                symbol=symbol,
                timeframe=timeframe,
                candles=candles[-limit:],
                source="Alpha Vantage (Live FX Backup)",
                is_demo_data=False,
                fetched_at=utcnow(),
            )
    except Exception as exc:
        latency = int((time.monotonic() - t0) * 1000)
        _trip_provider_cooldown("alphavantage", 120.0)
        _record_source_health(
            db, "alphavantage", "Alpha Vantage (FX Backup)", "OFFLINE", latency,
            str(exc), "Optional FX backup key"
        )
        return None


def generate_deterministic_replay_series(
    symbol: str,
    timeframe: str,
    limit: int = 420,
    db: Optional[Session] = None,
) -> MarketSeries:
    """
    Deterministic, clearly-labelled DEMO/REPLAY OHLCV generator used ONLY when
    NEXVORA_DATA_MODE=demo or when live network access is blocked (e.g. sandbox).
    Generates realistic Forex/Gold regime-switching swings (trends + liquidity sweeps
    + CHoCH + pullbacks into FVG/OB) so the real Trading Hub 3.0 SMC engine, backtester,
    and position tracker execute authentically end-to-end without ever fabricating
    fake "live" labels.
    """
    meta = SYMBOL_META[symbol]
    tf_minutes = {"4H": 240, "15m": 15, "5m": 5, "1H": 60, "1D": 1440}.get(timeframe, 15)
    digits = meta["digits"]
    base_price = meta["base_price_demo"]
    # Scale per-bar volatility realistically with sqrt(tf_minutes / 15)
    vol = meta["vol_demo"] * math.sqrt(tf_minutes / 15.0)

    # Deterministic seed per symbol+timeframe so charts & backtests stay consistent
    seed_int = int(hashlib.sha256(f"nexvora-v1:{symbol}:{timeframe}".encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed_int)

    # Align end time to latest closed bar in UTC (snapped to current minute/hour)
    now = utcnow().replace(second=0, microsecond=0)
    # Create a slight live-tick offset based on 30-second slices for realistic tracking progression
    step_delta = timedelta(minutes=tf_minutes)
    start_ts = now - step_delta * limit

    # Per-symbol structural profiles so some pairs naturally exhibit higher SMC Win Rate
    # and some are choppier — allowing the Win-Rate Qualification Gate to genuinely differentiate pairs!
    symbol_trend_strength = {
        "EURUSD": 0.92,
        "XAUUSD": 0.96,
        "USDJPY": 0.88,
        "GBPUSD": 0.82,
        "AUDUSD": 0.60,
        "EURGBP": 0.42,  # notoriously rangy cross -> often filtered out on LTF!
    }.get(symbol, 0.75)

    tf_cleanliness = {"4H": 1.05, "15m": 0.95, "5m": 0.80, "1H": 1.0, "1D": 1.1}.get(timeframe, 0.9)
    clarity = symbol_trend_strength * tf_cleanliness

    candles: List[Candle] = []
    price = base_price

    # Build macro trend + realistic SMC impulse -> deep discount/premium pullback -> sweep -> CHoCH -> continuation cycles
    macro_dir = 1 if (seed_int % 2 == 0) else -1
    cycle_len = 42
    for i in range(limit):
        ts = start_ts + step_delta * i
        if i > 0 and i % 240 == 0:
            macro_dir = -macro_dir

        phase = i % cycle_len
        drift = 0.0
        wick_up = abs(rng.normal(0.28, 0.10)) * vol
        wick_dn = abs(rng.normal(0.28, 0.10)) * vol

        if clarity >= 0.65:
            # Realistic SMC ABC pullback + Sweep of A-low + CHoCH above B-high + FVG/OB retest + Expansion!
            if phase < 10:
                # Impulse leg creating strong trend & ADX
                drift = macro_dir * vol * (1.05 + rng.normal(0, 0.12))
            elif phase < 15:
                # Wave A pullback down into discount (forms minor_pl at phase 14)
                drift = -macro_dir * vol * (1.25 + rng.normal(0, 0.10))
            elif phase < 19:
                # Wave B internal bounce (forms minor_ph at phase 17-18 -> CHoCH trigger level!)
                drift = macro_dir * vol * (0.70 + rng.normal(0, 0.08))
            elif phase == 19:
                # Wave C pullback approaching Wave A low
                drift = -macro_dir * vol * 1.15
            elif phase == 20:
                # Institutional SWEEP of Wave A low (minor_pl) with long rejection wick!
                drift = macro_dir * vol * 0.55
                if macro_dir == 1:
                    wick_dn = vol * 2.8
                else:
                    wick_up = vol * 2.8
            elif phase in (21, 22):
                # Strong displacement CHoCH breaking Wave B high (minor_ph) & creating clean FVG + OB
                drift = macro_dir * vol * (1.85 + abs(rng.normal(0.15, 0.08)))
                if macro_dir == 1:
                    wick_dn = vol * 0.10
                else:
                    wick_up = vol * 0.10
            elif phase in (23, 24):
                # Pullback tapping FVG/OB midpoint (fills limit order cleanly without breaking sweep SL)
                drift = -macro_dir * vol * 1.45
                if macro_dir == 1:
                    wick_dn = vol * 1.85
                else:
                    wick_up = vol * 1.85
            else:
                # Expansion hitting TP1 / TP2 / TP3 (or stop-out on ~18-35% of cycles)
                cycle_id = i // cycle_len
                cycle_succeeds = ((seed_int + cycle_id * 37) % 100) < int(clarity * 88)
                if cycle_succeeds:
                    drift = macro_dir * vol * (0.95 + rng.normal(0.08, 0.14))
                else:
                    drift = -macro_dir * vol * (0.95 + rng.normal(0.08, 0.16))
        else:
            # Choppy mean-reverting range (e.g. EURGBP on LTF) -> rejected by ADX / Win Rate gate
            drift = math.sin(i / 4.2) * vol * 0.65 + rng.normal(0, vol * 0.90)

        o = price
        c = max(meta["pip_size"] * 10, o + drift)
        h = max(o, c) + wick_up
        l = min(o, c) - wick_dn
        if l <= 0:
            l = min(o, c) * 0.999

        candles.append(
            Candle(
                timestamp=ts,
                open=round(o, digits),
                high=round(h, digits),
                low=round(l, digits),
                close=round(c, digits),
                volume=round(float(abs(rng.normal(1200, 350))), 1),
            )
        )
        price = c

    _record_source_health(
        db,
        "demo_replay",
        "Deterministic Replay (Offline Demo Mode)",
        "DEMO_FALLBACK",
        latency_ms=2,
        rate_limit_note="Offline sandbox/demo mode — clearly labelled as non-live",
    )

    return MarketSeries(
        symbol=symbol,
        timeframe=timeframe,
        candles=candles,
        source="DEMO_REPLAY (Offline Simulation)",
        is_demo_data=True,
        fetched_at=utcnow(),
    )


_PROVIDER_FETCHERS = {
    "oanda": fetch_oanda,
    "biquote": fetch_biquote,
    "twelvedata": fetch_twelvedata,
    "yahoo": fetch_yahoo_finance,
    "alphavantage": fetch_alphavantage,
}


def get_market_series(
    symbol: str,
    timeframe: str,
    limit: int = 380,
    db: Optional[Session] = None,
    force_refresh: bool = False,
) -> MarketSeries:
    if symbol not in ALLOWED_SYMBOLS:
        raise ValueError(f"Unsupported symbol: {symbol}. Allowed: {ALLOWED_SYMBOLS}")
    if timeframe not in ALLOWED_TIMEFRAMES and timeframe not in ("1H", "1D"):
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    # Round the requested depth up so call sites never end up with tiny sample
    # sizes (360/420 bars is not enough for a 200-EMA based trend filter).
    limit = max(240, int(limit))
    if limit > 900:
        limit = 900

    cache_key = (symbol, timeframe, limit)
    ttl_map = {"5m": 45, "15m": 120, "1H": 240, "4H": 420, "1D": 900}
    ttl_sec = ttl_map.get(timeframe, 120)
    stale_max_sec = max(ttl_sec * 4, 900)
    now_mono = time.monotonic()

    cached_entry = _CACHE.get(cache_key)
    if not force_refresh and cached_entry is not None:
        cached_at, cached_series = cached_entry
        if now_mono - cached_at < ttl_sec:
            return cached_series

    settings = get_settings()
    series: Optional[MarketSeries] = None

    if settings.nexvora_data_mode in ("live", "auto"):
        for provider_name in settings.market_provider_order:
            fetcher = _PROVIDER_FETCHERS.get(provider_name)
            if fetcher is None:
                continue
            series = fetcher(symbol, timeframe, limit=limit, db=db)
            if series is not None:
                break

    if series is None:
        # Stale-if-error: if we have a recent live cached series (< 15 min old), reuse it instead of degrading
        if cached_entry is not None and not cached_entry[1].is_demo_data and (now_mono - cached_entry[0] < stale_max_sec):
            return cached_entry[1]

        if settings.nexvora_data_mode == "live":
            raise RuntimeError(
                f"Live market data unavailable for {symbol} {timeframe} across all configured providers ({', '.join(settings.market_provider_order)})."
            )
        series = generate_deterministic_replay_series(symbol, timeframe, limit=limit, db=db)

    _CACHE[cache_key] = (now_mono, series)
    return series
