"""
NEXVORA — Trading Policy (single source of truth)
=================================================

This module encodes the *hard* risk / quality policy that sits on top of the
Trading Hub 3.0 (`hub3.txt`) execution core.

Design rules (derived from hub3.txt + the user's requirements):

1. The hub3 core states are never skipped:
   ``sweep -> CHoCH -> POI zone -> limit entry``.
   If any link of that chain is missing there is no signal.

2. Every timeframe gets its own *risk profile*:

   ======  ==================  ==================================================
   TF      Risk tier           Intent
   ======  ==================  ==================================================
   4H      SAFE                Few, high-quality swing trades. Structural stops,
                               wide targets, session filter off.
   15m     MEDIUM_RISK         Intraday, only inside London / New York kill zones.
   5m      HIGH_RISK           Strictest filters, tighter targets, fastest expiry.
   ======  ==================  ==================================================

3. Stops are always *structural* (beyond the swept swing / POI edge + ATR buffer)
   and clamped into ``[min_stop_atr, max_stop_atr]`` so that:
     - the stop is never so tight that normal volatility hunts it (that is what
       turns good setups into losses), and
     - the stop is never so wide that one loss destroys several wins.

4. Targets are expressed in R multiples of the *structural* risk distance, then
   optionally snapped to real liquidity. TP1 is deliberately reachable so the
   trade gets de-risked early (TP1 -> remaining position at break-even).

All numbers here are policy constants, not per-symbol magic. They are covered by
``backend/tests/test_policy_and_engine.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, List, Tuple

# Bump this when the numeric policy changes so that backtest results stored in the
# database can be tied to the exact rule-set that produced them.
TRADING_POLICY_VERSION = "nexvora-strict-2026.11.1"


@dataclass(frozen=True)
class TimeframePolicy:
    timeframe: str
    risk_tier: str

    # --- stop loss construction -------------------------------------------------
    sl_buf_atr: float          # buffer beyond the structural level (ATR multiple)
    min_stop_atr: float        # floor for the total risk distance in ATR
    min_stop_pips: float       # floor in pips (guards against tick-sized noise)
    max_stop_atr: float        # reject setups whose stop is absurdly wide

    # --- targets ----------------------------------------------------------------
    tp1_rr: float
    tp2_rr: float
    tp3_rr: float
    tp1_exit_pct: float
    tp2_exit_pct: float
    early_be_fraction: float   # move SL to BE once price covers this share of entry->TP1

    # --- quality gates ----------------------------------------------------------
    min_score: float
    min_adx: float
    min_rr_tp1: float
    require_session: bool
    require_idm: bool
    require_dual_htf: bool
    require_di_alignment: bool
    require_liquidity_room: bool
    min_zone_quality: float
    max_poi_age_bars: int
    pullback_frac: float       # depth of the limit entry inside the impulse (0..1)

    # --- timing / lifecycle -----------------------------------------------------
    arm_valid_bars: int
    cooldown_bars: int
    max_bars_pending: int
    pending_expiry_hours: int

    @property
    def tp3_exit_pct(self) -> float:
        return round(max(0.0, 100.0 - self.tp1_exit_pct - self.tp2_exit_pct), 1)

    def stop_bounds(self, atr: float, pip_size: float) -> Tuple[float, float]:
        """Return (min_risk_distance, max_risk_distance) for this timeframe."""
        floor = max(self.min_stop_atr * atr, self.min_stop_pips * pip_size)
        ceiling = max(self.max_stop_atr * atr, floor * 1.25)
        return floor, ceiling


# ---------------------------------------------------------------------------
# The three supported risk profiles
# ---------------------------------------------------------------------------
TF_POLICIES: Dict[str, TimeframePolicy] = {
    "4H": TimeframePolicy(
        timeframe="4H",
        risk_tier="SAFE",
        sl_buf_atr=0.30,
        min_stop_atr=1.20,
        min_stop_pips=8.0,
        max_stop_atr=4.00,
        tp1_rr=1.3,
        tp2_rr=2.4,
        tp3_rr=3.6,
        tp1_exit_pct=50.0,
        tp2_exit_pct=30.0,
        early_be_fraction=0.70,
        min_score=8.0,
        min_adx=22.0,
        min_rr_tp1=0.95,
        require_session=False,
        require_idm=True,
        require_dual_htf=True,
        require_di_alignment=True,
        require_liquidity_room=True,
        min_zone_quality=1.00,
        max_poi_age_bars=30,
        pullback_frac=0.55,
        arm_valid_bars=20,
        cooldown_bars=6,
        max_bars_pending=30,
        pending_expiry_hours=96,
    ),
    "15m": TimeframePolicy(
        timeframe="15m",
        risk_tier="MEDIUM_RISK",
        sl_buf_atr=0.30,
        min_stop_atr=1.20,
        min_stop_pips=5.0,
        max_stop_atr=3.50,
        tp1_rr=1.2,
        tp2_rr=2.2,
        tp3_rr=3.4,
        tp1_exit_pct=50.0,
        tp2_exit_pct=30.0,
        early_be_fraction=0.70,
        min_score=8.5,
        min_adx=25.0,
        min_rr_tp1=0.95,
        require_session=True,
        require_idm=True,
        require_dual_htf=True,
        require_di_alignment=True,
        require_liquidity_room=True,
        min_zone_quality=1.00,
        max_poi_age_bars=24,
        pullback_frac=0.50,
        arm_valid_bars=20,
        cooldown_bars=10,
        max_bars_pending=40,
        pending_expiry_hours=24,
    ),
    "5m": TimeframePolicy(
        timeframe="5m",
        risk_tier="HIGH_RISK",
        sl_buf_atr=0.35,
        min_stop_atr=1.30,
        min_stop_pips=4.0,
        max_stop_atr=3.00,
        tp1_rr=1.1,
        tp2_rr=2.0,
        tp3_rr=3.0,
        tp1_exit_pct=50.0,
        tp2_exit_pct=30.0,
        early_be_fraction=0.70,
        min_score=9.0,
        min_adx=28.0,
        min_rr_tp1=0.90,
        require_session=True,
        require_idm=True,
        require_dual_htf=True,
        require_di_alignment=True,
        require_liquidity_room=True,
        min_zone_quality=1.00,
        max_poi_age_bars=18,
        pullback_frac=0.50,
        arm_valid_bars=18,
        cooldown_bars=12,
        max_bars_pending=24,
        pending_expiry_hours=6,
    ),
}

# Global (non time-frame specific) portfolio guards
MAX_CONCURRENT_TRADES: int = 4            # hard cap across the whole portfolio
MAX_CONCURRENT_PER_SYMBOL: int = 1        # pyramiding disabled (hub3: pyramiding = 0)
CONSECUTIVE_LOSS_PAUSE: int = 2           # after N straight losses on a cell ...
CONSECUTIVE_LOSS_PAUSE_HOURS: int = 24    # ... pause that cell for this long
NEWS_BLACKOUT_MINUTES: int = 30           # no fresh entries this close to high-impact news


def get_policy(timeframe: str) -> TimeframePolicy:
    try:
        return TF_POLICIES[timeframe]
    except KeyError as exc:  # pragma: no cover - guarded by config validation
        raise ValueError(f"No trading policy for timeframe {timeframe!r}") from exc


def policy_with_overrides(
    timeframe: str,
    *,
    tp1_rr: float | None = None,
    tp2_rr: float | None = None,
    tp3_rr: float | None = None,
    tp1_exit_pct: float | None = None,
    tp2_exit_pct: float | None = None,
    min_score: float | None = None,
    min_adx: float | None = None,
    require_session: bool | None = None,
) -> TimeframePolicy:
    """Apply the admin-editable EngineConfig values on top of the base policy."""
    base = get_policy(timeframe)
    changes: dict = {}
    if tp1_rr is not None:
        changes["tp1_rr"] = float(tp1_rr)
    if tp2_rr is not None:
        changes["tp2_rr"] = float(tp2_rr)
    if tp3_rr is not None:
        changes["tp3_rr"] = float(tp3_rr)
    if tp1_exit_pct is not None:
        changes["tp1_exit_pct"] = float(tp1_exit_pct)
    if tp2_exit_pct is not None:
        changes["tp2_exit_pct"] = float(tp2_exit_pct)
    if min_score is not None:
        changes["min_score"] = float(min_score)
    if min_adx is not None:
        changes["min_adx"] = float(min_adx)
    if require_session is not None:
        changes["require_session"] = bool(require_session)
    if not changes:
        return base

    merged = replace(base, **changes)

    # Guard rails: a stored configuration may never push the engine into a
    # configuration that structurally destroys expectancy.
    if merged.tp1_exit_pct + merged.tp2_exit_pct > 95.0:
        return replace(base, **(changes | {"tp1_exit_pct": base.tp1_exit_pct, "tp2_exit_pct": base.tp2_exit_pct}))
    if merged.tp1_exit_pct <= 0:
        merged = replace(merged, tp1_exit_pct=base.tp1_exit_pct)

    # TP1 can never be tighter than the timeframe's minimum acceptable R:R.
    tp1 = max(merged.tp1_rr, merged.min_rr_tp1 + 0.05)
    tp2 = max(merged.tp2_rr, tp1 + 0.5)
    tp3 = max(merged.tp3_rr, tp2 + 0.5)
    return replace(merged, tp1_rr=round(tp1, 2), tp2_rr=round(tp2, 2), tp3_rr=round(tp3, 2))


def all_policies() -> List[TimeframePolicy]:
    return [TF_POLICIES["4H"], TF_POLICIES["15m"], TF_POLICIES["5m"]]
