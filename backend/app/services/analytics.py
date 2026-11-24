from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import SignalTrade, utcnow


def compute_performance_analytics(
    db: Session,
    days: Optional[int] = None,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    include_be_in_winrate_denominator: bool = True,
) -> dict:
    """
    Documented, auditable KPI reconciliation formulas (per MASTER_IMPLEMENTATION_PROMPT.md §4.5):
    - Eligible Closed Trades = trades with outcome in (WIN, LOSS, BE); OPEN and CANCELLED are excluded.
    - Win Rate = Winning Trades / Eligible Closed Trades * 100 (break-even explicitly tracked & documented).
    - Target Hits (TP1/TP2/TP3) are counted separately and NEVER confused with Winning Trades.
    - Profit Factor = Gross Profit ($) / |Gross Loss ($)|.
    - Expectancy (R) = Mean realized_r across eligible closed trades.
    - Max Drawdown (%) computed on cumulative realized equity curve from $10,000 base.
    """
    q = db.query(SignalTrade)
    range_label = "کل دوره"
    if days is not None and days > 0:
        cutoff = utcnow() - timedelta(days=days)
        q = q.filter(SignalTrade.created_at >= cutoff)
        range_label = f"{days} روز اخیر"
    if symbol:
        q = q.filter(SignalTrade.symbol == symbol)
    if timeframe:
        q = q.filter(SignalTrade.timeframe == timeframe)

    all_trades: List[SignalTrade] = q.order_by(SignalTrade.created_at.asc()).all()

    active_trades = [t for t in all_trades if t.status in ("PENDING_LIMIT", "ACTIVE", "TP1_HIT", "TP2_HIT")]
    closed_eligible = [t for t in all_trades if t.outcome in ("WIN", "LOSS", "BE")]
    cancelled_trades = [t for t in all_trades if t.outcome == "CANCELLED"]

    wins = [t for t in closed_eligible if t.outcome == "WIN"]
    losses = [t for t in closed_eligible if t.outcome == "LOSS"]
    bes = [t for t in closed_eligible if t.outcome == "BE"]

    denom = len(closed_eligible) if include_be_in_winrate_denominator else (len(wins) + len(losses))
    win_rate = round((len(wins) / denom) * 100.0, 2) if denom > 0 else 0.0
    loss_rate = round((len(losses) / denom) * 100.0, 2) if denom > 0 else 0.0
    be_rate = round((len(bes) / len(closed_eligible)) * 100.0, 2) if closed_eligible else 0.0

    gross_profit = round(sum((t.realized_pnl_usd - t.fees_usd) for t in closed_eligible if (t.realized_pnl_usd - t.fees_usd) > 0), 2)
    gross_loss = round(abs(sum((t.realized_pnl_usd - t.fees_usd) for t in closed_eligible if (t.realized_pnl_usd - t.fees_usd) < 0)), 2)
    net_profit = round(gross_profit - gross_loss, 2)
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (9.99 if gross_profit > 0 else 0.0)

    avg_win_usd = round(sum(t.realized_pnl_usd for t in wins) / len(wins), 2) if wins else 0.0
    avg_loss_usd = round(sum(t.realized_pnl_usd for t in losses) / len(losses), 2) if losses else 0.0
    avg_r = round(sum(t.realized_r for t in closed_eligible) / len(closed_eligible), 3) if closed_eligible else 0.0
    expectancy_r = avg_r

    # Separate Target Hits counters (NEVER conflated with winning trade count)
    tp1_hits = sum(1 for t in all_trades if t.tp1_hit)
    tp2_hits = sum(1 for t in all_trades if t.tp2_hit)
    tp3_hits = sum(1 for t in all_trades if t.tp3_hit)
    sl_hits = len(losses)

    # Equity curve & Max Drawdown
    base_eq = 10000.0
    eq = base_eq
    peak = base_eq
    max_dd_pct = 0.0
    equity_curve: List[dict] = []
    for t in closed_eligible:
        net_t = t.realized_pnl_usd - t.fees_usd
        eq = round(eq + net_t, 2)
        if eq > peak:
            peak = eq
        dd = ((peak - eq) / peak * 100.0) if peak > 0 else 0.0
        max_dd_pct = max(max_dd_pct, dd)
        ts = (t.closed_at or t.updated_at or t.created_at).isoformat()
        equity_curve.append({
            "timestamp": ts,
            "trade_code": t.trade_code,
            "symbol": t.symbol,
            "equity": eq,
            "pnl_usd": round(net_t, 2),
            "r": t.realized_r,
        })

    def _group_breakdown(key_fn) -> List[dict]:
        buckets: Dict[str, List[SignalTrade]] = defaultdict(list)
        for t in closed_eligible:
            buckets[key_fn(t)].append(t)
        rows = []
        for k, items in buckets.items():
            w = sum(1 for x in items if x.outcome == "WIN")
            l = sum(1 for x in items if x.outcome == "LOSS")
            b = sum(1 for x in items if x.outcome == "BE")
            gp = sum(x.realized_pnl_usd for x in items if x.realized_pnl_usd > 0)
            gl = abs(sum(x.realized_pnl_usd for x in items if x.realized_pnl_usd < 0))
            rows.append({
                "key": k,
                "trades": len(items),
                "wins": w,
                "losses": l,
                "breakeven": b,
                "win_rate": round(w / len(items) * 100.0, 2) if items else 0.0,
                "net_pnl_usd": round(sum(x.realized_pnl_usd - x.fees_usd for x in items), 2),
                "avg_r": round(sum(x.realized_r for x in items) / len(items), 3) if items else 0.0,
                "profit_factor": round(gp / gl, 2) if gl > 0 else (9.99 if gp > 0 else 0.0),
            })
        return sorted(rows, key=lambda r: r["net_pnl_usd"], reverse=True)

    return {
        "time_range_label": range_label,
        "calculation_basis_fa": (
            "فرمول وین‌ریت: تعداد معاملات برنده تقسیم بر معاملات بسته‌شده معتبر (برنده + ضرر + سر‌به‌سر) × ۱۰۰. "
            "معاملات باز و سفارش‌های لغو/منقضی‌شده از مخرج کسر حذف شده‌اند."
        ),
        "kpis": {
            "total_trades": len(closed_eligible),
            "total_signals_all": len(all_trades),
            "active_trades": len(active_trades),
            "cancelled_or_expired": len(cancelled_trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "breakeven_trades": len(bes),
            "win_rate": win_rate,
            "loss_rate": loss_rate,
            "breakeven_rate": be_rate,
            "gross_profit_usd": gross_profit,
            "gross_loss_usd": gross_loss,
            "net_profit_usd": net_profit,
            "return_pct": round((net_profit / base_eq) * 100.0, 2),
            "profit_factor": profit_factor,
            "avg_win_usd": avg_win_usd,
            "avg_loss_usd": avg_loss_usd,
            "expectancy_r": expectancy_r,
            "avg_r": avg_r,
            "max_drawdown_pct": round(max_dd_pct, 2),
            "tp1_hits": tp1_hits,
            "tp2_hits": tp2_hits,
            "tp3_hits": tp3_hits,
            "target_hits_total": tp1_hits + tp2_hits + tp3_hits,
            "sl_hits": sl_hits,
        },
        "equity_curve": equity_curve,
        "by_symbol": _group_breakdown(lambda t: t.symbol),
        "by_timeframe": _group_breakdown(lambda t: f"{t.timeframe} ({t.risk_tier})"),
        "by_module": _group_breakdown(lambda t: t.entry_module),
        "by_session": _group_breakdown(lambda t: t.session_name),
    }
