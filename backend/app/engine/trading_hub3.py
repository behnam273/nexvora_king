from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.config import SYMBOL_META, TIMEFRAME_META
from app.engine.market_data import Candle
from app.engine.policy import TRADING_POLICY_VERSION, TimeframePolicy, get_policy


@dataclass
class HighAccuracyParams:
    """
    Engine parameters.

    ``policy`` holds the per-timeframe risk profile (stops, targets, gates).
    The remaining fields are hub3.txt core constants that do not change per
    timeframe.
    """
    policy: TimeframePolicy = field(default_factory=lambda: get_policy("15m"))

    # hub3.txt core constants
    disp_atr_mult: float = 0.80       # "strong" displacement body for FVG/OB creation
    choch_body_atr: float = 0.45      # min CHoCH body (ATR multiple) -> real intent, not noise
    choch_close_frac: float = 0.55    # CHoCH close must sit in this fraction of the bar range
    poi_dist_atr: float = 0.20        # min distance of POI from current price
    fvg_min_atr: float = 0.22         # min FVG size
    ob_lookback: int = 20
    ifc_mult: float = 1.8
    eq_tol_atr: float = 0.15
    spike_mult: float = 2.5           # reject news/panic candles
    vol_min_ratio: float = 0.70       # reject dead volatility
    pd_len: int = 18                  # premium/discount dealing range

    # execution assumptions (also used by the backtester / position tracker)
    slippage_atr: float = 0.02
    commission_r: float = 0.04

    risk_pct: float = 1.0
    account_equity_ref: float = 10000.0
    trend_ema_len: int = 200

    # Legacy field kept so older call sites keep working; policy wins when set.
    timeframe: str = "15m"

    def __post_init__(self) -> None:
        # Allow `HighAccuracyParams(timeframe="5m")` and keep policy in sync.
        if self.policy.timeframe != self.timeframe:
            self.policy = get_policy(self.timeframe)

    @property
    def min_score(self) -> float:
        return self.policy.min_score

    @property
    def min_adx(self) -> float:
        return self.policy.min_adx

    @property
    def tp1_rr(self) -> float:
        return self.policy.tp1_rr

    @property
    def tp2_rr(self) -> float:
        return self.policy.tp2_rr

    @property
    def tp3_rr(self) -> float:
        return self.policy.tp3_rr

    @property
    def tp1_exit_pct(self) -> float:
        return self.policy.tp1_exit_pct

    @property
    def tp2_exit_pct(self) -> float:
        return self.policy.tp2_exit_pct

    @property
    def require_sweep(self) -> bool:
        # Sweep is the backbone of the style — never optional.
        return True

    @property
    def require_idm(self) -> bool:
        return True

    @property
    def require_strong_choch_body(self) -> bool:
        return True


@dataclass
class LiquidityLevel:
    price: float
    kind: int          # +1 = buy-side (high), -1 = sell-side (low)
    used: bool = False
    is_equal: bool = False
    bar_idx: int = 0


@dataclass
class POIZone:
    top: float
    bot: float
    direction: int     # +1 bull, -1 bear
    poi_type: int      # 1=FVG, 2=OB, 3=SCOB, 4=FLIP, 5=IFC
    bar_idx: int
    quality: float


@dataclass
class TradeSetupSignal:
    bar_idx: int
    timestamp: datetime
    symbol: str
    timeframe: str
    risk_tier: str
    direction: str          # LONG | SHORT
    entry_module: str       # CHoCH | SWEEP | FLIP | OB | FVG | SCOB | IFC
    entry_price: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    tp1_exit_pct: float
    tp2_exit_pct: float
    tp3_exit_pct: float
    confluence_score: float
    grade: str              # A+ | A | B
    htf_bias: str           # BULLISH | BEARISH | NEUTRAL
    session_name: str
    position_size_lots: float
    checklist: List[dict]
    rationale_fa: str
    bars_valid: int
    risk_atr: float = 0.0
    risk_pips: float = 0.0
    adx_value: float = 0.0
    atr_value: float = 0.0
    policy_version: str = TRADING_POLICY_VERSION
    early_be_price: float = 0.0
    pending_expiry_hours: int = 24


@dataclass
class EngineEvaluation:
    symbol: str
    timeframe: str
    risk_tier: str
    state: str              # FLAT | ARMED | SETUP_READY
    htf_bias: str
    session_name: str
    adx_value: float
    atr_value: float
    readiness_pct: int
    why_no_trade_fa: str
    active_poi_count: int
    active_liq_count: int
    latest_signal: Optional[TradeSetupSignal] = None
    historical_signals: List[TradeSetupSignal] = field(default_factory=list)
    rejection_counts: Dict[str, int] = field(default_factory=dict)
    policy: Optional[TimeframePolicy] = None
    di_plus: float = 0.0
    di_minus: float = 0.0


# -------------------- Technical Indicators --------------------

def compute_ema(values: np.ndarray, length: int) -> np.ndarray:
    n = len(values)
    out = np.full(n, np.nan, dtype=np.float64)
    if n == 0 or length <= 0:
        return out
    alpha = 2.0 / (length + 1.0)
    out[0] = values[0]
    for i in range(1, n):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def compute_rma(values: np.ndarray, length: int) -> np.ndarray:
    n = len(values)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < length or length <= 0:
        return out
    out[length - 1] = float(np.mean(values[:length]))
    alpha = 1.0 / length
    for i in range(length, n):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def compute_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, length: int = 14) -> np.ndarray:
    n = len(closes)
    tr = np.zeros(n, dtype=np.float64)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = compute_rma(tr, length)
    # Fill early bars with simple average so indicator never breaks
    for i in range(min(length - 1, n)):
        atr[i] = float(np.mean(tr[: i + 1]))
    return atr


def compute_sma(values: np.ndarray, length: int) -> np.ndarray:
    n = len(values)
    out = np.full(n, np.nan, dtype=np.float64)
    for i in range(n):
        start = max(0, i - length + 1)
        window = values[start : i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) > 0:
            out[i] = float(np.mean(valid))
    return out


def compute_adx_di(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    length: int = 14,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Wilder's ADX together with +DI / -DI.

    Returns ``(adx, plus_di, minus_di)``. The DI pair is what actually tells us
    whether the *dominant* side of the market agrees with the setup direction —
    ADX alone only says "there is a trend somewhere".
    """
    n = len(closes)
    if n < length + 2:
        flat = np.full(n, 25.0, dtype=np.float64)
        return flat, np.full(n, 25.0, dtype=np.float64), np.full(n, 25.0, dtype=np.float64)

    up_move = np.zeros(n, dtype=np.float64)
    dn_move = np.zeros(n, dtype=np.float64)
    tr = np.zeros(n, dtype=np.float64)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        up_move[i] = up if (up > dn and up > 0) else 0.0
        dn_move[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = compute_rma(tr, length)
    plus_dm = compute_rma(up_move, length)
    minus_dm = compute_rma(dn_move, length)

    plus_di = np.full(n, 25.0, dtype=np.float64)
    minus_di = np.full(n, 25.0, dtype=np.float64)
    dx = np.zeros(n, dtype=np.float64)
    for i in range(n):
        if np.isnan(atr[i]) or atr[i] <= 0:
            continue
        pdi = 100.0 * plus_dm[i] / atr[i]
        mdi = 100.0 * minus_dm[i] / atr[i]
        plus_di[i] = pdi
        minus_di[i] = mdi
        denom = pdi + mdi
        dx[i] = (100.0 * abs(pdi - mdi) / denom) if denom > 0 else 0.0

    adx = compute_rma(dx, length)
    for i in range(n):
        if np.isnan(adx[i]):
            adx[i] = 25.0
    return adx, plus_di, minus_di


def compute_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, length: int = 14) -> np.ndarray:
    return compute_adx_di(highs, lows, closes, length)[0]


def classify_session_ny(ts_utc: datetime) -> Tuple[str, bool, bool, bool]:
    """
    Classify the trading session using hub3.txt America/New_York windows:
    London: 02:00-05:00 NY, NY AM: 07:00-10:00 NY, NY PM: 13:30-16:00 NY,
    Asia: 20:00-23:59 NY.

    Uses a deterministic UTC-5 approximation (NY EST) so behaviour is stable and
    identical between backtests and live scans.

    Returns (session_name, in_active_killzone, in_asia, in_london).
    """
    utc = ts_utc.astimezone(timezone.utc)
    ny_hour = (utc.hour - 4) % 24   # NY local = UTC-4 (DST-approx, matches hub3 02:00-05:00 London window)
    hm = ny_hour * 60 + utc.minute

    in_asia = 20 * 60 <= hm <= 23 * 60 + 59
    in_london = 2 * 60 <= hm <= 5 * 60
    in_ny_am = 7 * 60 <= hm <= 10 * 60
    in_ny_pm = 13 * 60 + 30 <= hm <= 16 * 60

    in_active = in_london or in_ny_am or in_ny_pm
    if in_london:
        name = "LONDON"
    elif in_ny_am:
        name = "NEW YORK AM"
    elif in_ny_pm:
        name = "NEW YORK PM"
    elif in_asia:
        name = "ASIA"
    else:
        name = "OFF-SESSION"
    return name, in_active, in_asia, in_london


def compute_htf_bias_from_candles(
    htf_candles: Optional[List[Candle]],
    ema_len: int = 50,
    atr_len: int = 14,
) -> int:
    """
    Directional bias of a higher timeframe.

    Uses the classic hub3 rule (close vs EMA) but *requires* the EMA itself to be
    sloping in the same direction, so a flat, coiled market yields NEUTRAL
    instead of a random long/short bias.
    """
    if not htf_candles or len(htf_candles) < 15:
        return 0
    closes = np.array([c.close for c in htf_candles], dtype=np.float64)
    ema = compute_ema(closes, min(ema_len, max(5, len(closes) - 1)))
    look = min(5, len(ema) - 1)
    if look <= 0:
        return 0
    slope = ema[-1] - ema[-1 - look]
    # Noise threshold proportional to the average bar range of the HTF series
    ranges = np.array([c.high - c.low for c in htf_candles[-30:]], dtype=np.float64)
    noise = float(np.mean(ranges)) * 0.35 if len(ranges) else 0.0

    if closes[-1] > ema[-1] and slope > noise:
        return 1
    if closes[-1] < ema[-1] and -slope > noise:
        return -1
    return 0


def _score_to_grade(score: float) -> str:
    if score >= 9.0:
        return "A+"
    if score >= 8.0:
        return "A"
    if score >= 7.0:
        return "B"
    return "C"


def _usd_per_price_unit_per_lot(symbol: str, price: float) -> float:
    if symbol == "XAUUSD":
        return 100.0
    if symbol == "USDJPY":
        return 100000.0 / max(price, 1.0)
    if symbol.endswith("USD"):
        return 100000.0
    # EURGBP (quoted in GBP) -> approximate via GBPUSD
    return 100000.0 * 1.27


def _compute_lot_size(symbol: str, entry: float, sl: float, risk_pct: float, equity: float) -> float:
    dist = abs(entry - sl)
    if dist <= 0:
        return 0.01
    risk_money = equity * (risk_pct / 100.0)
    usd_per_unit_per_lot = _usd_per_price_unit_per_lot(symbol, entry)
    lots = risk_money / (dist * usd_per_unit_per_lot)
    return round(max(0.01, min(lots, 50.0)), 2)


# Reason codes recorded for every rejected setup attempt. These feed the PWA so
# the user always sees *why* the engine is flat instead of a vague message.
REJECTION_LABELS_FA: Dict[str, str] = {
    "no_sweep": "بدون سوییپ نقدینگی",
    "no_idm": "بدون برداشته‌شدن IDM",
    "cooldown": "دوره کول‌داون",
    "spike": "کندل انفجاری/خبری",
    "dead_vol": "نوسان مرده",
    "adx": "بازار رِنج (ADX پایین)",
    "session": "خارج از سشن لندن/نیویورک",
    "news": "گارد خبری فعال",
    "no_choch": "بدون CHoCH تأییدشده (سطح ساختار شکسته نشد)",
    "choch_body": "شکست ساختار بدون بدنه/بسته‌شدن معتبر",
    "htf_bias": "ناهم‌جهت با بایاس HTF",
    "htf2_bias": "ناهم‌جهت با HTF دوم",
    "di": "ناهم‌جهت با DI غالب",
    "no_poi": "بدون زون ورود معتبر",
    "poi_quality": "کیفیت زون پایین",
    "poi_stale": "زون ورود قدیمی",
    "pd_zone": "ورود در ناحیه اشتباه پریمیوم/دیسکانت",
    "stop_too_wide": "حد ضرر بیش از حد گشاد",
    "stop_too_tight": "حد ضرر غیرممکن (فشرده)",
    "rr": "نسبت R:R کافی نیست",
    "no_room": "فضای سود تا نقدینگی کافی نیست",
    "score": "امتیاز کانفلوئنس پایین",
}


def run_trading_hub3_engine(
    symbol: str,
    timeframe: str,
    candles: List[Candle],
    params: Optional[HighAccuracyParams] = None,
    htf1_candles: Optional[List[Candle]] = None,
    htf2_candles: Optional[List[Candle]] = None,
    news_blackout_active: bool = False,
) -> EngineEvaluation:
    """
    Faithful Python implementation of hub3.txt (Trading Hub 3.0 SMC engine) with
    the strict NEXVORA policy gate on top.

    Chain of evidence, in order (nothing can be skipped):
        liquidity sweep -> arm -> CHoCH -> POI zone -> location check ->
        ADX/DI regime -> HTF alignment -> structural stop within bounds ->
        R:R room check -> confluence score
    """
    if params is None:
        params = HighAccuracyParams(policy=get_policy(timeframe))
    else:
        # The caller may pass a shared params object; always bind the TF policy.
        params = HighAccuracyParams(
            policy=params.policy if params.policy.timeframe == timeframe else get_policy(timeframe),
            disp_atr_mult=params.disp_atr_mult,
            choch_body_atr=params.choch_body_atr,
            choch_close_frac=params.choch_close_frac,
            poi_dist_atr=params.poi_dist_atr,
            fvg_min_atr=params.fvg_min_atr,
            ob_lookback=params.ob_lookback,
            ifc_mult=params.ifc_mult,
            eq_tol_atr=params.eq_tol_atr,
            spike_mult=params.spike_mult,
            vol_min_ratio=params.vol_min_ratio,
            pd_len=params.pd_len,
            slippage_atr=params.slippage_atr,
            commission_r=params.commission_r,
            risk_pct=params.risk_pct,
            account_equity_ref=params.account_equity_ref,
            trend_ema_len=params.trend_ema_len,
            timeframe=timeframe,
        )

    pol = params.policy
    meta = SYMBOL_META[symbol]
    tf_meta = TIMEFRAME_META[timeframe]
    digits = meta["digits"]
    pip_size = meta["pip_size"]
    risk_tier = tf_meta["risk_tier"]

    n = len(candles)
    if n < 120:
        return EngineEvaluation(
            symbol=symbol,
            timeframe=timeframe,
            risk_tier=risk_tier,
            state="FLAT",
            htf_bias="NEUTRAL",
            session_name="OFF-SESSION",
            adx_value=0.0,
            atr_value=0.0,
            readiness_pct=0,
            why_no_trade_fa="داده کندلی کافی برای ارزیابی Trading Hub 3.0 وجود ندارد.",
            active_poi_count=0,
            active_liq_count=0,
            policy=pol,
        )

    opens = np.array([c.open for c in candles], dtype=np.float64)
    highs = np.array([c.high for c in candles], dtype=np.float64)
    lows = np.array([c.low for c in candles], dtype=np.float64)
    closes = np.array([c.close for c in candles], dtype=np.float64)

    atr_arr = compute_atr(highs, lows, closes, 14)
    atr_sma50 = compute_sma(atr_arr, 50)
    adx_arr, pdi_arr, mdi_arr = compute_adx_di(highs, lows, closes, 14)
    ema_htf_proxy = compute_ema(closes, 50)
    ema_slow = compute_ema(closes, min(params.trend_ema_len, max(30, n // 2)))

    # HTF bias is rebuilt bar-by-bar from the HTF series (no look-ahead): only
    # candles that had already closed at the time of the signal are used.
    htf1_full = htf1_candles or []
    htf2_full = htf2_candles or []

    def htf_bases_at(ts: datetime) -> Tuple[int, int]:
        c1 = [c for c in htf1_full if c.timestamp <= ts] if htf1_full else []
        c2 = [c for c in htf2_full if c.timestamp <= ts] if htf2_full else []
        b1 = compute_htf_bias_from_candles(c1[-120:], 50) if len(c1) >= 15 else 0
        b2 = compute_htf_bias_from_candles(c2[-120:], 50) if len(c2) >= 15 else 0
        return b1, b2

    htf1_bias_global = compute_htf_bias_from_candles(htf1_full, 50)
    htf2_bias_global = compute_htf_bias_from_candles(htf2_full, 50)

    pivot_len = tf_meta["pivot_len"]
    minor_len = 2
    cooldown_bars = pol.cooldown_bars
    arm_valid_bars = pol.arm_valid_bars

    liq_levels: List[LiquidityLevel] = []
    poi_zones: List[POIZone] = []
    max_liq = 18
    max_poi = 12

    last_ph: Optional[float] = None
    last_pl: Optional[float] = None
    minor_ph: Optional[float] = None
    minor_pl: Optional[float] = None
    minor_ph_bar = -1
    minor_pl_bar = -1
    idm_done = False

    day_id: Optional[int] = None
    asia_h: Optional[float] = None
    asia_l: Optional[float] = None
    was_asia = False
    ldn_h: Optional[float] = None
    ldn_l: Optional[float] = None
    was_london = False

    arm_dir = 0
    arm_bar = -999
    arm_price = 0.0
    arm_struct = 0.0
    arm_eq = False
    arm_swept = False
    arm_run_high = 0.0   # highest high formed after a low sweep (long trigger)
    arm_run_low = 0.0    # lowest low formed after a high sweep (short trigger)
    arm_extreme = 0.0    # swept extreme (low for longs / high for shorts) — anchor of the dealing range
    arm_struct_bar = -1  # bar index of the structure level currently being watched
    last_signal_bar = -999

    signals: List[TradeSetupSignal] = []
    rejection_counts: Dict[str, int] = {}
    last_why_fa = "در انتظار سوییپ نقدینگی معتبر..."

    def reject(code: str, msg_fa: str) -> None:
        nonlocal last_why_fa
        rejection_counts[code] = rejection_counts.get(code, 0) + 1
        last_why_fa = msg_fa

    def find_near_liq(px: float, kind: int, tol: float) -> int:
        for idx, lv in enumerate(liq_levels):
            if lv.kind == kind and abs(lv.price - px) <= tol:
                return idx
        return -1

    def liq_target(from_px: float, direction: int, min_dist: float) -> Optional[float]:
        best: Optional[float] = None
        for lv in liq_levels:
            if not lv.used and lv.kind == (1 if direction > 0 else -1):
                d = (lv.price - from_px) * direction
                if d >= min_dist:
                    if best is None or d < (best - from_px) * direction:
                        best = lv.price
        return best

    def add_liq(px: float, kind: int, bar_idx: int, tol: float) -> None:
        near = find_near_liq(px, kind, tol)
        if near >= 0:
            liq_levels[near].is_equal = True
            return
        if len(liq_levels) >= max_liq:
            liq_levels.pop(0)
        liq_levels.append(LiquidityLevel(price=px, kind=kind, bar_idx=bar_idx))

    def add_poi(top: float, bot: float, direction: int, poi_type: int, quality: float, bar_idx: int) -> None:
        if top <= bot:
            return
        if len(poi_zones) >= max_poi:
            poi_zones.pop(0)
        poi_zones.append(
            POIZone(top=top, bot=bot, direction=direction, poi_type=poi_type, bar_idx=bar_idx, quality=quality)
        )

    def pick_poi(
        direction: int, since_bar: int, close_px: float, atr_val: float
    ) -> List[POIZone]:
        """
        Candidate POIs on the correct side of price, best first.

        Ranking is quality first (SCOB/IFC/OB beat a bare FVG) and recency
        second, because the newest zone is not necessarily the strongest one.
        All candidates are returned so the caller can fall through to the next
        zone if the best one does not pass the risk/location gates.
        """
        candidates: List[POIZone] = []
        for z in poi_zones:
            if z.direction != direction:
                continue
            if z.bar_idx < since_bar - 4:
                continue
            if i - z.bar_idx > pol.max_poi_age_bars:
                continue
            mid = (z.top + z.bot) / 2.0
            if direction == 1 and mid < close_px - params.poi_dist_atr * atr_val:
                candidates.append(z)
            elif direction == -1 and mid > close_px + params.poi_dist_atr * atr_val:
                candidates.append(z)
        candidates.sort(key=lambda z: (z.quality, z.bar_idx), reverse=True)
        return candidates

    def impulse_poi(direction: int, from_bar: int, to_bar: int, atr_val: float) -> List[POIZone]:
        """
        Entry zones created by the CHoCH displacement itself.

        When the CHoCH candle confirms the shift we look *inside* the impulse leg
        (from the sweep bar to the trigger bar) for:

        * the origin order block  -> last opposite-colour candle before the move
        * any fair value gap      -> imbalance left unfilled by the displacement

        These are the zones the institutional entry is actually taken from, and
        because they are derived at trigger time they are never stale.
        """
        lo_bar = max(from_bar, to_bar - 25)
        out: List[POIZone] = []
        if to_bar - lo_bar < 2:
            return out

        # --- origin order block ---
        ob_idx = -1
        if direction == 1:
            best_low = None
            for j in range(to_bar - 1, lo_bar - 1, -1):
                if closes[j] < opens[j]:  # bearish candle = origin of a bullish leg
                    if best_low is None or lows[j] < best_low:
                        best_low = float(lows[j])
                        ob_idx = j
                    if ob_idx >= 0 and j < to_bar - 4:
                        break
        else:
            best_high = None
            for j in range(to_bar - 1, lo_bar - 1, -1):
                if closes[j] > opens[j]:
                    if best_high is None or highs[j] > best_high:
                        best_high = float(highs[j])
                        ob_idx = j
                    if ob_idx >= 0 and j < to_bar - 4:
                        break
        if ob_idx >= 0:
            out.append(
                POIZone(
                    top=float(highs[ob_idx]),
                    bot=float(lows[ob_idx]),
                    direction=direction,
                    poi_type=2,
                    bar_idx=ob_idx,
                    quality=1.2,
                )
            )

        # --- fair value gaps inside the impulse ---
        for j in range(lo_bar + 2, to_bar + 1):
            if direction == 1 and lows[j] > highs[j - 2] and (lows[j] - highs[j - 2]) >= 0.15 * atr_val:
                out.append(
                    POIZone(
                        top=float(lows[j]),
                        bot=float(highs[j - 2]),
                        direction=1,
                        poi_type=1,
                        bar_idx=j - 2,
                        quality=1.0,
                    )
                )
            if direction == -1 and highs[j] < lows[j - 2] and (lows[j - 2] - highs[j]) >= 0.15 * atr_val:
                out.append(
                    POIZone(
                        top=float(lows[j - 2]),
                        bot=float(highs[j]),
                        direction=-1,
                        poi_type=1,
                        bar_idx=j - 2,
                        quality=1.0,
                    )
                )
        return out

    start = max(30, pivot_len * 2 + 1)

    for i in range(start, n):
        c = candles[i]
        o, h, l, cl = opens[i], highs[i], lows[i], closes[i]
        atr = atr_arr[i] if atr_arr[i] > 0 else pip_size * 10
        adx = adx_arr[i]
        pdi = pdi_arr[i]
        mdi = mdi_arr[i]
        ses_name, in_session, in_asia, in_london = classify_session_ny(c.timestamp)

        # ---------------- 1. Daily & session liquidity (hub3 §1) ----------------
        cur_day = c.timestamp.day
        if day_id is None or cur_day != day_id:
            if i > 0:
                add_liq(highs[i - 1], 1, i - 1, params.eq_tol_atr * atr)
                add_liq(lows[i - 1], -1, i - 1, params.eq_tol_atr * atr)
            day_id = cur_day
        if in_asia:
            asia_h = h if asia_h is None else max(asia_h, h)
            asia_l = l if asia_l is None else min(asia_l, l)
            was_asia = True
        elif was_asia:
            if asia_h is not None:
                add_liq(asia_h, 1, i, params.eq_tol_atr * atr)
            if asia_l is not None:
                add_liq(asia_l, -1, i, params.eq_tol_atr * atr)
            asia_h = asia_l = None
            was_asia = False
        if in_london:
            ldn_h = h if ldn_h is None else max(ldn_h, h)
            ldn_l = l if ldn_l is None else min(ldn_l, l)
            was_london = True
        elif was_london:
            if ldn_h is not None:
                add_liq(ldn_h, 1, i, params.eq_tol_atr * atr)
            if ldn_l is not None:
                add_liq(ldn_l, -1, i, params.eq_tol_atr * atr)
            ldn_h = ldn_l = None
            was_london = False

        # ---------------- 2. Confirmed pivots (non-repainting) ----------------
        pc = i - pivot_len
        if pc >= pivot_len:
            win_h = highs[pc - pivot_len : pc + pivot_len + 1]
            win_l = lows[pc - pivot_len : pc + pivot_len + 1]
            if highs[pc] == np.max(win_h):
                last_ph = float(highs[pc])
                add_liq(last_ph, 1, pc, params.eq_tol_atr * atr)
            if lows[pc] == np.min(win_l):
                last_pl = float(lows[pc])
                add_liq(last_pl, -1, pc, params.eq_tol_atr * atr)

        mc = i - minor_len
        if mc >= minor_len:
            mwin_h = highs[mc - minor_len : mc + minor_len + 1]
            mwin_l = lows[mc - minor_len : mc + minor_len + 1]
            if highs[mc] == np.max(mwin_h):
                minor_ph = float(highs[mc])
                minor_ph_bar = mc
            if lows[mc] == np.min(mwin_l):
                minor_pl = float(lows[mc])
                minor_pl_bar = mc

        hi20 = float(np.max(highs[i - 20 : i]))
        lo20 = float(np.min(lows[i - 20 : i]))

        # ---------------- 3. POI detection (hub3 §3-5) ----------------
        body = abs(cl - o)
        strong = body >= params.disp_atr_mult * atr
        if strong and l > highs[i - 2] and (l - highs[i - 2]) >= params.fvg_min_atr * atr:
            add_poi(l, float(highs[i - 2]), 1, 1, 1.0, i - 2)
        if strong and h < lows[i - 2] and (lows[i - 2] - h) >= params.fvg_min_atr * atr:
            add_poi(float(lows[i - 2]), h, -1, 1, 1.0, i - 2)

        if strong:
            opp_idx = -1
            for j in range(1, min(params.ob_lookback, i) + 1):
                opp_col = (closes[i - j] > opens[i - j]) if cl < o else (closes[i - j] < opens[i - j])
                if opp_col:
                    opp_idx = j
                    break
            if opp_idx > 0:
                is_scob = opp_idx == 1
                typ = 3 if is_scob else 2
                q = 1.5 if is_scob else 1.2
                add_poi(
                    float(highs[i - opp_idx]),
                    float(lows[i - opp_idx]),
                    -1 if cl < o else 1,
                    typ,
                    q,
                    i - opp_idx,
                )

        if body >= params.ifc_mult * atr:
            if cl > o and cl > hi20:
                add_poi(max(cl, o), min(cl, o), 1, 5, 1.5, i - 1)
            elif cl < o and cl < lo20:
                add_poi(max(cl, o), min(cl, o), -1, 5, 1.5, i - 1)

        # ---------------- 4. POI maintenance & flip (hub3 §6) ----------------
        for z_idx in range(len(poi_zones) - 1, -1, -1):
            z = poi_zones[z_idx]
            # hub3 §6: a wick into the zone consumes it; if the candle did not
            # actually close through the far edge the zone flips and is reused
            # from the other side (this is a major source of valid entries).
            dead = (l <= z.bot) if z.direction == 1 else (h >= z.top)
            if dead:
                can_flip = z.poi_type in (2, 3) and not ((cl < z.bot) if z.direction == 1 else (cl > z.top))
                if can_flip:
                    span = z.top - z.bot
                    if z.direction == 1:
                        nt, nb = z.bot, z.bot - span
                    else:
                        nt, nb = z.top + span, z.top
                    z.direction = -z.direction
                    z.poi_type = 4
                    z.top = max(nt, nb)
                    z.bot = min(nt, nb)
                    z.bar_idx = i
                else:
                    poi_zones.pop(z_idx)

        # ---------------- 5. Liquidity sweeps (hub3 §7) ----------------
        swept_high = False
        swept_low = False
        swept_eq = False
        for lv in liq_levels:
            if lv.used:
                continue
            if lv.kind == 1 and h > lv.price and cl < lv.price:
                lv.used = True
                swept_high = True
                if lv.is_equal:
                    swept_eq = True
            elif lv.kind == -1 and l < lv.price and cl > lv.price:
                lv.used = True
                swept_low = True
                if lv.is_equal:
                    swept_eq = True

        if i - arm_bar > 3:
            if h > hi20 and cl < hi20:
                swept_high = True
            if l < lo20 and cl > lo20:
                swept_low = True
            if minor_ph is not None and h > minor_ph and cl < minor_ph and (h - max(o, cl)) >= 0.45 * atr:
                swept_high = True
            if minor_pl is not None and l < minor_pl and cl > minor_pl and (min(o, cl) - l) >= 0.45 * atr:
                swept_low = True

        if minor_pl is not None and l < minor_pl:
            idm_done = True
        if minor_ph is not None and h > minor_ph:
            idm_done = True

        # ---------------- 6. Arm (hub3 §8) ----------------
        if swept_high and (last_pl is not None or minor_pl is not None):
            arm_dir = -1
            arm_bar = i
            arm_price = h
            arm_eq = swept_eq
            arm_swept = True
            # Trigger = lowest low printed after the sweep (micro market-structure shift)
            arm_run_low = l
            arm_struct = l
            arm_extreme = h
            arm_struct_bar = i
            idm_done = False
        if swept_low and (last_ph is not None or minor_ph is not None):
            arm_dir = 1
            arm_bar = i
            arm_price = l
            arm_eq = swept_eq
            arm_swept = True
            # Trigger = highest high printed after the sweep (micro market-structure shift)
            arm_run_high = h
            arm_struct = h
            arm_extreme = l
            arm_struct_bar = i
            idm_done = False

        if arm_dir == 1 and (cl < arm_price or i - arm_bar > arm_valid_bars):
            arm_dir = 0
            arm_swept = False
        if arm_dir == -1 and (cl > arm_price or i - arm_bar > arm_valid_bars):
            arm_dir = 0
            arm_swept = False

        # ---------------- 7. Gates ----------------
        if arm_dir == 0:
            last_why_fa = "هنوز سوییپ نقدینگی معتبر روی سقف/کف کلیدی ثبت نشده است."
            continue

        if i - last_signal_bar < cooldown_bars:
            reject("cooldown", f"در دوره کول‌داون پس از سیگنال قبلی ({cooldown_bars - (i - last_signal_bar)} کندل باقی‌مانده).")
            continue

        bar_range = h - l
        if bar_range > params.spike_mult * atr:
            reject("spike", "کندل انفجاری/خبری شناسایی شد (فیلتر نوسان غیرعادی فعال).")
            continue
        if atr < params.vol_min_ratio * atr_sma50[i]:
            reject("dead_vol", "نوسان بازار کمتر از حد مجاز (بازار کم‌رمق / مرده).")
            continue
        if adx < pol.min_adx:
            reject("adx", f"بازار در حالت رنج است (ADX={adx:.1f} < {pol.min_adx:.0f}).")
            continue
        if news_blackout_active and i == n - 1:
            reject("news", "گارد خبری فعال است (نزدیک به انتشار خبر High Impact).")
            continue
        if pol.require_session and not in_session:
            reject("session", f"خارج از سشن فعال لندن/نیویورک (سشن فعلی: {ses_name}).")
            continue
        if not arm_swept:
            reject("no_sweep", "سوییپ نقدینگی تأیید نشده است.")
            continue
        if pol.require_idm and not idm_done:
            reject("no_idm", "اینداسمنت (IDM) هنوز برداشته نشده است.")
            continue

        # Trading range for premium/discount
        pd_start = max(0, i - params.pd_len + 1)
        rng_hi = float(np.max(highs[pd_start : i + 1]))
        rng_lo = float(np.min(lows[pd_start : i + 1]))

        for candidate_dir in (1, -1):
            if arm_dir != candidate_dir:
                continue

            bar_span = max(h - l, pip_size)
            body_ok = body >= params.choch_body_atr * atr
            if candidate_dir == 1:
                close_ok = (cl - l) >= params.choch_close_frac * bar_span
                choch_ok = cl > arm_struct and body_ok and close_ok
            else:
                close_ok = (h - cl) >= params.choch_close_frac * bar_span
                choch_ok = cl < arm_struct and body_ok and close_ok
            if not choch_ok:
                level_broken = (cl > arm_struct) if candidate_dir == 1 else (cl < arm_struct)
                code = "choch_body" if level_broken else "no_choch"
                reject(
                    code,
                    f"سوییپ انجام شد؛ در انتظار بسته‌شدن کندل قوی CHoCH "
                    f"{'بالای' if candidate_dir == 1 else 'زیر'} {arm_struct:.{digits}f}",
                )
                continue

            # ---- HTF alignment (no look-ahead: bias as of this candle) ----
            b1_at, b2_at = htf_bases_at(c.timestamp)
            if b1_at != 0:
                htf_bias = b1_at
            else:
                htf_bias = 1 if cl > ema_htf_proxy[i] else -1
            if htf_bias != candidate_dir:
                reject("htf_bias", "بایاس تایم‌فریم بالاتر با جهت ستاپ هم‌راستا نیست.")
                continue
            # Dual-HTF confirmation:
            #   * a *contradicting* higher timeframe always blocks the trade
            #   * on the 5m profile we additionally require the second reference
            #     timeframe to actively confirm (it may not be neutral)
            if b2_at != 0 and b2_at != candidate_dir:
                reject("htf2_bias", "تایم‌فریم مرجع دوم (EMA200 / HTF2) خلاف جهت ستاپ است.")
                continue
            if pol.require_dual_htf and b2_at == 0 and pol.timeframe == "5m":
                reject("htf2_bias", "تایم‌فریم مرجع دوم (EMA200 / HTF2) خنثی است؛ تأیید دوعاملی کامل نیست.")
                continue
            if pol.require_di_alignment:
                dominant_ok = (pdi > mdi) if candidate_dir == 1 else (mdi > pdi)
                if not dominant_ok:
                    reject("di", f"DI غالب با جهت ستاپ هم‌سو نیست (DI+={pdi:.1f} / DI-={mdi:.1f}).")
                    continue

            candidates = pick_poi(candidate_dir, arm_bar, cl, atr)
            # Zones created by this very impulse are at least as valid as the
            # ones registered earlier in the session.
            candidates = impulse_poi(candidate_dir, arm_bar, i, atr) + candidates
            # Deep-pullback limit (policy controlled): the resting order is placed
            # at a retracement of the impulse where the risk/reward becomes real.
            # The structural stop stays anchored on the swept extreme.
            imp_top = max(h, arm_struct)
            imp_bot = min(l, arm_extreme) if arm_extreme > 0 else min(l, arm_struct)
            if candidate_dir == 1:
                pb_entry = imp_top - pol.pullback_frac * max(imp_top - imp_bot, pip_size)
            else:
                pb_entry = imp_bot + pol.pullback_frac * max(imp_top - imp_bot, pip_size)
            candidates = candidates + [
                POIZone(
                    top=pb_entry + 0.08 * atr,
                    bot=pb_entry - 0.08 * atr,
                    direction=candidate_dir,
                    poi_type=6,
                    bar_idx=i,
                    quality=1.0,
                )
            ]
            if not candidates:
                reject("no_poi", "ناحیه ورود معتبر (POI / FVG / OB) با فاصله استاندارد پیدا نشد.")
                continue

            # ---- location: the POI must sit in the origin half of the impulse ----
            # The dealing range is measured from the swept extreme (origin of the
            # move) to the current impulse extreme, which is exactly how SMC
            # discount / premium is defined for a post-sweep continuation leg.
            impulse_span = max(abs(arm_struct - arm_extreme), pip_size)
            min_risk, max_risk = pol.stop_bounds(atr, pip_size)

            poi = None
            entry = 0.0
            sl = 0.0
            risk_d = 0.0
            retrace_frac = 0.0
            last_reject = "pd_zone"

            for cand in candidates:
                if cand.quality < pol.min_zone_quality:
                    last_reject = "poi_quality"
                    continue
                cand_entry = (cand.top + cand.bot) / 2.0
                if candidate_dir == 1:
                    cand_retr = (arm_struct - cand_entry) / impulse_span
                else:
                    cand_retr = (cand_entry - arm_struct) / impulse_span
                if not (0.05 <= cand_retr <= 0.95):
                    last_reject = "pd_zone"
                    continue

                # Stop: beyond the swept extreme AND beyond the zone edge, plus
                # an ATR buffer. Using max()/min() guarantees the stop is never
                # closer than the real invalidation point of the structure.
                if candidate_dir == 1:
                    structural = min(arm_price, cand.bot) - pol.sl_buf_atr * atr
                    cand_raw_risk = cand_entry - structural
                else:
                    structural = max(arm_price, cand.top) + pol.sl_buf_atr * atr
                    cand_raw_risk = structural - cand_entry

                if cand_raw_risk <= 0:
                    last_reject = "stop_too_tight"
                    continue
                if cand_raw_risk > max_risk:
                    last_reject = "stop_too_wide"
                    continue

                poi = cand
                entry = cand_entry
                retrace_frac = cand_retr
                risk_d = min(max(cand_raw_risk, min_risk), max_risk)
                break

            if poi is None:
                if last_reject == "poi_quality":
                    reject("poi_quality", "کیفیت زون ورود کمتر از حداقل مجاز است.")
                elif last_reject == "stop_too_wide":
                    reject("stop_too_wide", "حد ضرر ساختاری همه زون‌های کاندید بیش از حد گشاد است.")
                elif last_reject == "stop_too_tight":
                    reject("stop_too_tight", "ورود بالاتر/پایین‌تر از ساختار است؛ ستاپ منقضی محسوب شد.")
                else:
                    reject("pd_zone", "هیچ زون ورودی در ناحیه اصلاحی درست موج قرار ندارد.")
                continue

            in_correct_zone = True
            if candidate_dir == 1:
                sl = entry - risk_d
            else:
                sl = entry + risk_d
            if candidate_dir == 1:
                sl = entry - risk_d
            else:
                sl = entry + risk_d

            # ---- targets (R multiples, optionally tightened to real liquidity) ----
            r1, r2, r3 = pol.tp1_rr, pol.tp2_rr, pol.tp3_rr
            sign = 1 if candidate_dir == 1 else -1

            # TP1 may be pulled in front of a liquidity pool, but never below the
            # policy minimum R:R (a target that is too close destroys expectancy).
            lq1 = liq_target(entry, candidate_dir, risk_d * pol.min_rr_tp1)
            if lq1 is not None:
                lq1_rr = abs(lq1 - entry) / risk_d
                if pol.min_rr_tp1 <= lq1_rr < r1:
                    r1 = lq1_rr
            # TP2 / TP3 can be extended to a farther pool, but never compressed
            # below the previous target (ordering must always hold).
            lq2 = liq_target(entry + sign * risk_d * r1, candidate_dir, risk_d * 0.5)
            if lq2 is not None:
                lq2_rr = abs(lq2 - entry) / risk_d
                if lq2_rr > r2:
                    r2 = lq2_rr
            lq3 = liq_target(entry + sign * risk_d * r2, candidate_dir, risk_d * 0.5)
            if lq3 is not None:
                lq3_rr = abs(lq3 - entry) / risk_d
                if lq3_rr > r3:
                    r3 = lq3_rr

            # Hard invariants: steeply increasing ladder with real separation
            r2 = max(r2, r1 + 0.5)
            r3 = max(r3, r2 + 0.5)
            t1 = entry + sign * risk_d * r1
            t2 = entry + sign * risk_d * r2
            t3 = entry + sign * risk_d * r3

            rr1_actual, rr2_actual, rr3_actual = r1, r2, r3
            if rr1_actual < pol.min_rr_tp1:
                reject("rr", f"نسبت R:R تا تارگت اول کمتر از {pol.min_rr_tp1:.1f} است.")
                continue
            if pol.require_liquidity_room and (lq2 is None and lq3 is None):
                reject("no_room", "هیچ نقدینگی‌ای جلوی مسیر سود وجود ندارد (ریسک گیر افتادن در رنج).")
                continue

            # ---- confluence score (hub3 formula) ----
            score = 4.0
            score += 2.0 if htf_bias == candidate_dir else 0.0
            score += poi.quality
            score += 1.0 if (in_session or not pol.require_session) else 0.0
            score += 1.0  # confirmed CHoCH
            score += 0.5 if arm_eq else 0.0
            score = min(10.0, round(score, 2))
            if score < pol.min_score:
                reject("score", f"امتیاز کانفلوئنس ({score:.1f}/10) کمتر از حداقل سخت‌گیرانه ({pol.min_score:.1f}) است.")
                continue

            mod_name = (
                "SCOB" if poi.poi_type == 3
                else "FLIP" if poi.poi_type == 4
                else "IFC" if poi.poi_type == 5
                else "RETRACE" if poi.poi_type == 6
                else "SWEEP" if arm_swept
                else "CHoCH"
            )
            dir_str = "LONG" if candidate_dir == 1 else "SHORT"
            lots = _compute_lot_size(symbol, entry, sl, params.risk_pct, params.account_equity_ref)
            risk_pips = round(float(risk_d) / float(pip_size), 1)
            early_be_px = entry + pol.early_be_fraction * (t1 - entry)
            sl_anchor = "4H POI / Swing" if timeframe == "4H" else "Sweep / POI"

            checklist = [
                {"key": "bias", "label_fa": "هم‌جهت با بایاس HTF", "passed": True},
                {"key": "sweep", "label_fa": "سوییپ نقدینگی قبل از ورود", "passed": bool(arm_swept)},
                {"key": "choch", "label_fa": "تأیید CHoCH با بدنه قوی", "passed": True},
                {"key": "poi", "label_fa": f"ناحیه ورود باکیفیت ({mod_name})", "passed": bool(poi.quality >= pol.min_zone_quality)},
                {"key": "pd_loc", "label_fa": "موقعیت درست پریمیوم/دیسکانت", "passed": bool(in_correct_zone)},
                {"key": "session", "label_fa": f"سشن فعال ({ses_name})", "passed": bool(in_session or not pol.require_session)},
                {"key": "idm", "label_fa": "برداشته شدن اینداسمنت (IDM)", "passed": bool(idm_done)},
                {"key": "adx_regime", "label_fa": f"عدم رنج بازار (ADX={adx:.1f})", "passed": bool(adx >= pol.min_adx)},
                {"key": "di", "label_fa": f"هم‌سویی DI غالب ({pdi:.0f}/{mdi:.0f})", "passed": bool((pdi > mdi) == (candidate_dir == 1))},
                {"key": "rr_check", "label_fa": f"نسبت پاداش/ریسک TP1 ({rr1_actual:.1f}R)", "passed": bool(rr1_actual >= pol.min_rr_tp1)},
            ]

            rationale = (
                f"ستاپ {dir_str} با ماژول {mod_name} روی {meta['display']} ({tf_meta['label_fa']}): "
                f"پس از سوییپ نقدینگی و تأیید شکست ساختار (CHoCH) هم‌راستا با بایاس تایم‌فریم بالاتر، "
                f"سفارش لیمیت روی میانه POI ثبت شد. امتیاز کانفلوئنس {score:.1f}/10 (گرید {_score_to_grade(score)})، "
                f"ADX={adx:.1f}، DI+={pdi:.0f}/DI-={mdi:.0f}. "
                f"ریسک ساختاری {risk_d / atr:.1f}×ATR ({risk_pips:.0f} پیپ). "
                f"مدیریت: در TP1 ({pol.tp1_rr:.1f}R) {pol.tp1_exit_pct:.0f}٪ خروج و انتقال SL به سر‌به‌سر، "
                f"در TP2 ({pol.tp2_rr:.1f}R) {pol.tp2_exit_pct:.0f}٪ خروج و انتقال SL به TP1، "
                f"و {pol.tp3_exit_pct:.0f}٪ تا TP3 ({pol.tp3_rr:.1f}R). "
                f"ریسک‌فری خودکار در {pol.early_be_fraction * 100:.0f}٪ مسیر تا TP1."
            )

            sig = TradeSetupSignal(
                bar_idx=int(i),
                timestamp=c.timestamp,
                symbol=symbol,
                timeframe=timeframe,
                risk_tier=risk_tier,
                direction=dir_str,
                entry_module=mod_name,
                entry_price=round(float(entry), digits),
                sl=round(float(sl), digits),
                tp1=round(float(t1), digits),
                tp2=round(float(t2), digits),
                tp3=round(float(t3), digits),
                tp1_exit_pct=float(pol.tp1_exit_pct),
                tp2_exit_pct=float(pol.tp2_exit_pct),
                tp3_exit_pct=float(pol.tp3_exit_pct),
                confluence_score=round(float(score), 2),
                grade=_score_to_grade(float(score)),
                htf_bias="BULLISH" if htf_bias == 1 else "BEARISH" if htf_bias == -1 else "NEUTRAL",
                session_name=ses_name,
                position_size_lots=round(float(lots), 2),
                checklist=checklist,
                rationale_fa=rationale,
                bars_valid=int(pol.max_bars_pending),
                risk_atr=round(float(risk_d) / float(atr), 2),
                risk_pips=risk_pips,
                adx_value=round(float(adx), 1),
                atr_value=round(float(atr), digits),
                early_be_price=round(float(early_be_px), digits),
                pending_expiry_hours=int(pol.pending_expiry_hours),
            )
            signals.append(sig)
            last_signal_bar = i
            arm_dir = 0
            arm_swept = False
            idm_done = False
            last_why_fa = f"ستاپ معتبر {dir_str} تأیید شد (امتیاز {score:.1f}/10)."

        # Market-structure trigger: once a *confirmed* minor swing prints after the
        # sweep, the CHoCH level moves to that swing (classic MSS definition).
        if arm_dir == 1 and minor_ph_bar > max(arm_bar, arm_struct_bar):
            arm_struct = minor_ph
            arm_struct_bar = minor_ph_bar
        elif arm_dir == -1 and minor_pl_bar > max(arm_bar, arm_struct_bar):
            arm_struct = minor_pl
            arm_struct_bar = minor_pl_bar

        # Do not keep an arm alive whose trigger is now too far away to chase
        if arm_dir == 1 and arm_struct - cl > 2.5 * atr:
            arm_dir = 0
            arm_swept = False
        if arm_dir == -1 and cl - arm_struct > 2.5 * atr:
            arm_dir = 0
            arm_swept = False

    # ------------------- live snapshot -------------------
    latest_ses, _, _, _ = classify_session_ny(candles[-1].timestamp)
    final_bias_int = htf1_bias_global if htf1_bias_global != 0 else (
        1 if closes[-1] > ema_htf_proxy[-1] else -1
    )
    final_bias_txt = "BULLISH" if final_bias_int == 1 else "BEARISH" if final_bias_int == -1 else "NEUTRAL"

    latest_sig = signals[-1] if (signals and (n - 1 - signals[-1].bar_idx) <= 3) else None
    if latest_sig is not None:
        state_str = "SETUP_READY"
        readiness = 100
    elif arm_dir != 0:
        state_str = "ARMED"
        readiness = 70
    else:
        state_str = "FLAT"
        readiness = 35 if adx_arr[-1] >= pol.min_adx else 15

    return EngineEvaluation(
        symbol=symbol,
        timeframe=timeframe,
        risk_tier=risk_tier,
        state=state_str,
        htf_bias=final_bias_txt,
        session_name=latest_ses,
        adx_value=round(float(adx_arr[-1]), 1),
        atr_value=round(float(atr_arr[-1]), digits),
        readiness_pct=readiness,
        why_no_trade_fa=last_why_fa,
        active_poi_count=len(poi_zones),
        active_liq_count=len([lv for lv in liq_levels if not lv.used]),
        latest_signal=latest_sig,
        historical_signals=signals,
        rejection_counts=rejection_counts,
        policy=pol,
        di_plus=round(float(pdi_arr[-1]), 1),
        di_minus=round(float(mdi_arr[-1]), 1),
    )
