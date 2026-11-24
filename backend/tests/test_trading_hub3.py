from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

os.environ["NEXVORA_DATA_MODE"] = "demo"
os.environ["DATABASE_URL"] = "sqlite:///./test_hub3.db"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import ALLOWED_SYMBOLS, ALLOWED_TIMEFRAMES, TIMEFRAME_META
from app.database import Base
from app.engine.backtester import build_params_for_timeframe, evaluate_pair_backtest, simulate_signal_lifecycle
from app.engine.market_data import Candle, generate_deterministic_replay_series
from app.engine.position_tracker import track_open_trade_with_candle
from app.engine.trading_hub3 import HighAccuracyParams, run_trading_hub3_engine
from app.models import SignalTrade


def _make_memory_db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    return sessionmaker(bind=eng)()


def test_allowed_symbols_and_timeframe_risk_tiers():
    assert set(ALLOWED_SYMBOLS) == {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURGBP", "XAUUSD"}
    assert ALLOWED_TIMEFRAMES == ["4H", "15m", "5m"]
    assert TIMEFRAME_META["4H"]["risk_tier"] == "SAFE"
    assert TIMEFRAME_META["15m"]["risk_tier"] == "MEDIUM_RISK"
    assert TIMEFRAME_META["5m"]["risk_tier"] == "HIGH_RISK"


def _htf_for(symbol: str, timeframe: str):
    meta = TIMEFRAME_META[timeframe]
    htf1 = generate_deterministic_replay_series(symbol, meta["htf_primary"], limit=300)
    if meta["htf_secondary"] != meta["htf_primary"]:
        htf2 = generate_deterministic_replay_series(symbol, meta["htf_secondary"], limit=300)
    else:
        htf2 = htf1
    return htf1.candles, htf2.candles


def test_trading_hub3_strict_engine_and_backtest_qualification():
    db = _make_memory_db()
    series = generate_deterministic_replay_series("EURUSD", "4H", limit=900)
    assert series.is_demo_data is True

    h1, h2 = _htf_for("EURUSD", "4H")
    params = build_params_for_timeframe(None, "4H")
    ev = run_trading_hub3_engine("EURUSD", "4H", series.candles, params=params, htf1_candles=h1, htf2_candles=h2)
    assert len(ev.historical_signals) > 0, "the 4H profile must produce signals on a 900-bar series"

    for sig in ev.historical_signals:
        # score gate comes from the timeframe policy
        assert sig.confluence_score >= params.policy.min_score
        assert sig.grade in ("A+", "A", "B")
        assert len(sig.checklist) == 10
        assert all(item["passed"] for item in sig.checklist)
        assert sig.tp1_exit_pct == 50.0
        assert sig.tp2_exit_pct == 30.0
        assert sig.tp3_exit_pct == 20.0
        # structural risk inside policy bounds, sane R ladder
        assert params.policy.min_stop_atr * 0.99 <= sig.risk_atr <= params.policy.max_stop_atr * 1.01
        rr1 = abs(sig.tp1 - sig.entry_price) / abs(sig.entry_price - sig.sl)
        rr2 = abs(sig.tp2 - sig.entry_price) / abs(sig.entry_price - sig.sl)
        assert rr1 + 1e-6 >= params.policy.min_rr_tp1
        assert rr1 < rr2
        # stop is always on the losing side of the entry
        assert (sig.sl < sig.entry_price) if sig.direction == "LONG" else (sig.sl > sig.entry_price)

    qual_eur, results = evaluate_pair_backtest("EURUSD", "4H", db)
    assert qual_eur.total_trades == len(results)
    assert qual_eur.window_bars >= 400
    # Qualification must be explainable: either eligible or a documented reason
    assert qual_eur.reason_fa
    qual_eg, _ = evaluate_pair_backtest("EURGBP", "5m", db)
    assert qual_eg.risk_tier == "HIGH_RISK"
    db.close()


def test_policy_per_timeframe_shapes_risk_and_targets():
    from app.engine.policy import TF_POLICIES, TRADING_POLICY_VERSION, get_policy

    assert set(TF_POLICIES) == {"4H", "15m", "5m"}
    assert get_policy("4H").risk_tier == "SAFE"
    assert get_policy("15m").risk_tier == "MEDIUM_RISK"
    assert get_policy("5m").risk_tier == "HIGH_RISK"
    # Risk increases -> filters tighten and targets shorten
    assert get_policy("5m").min_score > get_policy("15m").min_score > get_policy("4H").min_score - 0.01
    assert get_policy("5m").min_adx > get_policy("4H").min_adx
    assert get_policy("5m").tp1_rr < get_policy("4H").tp1_rr
    assert get_policy("4H").require_session is False
    assert get_policy("15m").require_session is True
    assert get_policy("5m").require_session is True
    for tf, p in TF_POLICIES.items():
        assert p.tp1_rr < p.tp2_rr < p.tp3_rr
        assert abs(p.tp1_exit_pct + p.tp2_exit_pct + p.tp3_exit_pct - 100.0) < 0.2
        assert p.min_stop_atr <= p.max_stop_atr
        assert p.min_rr_tp1 >= 0.9
    assert TRADING_POLICY_VERSION


def test_policy_overrides_cannot_produce_a_broken_model():
    from app.engine.policy import policy_with_overrides

    # A stored legacy 1.2R TP1 must be raised to the timeframe floor, never
    # allowed to push TP1 under min_rr_tp1.
    merged = policy_with_overrides("15m", tp1_rr=0.2, tp2_rr=0.3, tp3_rr=0.4)
    assert merged.tp1_rr >= merged.min_rr_tp1
    assert merged.tp1_rr < merged.tp2_rr < merged.tp3_rr

    # Impossible exit split falls back to the hardened default
    merged2 = policy_with_overrides("15m", tp1_exit_pct=80.0, tp2_exit_pct=60.0)
    assert merged2.tp1_exit_pct + merged2.tp2_exit_pct <= 95.0


def test_position_tracker_full_tp1_be_tp2_tp3_lifecycle():
    db = _make_memory_db()
    t0 = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)
    trade = SignalTrade(
        trade_code="NXV-TEST-0001",
        idempotency_key="idem-test-0001",
        symbol="EURUSD",
        market_class="FOREX",
        timeframe="4H",
        risk_tier="SAFE",
        direction="LONG",
        entry_module="SWEEP",
        status="PENDING_LIMIT",
        outcome="OPEN",
        entry_price=1.10000,
        current_price=1.10200,
        initial_sl=1.09500,
        current_sl=1.09500,
        tp1=1.11000,   # 2R
        tp2=1.11500,   # 3R
        tp3=1.12500,   # 5R
        tp1_exit_pct=50.0,
        tp2_exit_pct=30.0,
        tp3_exit_pct=20.0,
        remaining_pct=100.0,
        position_size_lots=0.20,
        confluence_score=9.2,
        grade="A+",
        bars_remaining=10,
    )
    db.add(trade)
    db.commit()

    # 1. Limit Fill
    evs = track_open_trade_with_candle(db, trade, Candle(t0 + timedelta(hours=4), 1.1015, 1.1025, 1.0995, 1.1020))
    assert trade.status == "ACTIVE"
    assert trade.fill_price == 1.10000
    assert any(e.event_type == "LIMIT_FILLED" for e in evs)

    # 2. TP1 Hit -> 50% closed, SL automatically moved to Break-Even (1.10000)
    evs = track_open_trade_with_candle(db, trade, Candle(t0 + timedelta(hours=8), 1.1020, 1.1105, 1.1015, 1.1095))
    assert trade.status == "TP1_HIT"
    assert trade.tp1_hit is True
    assert trade.remaining_pct == 50.0
    assert trade.current_sl == 1.10000
    assert abs(trade.realized_r - 1.0) < 0.01  # 50% * 2R = +1.0R
    assert any(e.event_type == "TP1_HIT" for e in evs)

    # 3. TP2 Hit -> 30% closed, SL automatically moved to TP1 (1.11000)
    evs = track_open_trade_with_candle(db, trade, Candle(t0 + timedelta(hours=12), 1.1095, 1.1155, 1.1090, 1.1145))
    assert trade.status == "TP2_HIT"
    assert trade.tp2_hit is True
    assert trade.remaining_pct == 20.0
    assert trade.current_sl == 1.11000
    assert abs(trade.realized_r - 1.9) < 0.01  # 1.0R + 30%*3R = 1.9R

    # 4. TP3 Hit -> remaining 20% closed -> CLOSED_WIN
    evs = track_open_trade_with_candle(db, trade, Candle(t0 + timedelta(hours=16), 1.1145, 1.1255, 1.1140, 1.1250))
    assert trade.status == "CLOSED_WIN"
    assert trade.outcome == "WIN"
    assert trade.tp3_hit is True
    assert trade.remaining_pct == 0.0
    assert abs(trade.realized_r - 2.9) < 0.01  # 1.9R + 20%*5R = 2.9R
    db.close()


def test_position_tracker_sl_and_expiry():
    db = _make_memory_db()
    t0 = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)
    trade = SignalTrade(
        trade_code="NXV-TEST-SL",
        idempotency_key="idem-test-sl",
        symbol="XAUUSD",
        market_class="METALS",
        timeframe="15m",
        risk_tier="MEDIUM_RISK",
        direction="SHORT",
        entry_module="CHoCH",
        status="ACTIVE",
        outcome="OPEN",
        entry_price=2660.0,
        fill_price=2660.0,
        current_price=2660.0,
        initial_sl=2670.0,
        current_sl=2670.0,
        tp1=2640.0,
        tp2=2630.0,
        tp3=2610.0,
        remaining_pct=100.0,
        position_size_lots=0.1,
        confluence_score=8.5,
        grade="A",
    )
    db.add(trade)
    db.commit()

    evs = track_open_trade_with_candle(db, trade, Candle(t0, 2662.0, 2672.0, 2659.0, 2671.0))
    assert trade.status == "CLOSED_LOSS"
    assert trade.outcome == "LOSS"
    assert trade.realized_r == -1.0
    assert any(e.event_type == "SL_HIT" for e in evs)
    db.close()


def test_market_data_auto_failover_on_twelvedata_rate_limit_and_cooldown(monkeypatch):
    """
    Verifies that when Twelve Data hits its free-tier 429/credit limit, the router immediately
    trips a cooldown on Twelve Data and seamlessly switches to biquote.io (free no-key) without
    re-hitting Twelve Data during the cooldown window.
    """
    import httpx
    from datetime import timedelta
    from app.config import Settings
    from app.engine import market_data

    market_data.reset_provider_cooldowns()
    calls: list[str] = []
    base_ts = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)

    biquote_bars = [
        {
            "openTime": (base_ts - timedelta(minutes=15 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "open": 2650.0 + i * 0.1,
            "high": 2652.0 + i * 0.1,
            "low": 2649.0 + i * 0.1,
            "close": 2651.0 + i * 0.1,
            "tickVolume": 120,
            "isOpen": i == 0,
        }
        for i in range(80)
    ]

    class DummyResp:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload
            self.headers = {}

        def json(self):
            return self._payload

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None):
            calls.append(url)
            if "api.twelvedata.com" in url:
                return DummyResp(
                    200,
                    {
                        "status": "error",
                        "code": 429,
                        "message": "You have run out of API credits for the current minute.",
                    },
                )
            if "biquote.io" in url:
                return DummyResp(200, {"symbol": "XAUUSD", "interval": "15m", "bars": biquote_bars})
            return DummyResp(500, {})

    monkeypatch.setattr(httpx, "Client", DummyClient)
    monkeypatch.setattr(
        market_data,
        "get_settings",
        lambda: Settings(
            nexvora_data_mode="live",
            twelve_data_api_key="dummy-key-1",
            market_data_providers="twelvedata,biquote,yahoo",
        ),
    )

    # First call: Twelve Data returns credit limit error -> instant failover to biquote.io
    s1 = market_data.get_market_series("XAUUSD", "15m", limit=80, force_refresh=True)
    assert s1.is_demo_data is False
    assert "biquote.io" in s1.source
    assert len(s1.candles) == 80
    # Verify chronological ordering (oldest -> newest)
    assert s1.candles[0].timestamp < s1.candles[-1].timestamp
    assert any("api.twelvedata.com" in u for u in calls)
    assert any("biquote.io" in u for u in calls)

    # Second call (different symbol) during cooldown: Twelve Data MUST be skipped immediately!
    calls.clear()
    s2 = market_data.get_market_series("EURUSD", "15m", limit=80, force_refresh=True)
    assert "biquote.io" in s2.source
    assert not any("api.twelvedata.com" in u for u in calls)
    market_data.reset_provider_cooldowns()


def test_signal_fields_are_pure_python_types_and_psycopg2_numpy_adapters_registered():
    """Ensures PostgreSQL (psycopg2) never fails with `can't adapt type 'numpy.float64'`."""
    import numpy as np
    from psycopg2.extensions import adapt
    from app.database import _register_numpy_psycopg2_adapters

    _register_numpy_psycopg2_adapters()
    assert adapt(np.float64(1.12345)).getquoted() == b"1.12345"
    assert adapt(np.int64(42)).getquoted() == b"42"

    series = generate_deterministic_replay_series("EURUSD", "4H", limit=900)
    h1, h2 = _htf_for("EURUSD", "4H")
    ev = run_trading_hub3_engine("EURUSD", "4H", series.candles, htf1_candles=h1, htf2_candles=h2)
    assert len(ev.historical_signals) > 0
    for sig in ev.historical_signals:
        for field_name, val in sig.__dict__.items():
            assert not type(val).__module__.startswith("numpy"), (
                f"NumPy type leaked in TradeSetupSignal.{field_name}: {type(val)}"
            )


def test_official_signal_card_png_and_early_be_at_70pct():
    import io
    from PIL import Image
    from app.services.signal_card import render_signal_card_png

    db = _make_memory_db()
    t0 = datetime(2026, 11, 22, 8, 0, tzinfo=timezone.utc)
    trade = SignalTrade(
        trade_code="NXV-CARD-0001",
        idempotency_key="idem-card-0001",
        symbol="XAUUSD",
        market_class="METALS",
        timeframe="15m",
        risk_tier="MEDIUM_RISK",
        direction="LONG",
        entry_module="SWEEP",
        status="ACTIVE",
        outcome="OPEN",
        entry_price=2700.0,
        fill_price=2700.0,
        current_price=2700.0,
        initial_sl=2690.0,
        current_sl=2690.0,
        tp1=2712.0,   # 1.2R
        tp2=2722.0,   # 2.2R
        tp3=2732.0,   # 3.2R
        tp1_exit_pct=50.0,
        tp2_exit_pct=30.0,
        tp3_exit_pct=20.0,
        remaining_pct=100.0,
        position_size_lots=0.10,
        confluence_score=9.2,
        grade="A+",
        htf_bias="BULLISH",
        backtest_win_rate_at_entry=78.5,
        eligible_for_telegram=True,
        bars_remaining=10,
    )
    db.add(trade)
    db.commit()

    # Candle reaches 70% of entry-to-TP1 (2700 + 0.70*12 = 2708.4) without hitting TP1 (2712)
    evs = track_open_trade_with_candle(
        db, trade, Candle(t0 + timedelta(minutes=15), 2701.0, 2709.0, 2700.5, 2708.5)
    )
    assert trade.tp1_hit is False
    assert trade.current_sl == 2700.0
    assert any(e.event_type == "SL_MOVED_BE" for e in evs)

    # Render official 1080x1350 NEXVORA Telegram Signal Card PNG
    series = generate_deterministic_replay_series("XAUUSD", "15m", limit=120)
    png_bytes = render_signal_card_png(trade, candles=series.candles, adx_value=36.0)
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    im = Image.open(io.BytesIO(png_bytes))
    assert im.size == (1080, 1350)
    db.close()



