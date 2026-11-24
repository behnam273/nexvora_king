from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import ALLOWED_SYMBOLS, ALLOWED_TIMEFRAMES
from app.database import get_db
from app.models import BacktestQualification, User
from app.schemas import BacktestQualificationOut
from app.security import get_current_user
from app.services.analytics import compute_performance_analytics

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/performance")
def get_performance(
    days: Optional[int] = Query(default=None, ge=1, le=365),
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    include_be: bool = True,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sym = symbol if symbol in ALLOWED_SYMBOLS else None
    tf = timeframe if timeframe in ALLOWED_TIMEFRAMES else None
    return compute_performance_analytics(
        db=db,
        days=days,
        symbol=sym,
        timeframe=tf,
        include_be_in_winrate_denominator=include_be,
    )


@router.get("/policy")
def get_trading_policy(_user: User = Depends(get_current_user)):
    """
    Exposes the exact risk policy the engine is running so the PWA can show the
    user what each timeframe really does (stops, targets, exit split, filters).
    """
    from app.engine.policy import (
        CONSECUTIVE_LOSS_PAUSE,
        CONSECUTIVE_LOSS_PAUSE_HOURS,
        MAX_CONCURRENT_PER_SYMBOL,
        MAX_CONCURRENT_TRADES,
        TRADING_POLICY_VERSION,
        all_policies,
    )

    tfs = []
    for p in all_policies():
        tfs.append(
            {
                "timeframe": p.timeframe,
                "risk_tier": p.risk_tier,
                "sl_buf_atr": p.sl_buf_atr,
                "min_stop_atr": p.min_stop_atr,
                "max_stop_atr": p.max_stop_atr,
                "targets": [
                    {"label": "TP1", "rr": p.tp1_rr, "exit_pct": p.tp1_exit_pct},
                    {"label": "TP2", "rr": p.tp2_rr, "exit_pct": p.tp2_exit_pct},
                    {"label": "TP3", "rr": p.tp3_rr, "exit_pct": p.tp3_exit_pct},
                ],
                "early_be_pct": round(p.early_be_fraction * 100, 1),
                "min_score": p.min_score,
                "min_adx": p.min_adx,
                "min_rr_tp1": p.min_rr_tp1,
                "require_session": p.require_session,
                "require_dual_htf": p.require_dual_htf,
                "require_di_alignment": p.require_di_alignment,
                "require_idm": p.require_idm,
                "pending_expiry_hours": p.pending_expiry_hours,
            }
        )

    return {
        "policy_version": TRADING_POLICY_VERSION,
        "max_concurrent_trades": MAX_CONCURRENT_TRADES,
        "max_concurrent_per_symbol": MAX_CONCURRENT_PER_SYMBOL,
        "consecutive_loss_pause": CONSECUTIVE_LOSS_PAUSE,
        "consecutive_loss_pause_hours": CONSECUTIVE_LOSS_PAUSE_HOURS,
        "timeframes": tfs,
        "gate_rules_fa": [
            "هیچ سیگنالی بدون زنجیره کامل «سوییپ نقدینگی → CHoCH → ناحیه ورود (POI)» ساخته نمی‌شود.",
            "حد ضرر همیشه ساختاری است (پشت سوئیپ و لبه زون + بافر ATR) و داخل بازه مجاز هر تایم‌فریم قفل می‌شود.",
            "فقط ترکیب‌هایی که بک‌تست عمیق آن‌ها وین‌ریت، Profit Factor و انتظار ریاضی مثبت را تأیید کند مجاز به انتشار در تلگرام هستند.",
            "داده بازپخش/آزمایشی هرگز به کانال تلگرام ارسال نمی‌شود.",
        ],
    }


@router.get("/qualifications", response_model=List[BacktestQualificationOut])
def get_backtest_qualifications(
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(BacktestQualification)
        .order_by(BacktestQualification.eligible_for_telegram.desc(), BacktestQualification.win_rate.desc())
        .all()
    )
    return [BacktestQualificationOut.model_validate(r) for r in rows]
