from __future__ import annotations

import csv
import io
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.dashboard import serialize_trade
from app.config import ALLOWED_SYMBOLS, ALLOWED_TIMEFRAMES, SYMBOL_META, TIMEFRAME_META
from app.database import get_db
from app.engine.market_data import get_market_series
from app.models import SignalTrade, User, UserTradeJournal
from app.schemas import UserJournalOut, UserJournalUpdate
from app.security import get_current_user

router = APIRouter(prefix="/api/v1/trades", tags=["trades"])


def _safe_csv_cell(val) -> str:
    """Prevent CSV formula injection (=, +, -, @) in Excel exports."""
    s = "" if val is None else str(val)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


@router.get("/live")
def list_live_trades(
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    risk_tier: Optional[str] = None,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(SignalTrade).filter(
        SignalTrade.status.in_(["PENDING_LIMIT", "ACTIVE", "TP1_HIT", "TP2_HIT"])
    )
    if symbol and symbol in ALLOWED_SYMBOLS:
        q = q.filter(SignalTrade.symbol == symbol)
    if timeframe and timeframe in ALLOWED_TIMEFRAMES:
        q = q.filter(SignalTrade.timeframe == timeframe)
    if risk_tier in ("SAFE", "MEDIUM_RISK", "HIGH_RISK"):
        q = q.filter(SignalTrade.risk_tier == risk_tier)

    rows = q.order_by(SignalTrade.updated_at.desc()).all()
    return {
        "count": len(rows),
        "items": [serialize_trade(t) for t in rows],
    }


@router.get("/history")
def list_trade_history(
    search: Optional[str] = None,
    symbol: Optional[str] = None,
    direction: Optional[str] = None,
    timeframe: Optional[str] = None,
    risk_tier: Optional[str] = None,
    outcome: Optional[str] = None,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(SignalTrade)
    if symbol and symbol in ALLOWED_SYMBOLS:
        q = q.filter(SignalTrade.symbol == symbol)
    if direction in ("LONG", "SHORT"):
        q = q.filter(SignalTrade.direction == direction)
    if timeframe and timeframe in ALLOWED_TIMEFRAMES:
        q = q.filter(SignalTrade.timeframe == timeframe)
    if risk_tier in ("SAFE", "MEDIUM_RISK", "HIGH_RISK"):
        q = q.filter(SignalTrade.risk_tier == risk_tier)
    if outcome in ("WIN", "LOSS", "BE", "OPEN", "CANCELLED"):
        q = q.filter(SignalTrade.outcome == outcome)
    if status_filter:
        q = q.filter(SignalTrade.status == status_filter)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(
            (SignalTrade.trade_code.ilike(like))
            | (SignalTrade.symbol.ilike(like))
            | (SignalTrade.entry_module.ilike(like))
        )

    total = q.count()
    items = (
        q.order_by(SignalTrade.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [serialize_trade(t) for t in items],
    }


@router.get("/export.csv")
def export_trades_csv(
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    outcome: Optional[str] = None,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(SignalTrade)
    if symbol and symbol in ALLOWED_SYMBOLS:
        q = q.filter(SignalTrade.symbol == symbol)
    if timeframe and timeframe in ALLOWED_TIMEFRAMES:
        q = q.filter(SignalTrade.timeframe == timeframe)
    if outcome in ("WIN", "LOSS", "BE", "OPEN", "CANCELLED"):
        q = q.filter(SignalTrade.outcome == outcome)

    rows = q.order_by(SignalTrade.created_at.desc()).limit(1000).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "trade_code", "symbol", "timeframe", "risk_tier", "direction", "entry_module",
        "status", "outcome", "entry_price", "initial_sl", "current_sl",
        "tp1", "tp2", "tp3", "confluence_score", "grade",
        "realized_r", "realized_pips", "realized_pnl_usd", "data_source", "is_demo_data",
        "created_at", "closed_at",
    ])
    for t in rows:
        writer.writerow([
            _safe_csv_cell(t.trade_code),
            _safe_csv_cell(t.symbol),
            _safe_csv_cell(t.timeframe),
            _safe_csv_cell(t.risk_tier),
            _safe_csv_cell(t.direction),
            _safe_csv_cell(t.entry_module),
            _safe_csv_cell(t.status),
            _safe_csv_cell(t.outcome),
            t.entry_price,
            t.initial_sl,
            t.current_sl,
            t.tp1,
            t.tp2,
            t.tp3,
            t.confluence_score,
            _safe_csv_cell(t.grade),
            t.realized_r,
            t.realized_pips,
            t.realized_pnl_usd,
            _safe_csv_cell(t.data_source),
            t.is_demo_data,
            t.created_at.isoformat() if t.created_at else "",
            t.closed_at.isoformat() if t.closed_at else "",
        ])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="nexvora_trades.csv"'},
    )


@router.get("/journal/mine", response_model=List[UserJournalOut])
def get_my_journals(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(UserTradeJournal)
        .filter(UserTradeJournal.user_id == user.id)
        .order_by(UserTradeJournal.updated_at.desc())
        .all()
    )
    return [UserJournalOut.model_validate(r) for r in rows]


@router.get("/{trade_id}/card.png")
def get_trade_signal_card_png(
    trade_id: int,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns the official NEXVORA Telegram Signal Card (1080x1350 PNG) for this trade."""
    from app.services.signal_card import render_signal_card_png

    trade = db.query(SignalTrade).filter(SignalTrade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="معامله یافت نشد.")
    series = get_market_series(trade.symbol, trade.timeframe, limit=120, db=db)
    png_bytes = render_signal_card_png(trade, candles=series.candles)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="{trade.trade_code}.png"',
            "Cache-Control": "private, max-age=30",
        },
    )


@router.get("/{trade_id}")
def get_trade_detail(
    trade_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    trade = db.query(SignalTrade).filter(SignalTrade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="معامله موردنظر یافت نشد.")

    series = get_market_series(trade.symbol, trade.timeframe, limit=180, db=db)
    candles_out = [
        {
            "time": int(c.timestamp.timestamp()),
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        }
        for c in series.candles
    ]

    # Strictly user-isolated private journal
    journal = (
        db.query(UserTradeJournal)
        .filter(UserTradeJournal.user_id == user.id, UserTradeJournal.trade_id == trade.id)
        .first()
    )

    return {
        "trade": serialize_trade(trade),
        "symbol_meta": SYMBOL_META[trade.symbol],
        "timeframe_meta": TIMEFRAME_META[trade.timeframe],
        "candles": candles_out,
        "candles_source": series.source,
        "candles_is_demo": series.is_demo_data,
        "user_journal": UserJournalOut.model_validate(journal).model_dump() if journal else None,
    }


@router.put("/{trade_id}/journal", response_model=UserJournalOut)
def upsert_user_trade_journal(
    trade_id: int,
    payload: UserJournalUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    trade = db.query(SignalTrade).filter(SignalTrade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="معامله یافت نشد.")

    # Ownership strictly bound to authenticated server-side user.id
    row = (
        db.query(UserTradeJournal)
        .filter(UserTradeJournal.user_id == user.id, UserTradeJournal.trade_id == trade.id)
        .first()
    )
    if not row:
        row = UserTradeJournal(user_id=user.id, trade_id=trade.id)
        db.add(row)
    if payload.is_following is not None:
        row.is_following = payload.is_following
    if payload.personal_risk_usd is not None:
        row.personal_risk_usd = payload.personal_risk_usd
    if payload.notes is not None:
        row.notes = payload.notes
    db.commit()
    db.refresh(row)
    return UserJournalOut.model_validate(row)
