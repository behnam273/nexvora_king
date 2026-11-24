from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import ALLOWED_SYMBOLS, SYMBOL_META, TIMEFRAME_META, get_settings
from app.database import get_db
from app.engine.market_data import get_market_series
from app.models import (
    BacktestQualification,
    EconomicEvent,
    NewsItem,
    SignalTrade,
    SourceHealth,
    User,
    utcnow,
)
from app.security import get_current_user
from app.services.analytics import compute_performance_analytics

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def serialize_trade(t: SignalTrade) -> dict:
    return {
        "id": t.id,
        "trade_code": t.trade_code,
        "symbol": t.symbol,
        "display_symbol": SYMBOL_META[t.symbol]["display"],
        "market_class": t.market_class,
        "timeframe": t.timeframe,
        "timeframe_label_fa": TIMEFRAME_META[t.timeframe]["label_fa"],
        "risk_tier": t.risk_tier,
        "direction": t.direction,
        "strategy_name": t.strategy_name,
        "entry_module": t.entry_module,
        "htf_bias": t.htf_bias,
        "session_name": t.session_name,
        "status": t.status,
        "outcome": t.outcome,
        "entry_price": t.entry_price,
        "fill_price": t.fill_price,
        "current_price": t.current_price,
        "initial_sl": t.initial_sl,
        "current_sl": t.current_sl,
        "tp1": t.tp1,
        "tp2": t.tp2,
        "tp3": t.tp3,
        "tp1_exit_pct": t.tp1_exit_pct,
        "tp2_exit_pct": t.tp2_exit_pct,
        "tp3_exit_pct": t.tp3_exit_pct,
        "remaining_pct": t.remaining_pct,
        "tp1_hit": t.tp1_hit,
        "tp2_hit": t.tp2_hit,
        "tp3_hit": t.tp3_hit,
        "risk_pct": t.risk_pct,
        "position_size_lots": t.position_size_lots,
        "confluence_score": t.confluence_score,
        "grade": t.grade,
        "checklist": json.loads(t.checklist_json or "[]"),
        "rationale_fa": t.rationale_fa,
        "realized_r": t.realized_r,
        "floating_r": t.floating_r,
        "realized_pips": t.realized_pips,
        "floating_pips": t.floating_pips,
        "realized_pnl_usd": t.realized_pnl_usd,
        "floating_pnl_usd": t.floating_pnl_usd,
        "fees_usd": t.fees_usd,
        "progress_to_tp1_pct": t.progress_to_tp1_pct,
        "backtest_win_rate_at_entry": t.backtest_win_rate_at_entry,
        "eligible_for_telegram": t.eligible_for_telegram,
        "telegram_message_id": t.telegram_message_id,
        "data_source": t.data_source,
        "is_demo_data": t.is_demo_data,
        "bars_remaining": t.bars_remaining,
        "created_at": t.created_at,
        "opened_at": t.opened_at,
        "closed_at": t.closed_at,
        "updated_at": t.updated_at,
        "events": [
            {
                "id": e.id,
                "trade_id": e.trade_id,
                "event_type": e.event_type,
                "price": e.price,
                "r_value": e.r_value,
                "pips_value": e.pips_value,
                "description_fa": e.description_fa,
                "telegram_reply_id": e.telegram_reply_id,
                "source_timestamp": e.source_timestamp,
                "created_at": e.created_at,
            }
            for e in (t.events or [])
        ],
    }


@router.get("")
def get_dashboard(
    days: Optional[int] = Query(default=None, ge=1, le=365),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    analytics = compute_performance_analytics(db, days=days)
    active_trades = (
        db.query(SignalTrade)
        .filter(SignalTrade.status.in_(["PENDING_LIMIT", "ACTIVE", "TP1_HIT", "TP2_HIT"]))
        .order_by(SignalTrade.updated_at.desc())
        .limit(8)
        .all()
    )
    recent_closed = (
        db.query(SignalTrade)
        .filter(SignalTrade.outcome.in_(["WIN", "LOSS", "BE"]))
        .order_by(SignalTrade.closed_at.desc())
        .limit(6)
        .all()
    )
    top_news = (
        db.query(NewsItem)
        .order_by(NewsItem.published_at.desc())
        .limit(5)
        .all()
    )
    upcoming_events = (
        db.query(EconomicEvent)
        .filter(EconomicEvent.importance == "HIGH")
        .order_by(EconomicEvent.scheduled_at.asc())
        .limit(4)
        .all()
    )
    quals = db.query(BacktestQualification).all()
    health_rows = db.query(SourceHealth).all()

    # Market ticker snapshot for our exact 6 pairs
    market_strip = []
    any_demo = False
    for sym in ALLOWED_SYMBOLS:
        s = get_market_series(sym, "15m", limit=100, db=db)
        if s.is_demo_data:
            any_demo = True
        last_c = s.candles[-1]
        prev_c = s.candles[-24] if len(s.candles) >= 24 else s.candles[0]
        chg_pct = round(((last_c.close - prev_c.close) / prev_c.close) * 100.0, 2) if prev_c.close else 0.0
        market_strip.append({
            "symbol": sym,
            "display": SYMBOL_META[sym]["display"],
            "name_fa": SYMBOL_META[sym]["name_fa"],
            "price": last_c.close,
            "change_pct": chg_pct,
            "digits": SYMBOL_META[sym]["digits"],
            "source": s.source,
            "is_demo_data": s.is_demo_data,
        })

    settings = get_settings()
    return {
        "server_time": utcnow().isoformat(),
        "data_mode": settings.nexvora_data_mode,
        "is_demo_data": any_demo,
        "demo_notice_fa": (
            "حالت بازپخش آفلاین (Demo/Replay): دسترسی مستقیم به سرورهای خارجی در این محیط بسته است؛ "
            "تمام محاسبات Trading Hub 3.0، بک‌تست و پیگیری پوزیشن واقعی هستند اما قیمت‌ها از شبیه‌ساز آفلاین خوانده شده‌اند."
            if any_demo else ""
        ),
        "time_range_label": analytics["time_range_label"],
        "calculation_basis_fa": analytics["calculation_basis_fa"],
        "kpis": analytics["kpis"],
        "equity_curve": analytics["equity_curve"],
        "active_trades": [serialize_trade(t) for t in active_trades],
        "recent_closed": [serialize_trade(t) for t in recent_closed],
        "market_strip": market_strip,
        "top_news": [
            {
                "id": n.id,
                "source_name": n.source_name,
                "persian_title": n.persian_title,
                "persian_summary": n.persian_summary,
                "category": n.category,
                "impact_level": n.impact_level,
                "market_impact_pct": n.market_impact_pct,
                "active_trade_risk_score": n.active_trade_risk_score,
                "related_currencies": json.loads(n.related_currencies_json or "[]"),
                "related_symbols": json.loads(n.related_symbols_json or "[]"),
                "published_at": n.published_at,
                "canonical_url": n.canonical_url,
                "is_demo_data": n.is_demo_data,
            }
            for n in top_news
        ],
        "upcoming_events": [
            {
                "id": ev.id,
                "event_name_fa": ev.event_name_fa,
                "currency": ev.currency,
                "importance": ev.importance,
                "impact_pct": ev.impact_pct,
                "scheduled_at": ev.scheduled_at,
                "status": ev.status,
                "actual": ev.actual,
                "forecast": ev.forecast,
                "previous": ev.previous,
                "is_demo_data": ev.is_demo_data,
            }
            for ev in upcoming_events
        ],
        "telegram_eligible_count": sum(1 for q in quals if q.eligible_for_telegram),
        "telegram_total_pairs_tf": len(quals),
        "sources_health": [
            {
                "source_key": h.source_key,
                "source_type": h.source_type,
                "display_name": h.display_name,
                "status": h.status,
                "latency_ms": h.latency_ms,
                "last_success_at": h.last_success_at,
            }
            for h in health_rows
        ],
    }
