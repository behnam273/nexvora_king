from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import ALLOWED_SYMBOLS
from app.database import get_db
from app.models import EconomicEvent, NewsItem, User
from app.security import get_current_user

router = APIRouter(prefix="/api/v1", tags=["news"])


def _serialize_news(n: NewsItem) -> dict:
    return {
        "id": n.id,
        "source_name": n.source_name,
        "source_type": n.source_type,
        "canonical_url": n.canonical_url,
        "original_headline": n.original_headline,
        "persian_title": n.persian_title,
        "persian_summary": n.persian_summary,
        "summary_is_ai": n.summary_is_ai,
        "category": n.category,
        "related_currencies": json.loads(n.related_currencies_json or "[]"),
        "related_symbols": json.loads(n.related_symbols_json or "[]"),
        "impact_level": n.impact_level,
        "market_impact_pct": n.market_impact_pct,
        "importance_score": n.importance_score,
        "volatility_score": n.volatility_score,
        "currency_relevance_score": n.currency_relevance_score,
        "direction_bias": n.direction_bias,
        "direction_confidence": n.direction_confidence,
        "active_trade_risk_score": n.active_trade_risk_score,
        "methodology_note_fa": n.methodology_note_fa,
        "published_at": n.published_at,
        "first_seen_at": n.first_seen_at,
        "updated_at": n.updated_at,
        "telegram_sent": n.telegram_sent,
        "is_demo_data": n.is_demo_data,
    }


@router.get("/news")
def list_news(
    currency: Optional[str] = None,
    symbol: Optional[str] = None,
    category: Optional[str] = None,
    impact: Optional[str] = None,
    source: Optional[str] = None,
    min_impact_pct: int = Query(default=0, ge=0, le=100),
    limit: int = Query(default=40, ge=1, le=100),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(NewsItem)
    if category and category != "ALL":
        q = q.filter(NewsItem.category == category)
    if impact in ("HIGH", "MEDIUM", "LOW"):
        q = q.filter(NewsItem.impact_level == impact)
    if source and source != "ALL":
        q = q.filter(NewsItem.source_name.ilike(f"%{source}%"))
    if min_impact_pct > 0:
        q = q.filter(NewsItem.market_impact_pct >= min_impact_pct)

    rows = q.order_by(NewsItem.published_at.desc()).limit(limit * 2).all()
    out = []
    for n in rows:
        curs = json.loads(n.related_currencies_json or "[]")
        syms = json.loads(n.related_symbols_json or "[]")
        if currency and currency != "ALL" and currency.upper() not in curs:
            continue
        if symbol and symbol in ALLOWED_SYMBOLS and symbol not in syms:
            continue
        out.append(_serialize_news(n))
        if len(out) >= limit:
            break

    return {"count": len(out), "items": out}


@router.get("/news/{news_id}")
def get_news_detail(
    news_id: int,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(NewsItem).filter(NewsItem.id == news_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="خبر موردنظر یافت نشد.")
    return _serialize_news(row)


@router.get("/calendar")
def list_economic_calendar(
    currency: Optional[str] = None,
    importance: Optional[str] = None,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(EconomicEvent)
    if currency and currency != "ALL":
        q = q.filter(EconomicEvent.currency == currency.upper())
    if importance in ("HIGH", "MEDIUM", "LOW"):
        q = q.filter(EconomicEvent.importance == importance)
    if status_filter in ("SCHEDULED", "PUBLISHED", "REVISED"):
        q = q.filter(EconomicEvent.status == status_filter)

    rows = q.order_by(EconomicEvent.scheduled_at.asc()).limit(100).all()
    return {
        "count": len(rows),
        "items": [
            {
                "id": ev.id,
                "event_name_en": ev.event_name_en,
                "event_name_fa": ev.event_name_fa,
                "country": ev.country,
                "currency": ev.currency,
                "related_symbols": json.loads(ev.related_symbols_json or "[]"),
                "category": ev.category,
                "importance": ev.importance,
                "impact_pct": ev.impact_pct,
                "scheduled_at": ev.scheduled_at,
                "timezone_name": ev.timezone_name,
                "status": ev.status,
                "actual": ev.actual,
                "forecast": ev.forecast,
                "previous": ev.previous,
                "revision": ev.revision,
                "surprise_note_fa": ev.surprise_note_fa,
                "source_name": ev.source_name,
                "source_url": ev.source_url,
                "is_demo_data": ev.is_demo_data,
            }
            for ev in rows
        ],
    }
