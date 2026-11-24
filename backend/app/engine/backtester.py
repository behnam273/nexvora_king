from __future__ import annotations

from dataclasses import dataclass, replace
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import ALLOWED_SYMBOLS, ALLOWED_TIMEFRAMES, SYMBOL_META, TIMEFRAME_META
from app.engine.market_data import Candle, get_market_series
from app.engine.policy import TRADING_POLICY_VERSION, get_policy, policy_with_overrides
from app.engine.trading_hub3 import HighAccuracyParams, TradeSetupSignal, run_trading_hub3_engine
from app.models import BacktestQualification, EngineConfig, utcnow


@dataclass
class SimulatedTradeResult:
    signal: TradeSetupSignal
    filled: bool
    outcome: str      # WIN | LOSS | BE | EXPIRED
    realized_r: float
    tp1_hit: bool
    tp2_hit: bool
    tp3_hit: bool
    exit_bar_idx: int
    max_favorable_r: float = 0.0
    max_adverse_r: float = 0.0
    bars_held: int = 0


def simulate_signal_lifecycle(
    sig: TradeSetupSignal,
    candles: List[Candle],
    params: Optional[HighAccuracyParams] = None,
    commission_r: float = 0.04,
    max_hold_bars: Optional[int] = None,
) -> SimulatedTradeResult:
    """
    Deterministic bar-by-bar execution simulator that follows the *same* rules as
    the live position tracker:

    * The limit order is only filled on a **later** bar (no same-bar look-ahead),
      and only when price actually trades through the entry.
    * The order dies if the candle *closes* beyond the stop before being filled,
      or if ``bars_valid`` bars pass without a fill.
    * Once filled, the stop is checked **before** the targets on every bar
      (conservative intra-bar assumption) so the backtest can never look better
      than reality.
    * TP1 -> close ``tp1_exit_pct`` and move the stop to break-even.
      TP2 -> close ``tp2_exit_pct`` and move the stop to TP1.
      TP3 -> close the remainder.
    * An additional early break-even move happens once price covers
      ``early_be_fraction`` of the way to TP1 (same as the live tracker).
    """
    pol = params.policy if params is not None else get_policy(sig.timeframe)
    n = len(candles)
    is_long = sig.direction == "LONG"
    risk_d = abs(sig.entry_price - sig.sl)
    if risk_d <= 0:
        return SimulatedTradeResult(sig, False, "EXPIRED", 0.0, False, False, False, sig.bar_idx)

    filled = False
    fill_bar = -1
    wait_bars = sig.bars_valid if sig.bars_valid else pol.max_bars_pending
    max_wait_bar = min(n - 1, sig.bar_idx + wait_bars)

    for b in range(sig.bar_idx + 1, max_wait_bar + 1):
        c = candles[b]
        # Order is invalidated when the bar *closes* through the invalidation level
        if is_long and c.close < sig.sl:
            return SimulatedTradeResult(sig, False, "EXPIRED", 0.0, False, False, False, b)
        if (not is_long) and c.close > sig.sl:
            return SimulatedTradeResult(sig, False, "EXPIRED", 0.0, False, False, False, b)
        if c.low <= sig.entry_price <= c.high:
            filled = True
            fill_bar = b
            break

    if not filled:
        return SimulatedTradeResult(sig, False, "EXPIRED", 0.0, False, False, False, max_wait_bar)

    entry = sig.entry_price
    cur_sl = sig.sl
    rem = 1.0
    p1 = sig.tp1_exit_pct / 100.0
    p2 = sig.tp2_exit_pct / 100.0
    realized_r = 0.0
    tp1_hit = tp2_hit = tp3_hit = False
    early_be_done = False
    mfe = 0.0
    mae = 0.0

    rr1 = abs(sig.tp1 - entry) / risk_d
    rr2 = abs(sig.tp2 - entry) / risk_d
    rr3 = abs(sig.tp3 - entry) / risk_d
    early_be_px = entry + pol.early_be_fraction * (sig.tp1 - entry)

    hold_limit = n if max_hold_bars is None else min(n, fill_bar + max_hold_bars + 1)
    last_bar = fill_bar
    for b in range(fill_bar + 1, hold_limit):
        c = candles[b]
        last_bar = b
        fav = ((c.high - entry) if is_long else (entry - c.low)) / risk_d
        adv = ((entry - c.low) if is_long else (c.high - entry)) / risk_d
        mfe = max(mfe, fav)
        mae = max(mae, adv)

        # 1) stop first (worst-case ordering)
        sl_hit = (c.low <= cur_sl) if is_long else (c.high >= cur_sl)
        if sl_hit:
            sl_r = ((cur_sl - entry) / risk_d) if is_long else ((entry - cur_sl) / risk_d)
            realized_r += rem * sl_r
            realized_r -= commission_r
            outcome = "WIN" if realized_r > 0.05 else ("BE" if abs(realized_r) <= 0.05 else "LOSS")
            return SimulatedTradeResult(
                sig, True, outcome, round(realized_r, 3), tp1_hit, tp2_hit, tp3_hit, b,
                round(mfe, 2), round(mae, 2), b - fill_bar,
            )

        # 2) early break-even (only before TP1)
        if (not tp1_hit) and (not early_be_done):
            reached = (c.high >= early_be_px) if is_long else (c.low <= early_be_px)
            if reached:
                early_be_done = True
                cur_sl = entry

        # 3) TP1
        if (not tp1_hit) and ((c.high >= sig.tp1) if is_long else (c.low <= sig.tp1)):
            tp1_hit = True
            take = min(rem, p1)
            realized_r += take * rr1
            rem -= take
            cur_sl = entry  # break-even
            if rem <= 1e-6:
                return SimulatedTradeResult(
                    sig, True, "WIN", round(realized_r - commission_r, 3), True, False, False, b,
                    round(mfe, 2), round(mae, 2), b - fill_bar,
                )

        # 4) TP2
        if tp1_hit and (not tp2_hit) and ((c.high >= sig.tp2) if is_long else (c.low <= sig.tp2)):
            tp2_hit = True
            take = min(rem, p2)
            realized_r += take * rr2
            rem -= take
            cur_sl = sig.tp1  # lock TP1
            if rem <= 1e-6:
                return SimulatedTradeResult(
                    sig, True, "WIN", round(realized_r - commission_r, 3), True, True, False, b,
                    round(mfe, 2), round(mae, 2), b - fill_bar,
                )

        # 5) TP3
        if tp2_hit and (not tp3_hit) and ((c.high >= sig.tp3) if is_long else (c.low <= sig.tp3)):
            tp3_hit = True
            realized_r += rem * rr3
            rem = 0.0
            return SimulatedTradeResult(
                sig, True, "WIN", round(realized_r - commission_r, 3), True, True, True, b,
                round(mfe, 2), round(mae, 2), b - fill_bar,
            )

    # Still open at the end of the data / max-hold window -> mark to market
    last_close = candles[last_bar].close
    mtm_r = ((last_close - entry) / risk_d) if is_long else ((entry - last_close) / risk_d)
    total_r = realized_r + rem * mtm_r - commission_r
    outcome = "WIN" if total_r > 0.05 else ("BE" if abs(total_r) <= 0.05 else "LOSS")
    return SimulatedTradeResult(
        sig, True, outcome, round(total_r, 3), tp1_hit, tp2_hit, tp3_hit, last_bar,
        round(mfe, 2), round(mae, 2), last_bar - fill_bar,
    )


def build_params_for_timeframe(cfg: Optional[EngineConfig], timeframe: str) -> HighAccuracyParams:
    """
    Translate the admin-editable ``EngineConfig`` row into engine parameters for a
    single timeframe. Each timeframe keeps its own risk profile; only the fields
    the admin can actually change are overlaid.
    """
    policy = get_policy(timeframe)
    if cfg is not None:
        try:
            policy = policy_with_overrides(
                timeframe,
                tp1_rr=cfg.tp1_rr,
                tp2_rr=cfg.tp2_rr,
                tp3_rr=cfg.tp3_rr,
                tp1_exit_pct=cfg.tp1_exit_pct,
                tp2_exit_pct=cfg.tp2_exit_pct,
                min_score={
                    "4H": cfg.min_score_4h,
                    "15m": cfg.min_score_15m,
                    "5m": cfg.min_score_5m,
                }.get(timeframe),
                min_adx=cfg.min_adx,
                require_session=cfg.use_session_filter and policy.require_session,
            )
        except ValueError:
            # Invalid admin combination -> fall back to the hardened defaults.
            policy = get_policy(timeframe)
    return HighAccuracyParams(policy=policy, timeframe=timeframe)


def config_to_params(cfg: Optional[EngineConfig], timeframe: str = "15m") -> HighAccuracyParams:
    """Backwards-compatible helper (defaults to the 15m profile)."""
    return build_params_for_timeframe(cfg, timeframe)


def evaluate_pair_backtest(
    symbol: str,
    timeframe: str,
    db: Session,
    cfg: Optional[EngineConfig] = None,
) -> Tuple[BacktestQualification, List[SimulatedTradeResult]]:
    params = build_params_for_timeframe(cfg, timeframe)
    pol = params.policy
    tf_meta = TIMEFRAME_META[timeframe]
    min_wr = cfg.min_backtest_winrate if cfg else 70.0
    min_pf = cfg.min_backtest_pf if cfg else 1.5
    min_trades = cfg.min_backtest_trades if cfg else 3

    # Deep sample: a qualification is only meaningful on a long history, so the
    # backtest uses the largest window providers allow (900 bars).
    series = get_market_series(symbol, timeframe, limit=900, db=db)
    htf1 = get_market_series(symbol, tf_meta["htf_primary"], limit=400, db=db)
    htf2 = (
        get_market_series(symbol, tf_meta["htf_secondary"], limit=400, db=db)
        if tf_meta["htf_secondary"] != tf_meta["htf_primary"]
        else htf1
    )

    evaluation = run_trading_hub3_engine(
        symbol=symbol,
        timeframe=timeframe,
        candles=series.candles,
        params=params,
        htf1_candles=htf1.candles,
        htf2_candles=htf2.candles,
    )

    # Simulate non-overlapping trades (pyramiding = 0, matching hub3.txt)
    results: List[SimulatedTradeResult] = []
    busy_until = -1
    for sig in evaluation.historical_signals:
        if sig.bar_idx <= busy_until:
            continue
        sim = simulate_signal_lifecycle(
            sig, series.candles, params=params, commission_r=params.commission_r
        )
        if sim.filled:
            results.append(sim)
            busy_until = sim.exit_bar_idx

    total = len(results)
    wins = sum(1 for r in results if r.outcome == "WIN")
    losses = sum(1 for r in results if r.outcome == "LOSS")
    bes = sum(1 for r in results if r.outcome == "BE")

    # Documented Win Rate formula: Winning Trades / Eligible Closed Trades * 100
    win_rate = round((wins / total) * 100.0, 2) if total > 0 else 0.0
    gross_profit_r = sum(r.realized_r for r in results if r.realized_r > 0)
    gross_loss_r = abs(sum(r.realized_r for r in results if r.realized_r < 0))
    if gross_loss_r > 0:
        pf = round(gross_profit_r / gross_loss_r, 2)
    elif gross_profit_r > 0:
        pf = 9.99
    else:
        pf = 0.0

    avg_r = round(sum(r.realized_r for r in results) / total, 3) if total > 0 else 0.0
    expectancy_r = avg_r
    avg_hold_bars = round(sum(r.bars_held for r in results) / total, 1) if total > 0 else 0.0

    # Max drawdown on a 1%-risk-per-trade compounding equity curve
    eq = 100.0
    peak = 100.0
    max_dd = 0.0
    for r in results:
        eq *= (1.0 + (r.realized_r * 0.01))
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100.0 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    # A cell is only publishable with a real edge AND enough trades to trust it.
    eligible = (
        (total >= min_trades)
        and (win_rate >= min_wr)
        and (pf >= min_pf)
        and (max_dd <= 25.0)
        and (avg_r > 0.0)
    )
    if eligible:
        reason_fa = (
            f"تأییدشده برای کانال تلگرام — وین‌ریت {win_rate:.1f}% (≥ {min_wr:.0f}%)، "
            f"Profit Factor {pf:.2f} و حداکثر افت {max_dd:.1f}% روی {total} معامله معتبر "
            f"(پالیسی {TRADING_POLICY_VERSION})."
        )
    elif total < min_trades:
        reason_fa = f"رد موقت: تعداد معاملات بک‌تست کافی نیست ({total} < {min_trades})."
    elif win_rate < min_wr:
        reason_fa = f"رد توسط فیلتر وین‌ریت: {win_rate:.1f}% کمتر از آستانه سخت‌گیرانه {min_wr:.0f}% است."
    elif pf < min_pf:
        reason_fa = f"رد توسط فیلتر Profit Factor: {pf:.2f} کمتر از حداقل {min_pf:.2f} است."
    elif max_dd > 25.0:
        reason_fa = f"رد توسط فیلتر ریسک: حداکثر افت سرمایه {max_dd:.1f}% از سقف ۲۵٪ بیشتر است."
    else:
        reason_fa = f"رد: انتظار ریاضی هر معامله منفی یا صفر است (expectancy {avg_r:+.2f}R)."

    row = (
        db.query(BacktestQualification)
        .filter(BacktestQualification.symbol == symbol, BacktestQualification.timeframe == timeframe)
        .first()
    )
    if not row:
        row = BacktestQualification(symbol=symbol, timeframe=timeframe, risk_tier=tf_meta["risk_tier"])
        db.add(row)

    row.risk_tier = tf_meta["risk_tier"]
    row.eligible_for_telegram = eligible
    row.reason_fa = reason_fa
    row.total_trades = total
    row.winning_trades = wins
    row.losing_trades = losses
    row.breakeven_trades = bes
    row.win_rate = win_rate
    row.profit_factor = pf
    row.expectancy_r = expectancy_r
    row.max_drawdown_pct = round(max_dd, 2)
    row.avg_r = avg_r
    row.avg_hold_bars = avg_hold_bars
    row.window_bars = len(series.candles)
    row.data_source = series.source
    row.is_demo_data = series.is_demo_data
    row.policy_version = TRADING_POLICY_VERSION
    row.evaluated_at = utcnow()
    db.commit()
    db.refresh(row)
    return row, results


def refresh_all_qualifications(db: Session, cfg: Optional[EngineConfig] = None) -> List[BacktestQualification]:
    rows: List[BacktestQualification] = []
    for sym in ALLOWED_SYMBOLS:
        for tf in ALLOWED_TIMEFRAMES:
            q, _ = evaluate_pair_backtest(sym, tf, db, cfg)
            rows.append(q)
    return rows
