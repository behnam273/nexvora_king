from __future__ import annotations

import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.engine.backtester import refresh_all_qualifications
from app.engine.scheduler import get_or_create_engine_config, run_engine_scan_cycle
from app.models import (
    AuditLog,
    BacktestQualification,
    NewsItem,
    SignalTrade,
    SourceHealth,
    User,
)
from app.schemas import AdminUserRoleUpdate, AuditLogOut, EngineConfigUpdate, SourceHealthOut, UserOut
from app.security import get_client_ip, require_admin, write_audit
from app.services.news_engine import fetch_and_ingest_news
from app.services.realtime import realtime_hub

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/overview")
def admin_overview(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    sources = db.query(SourceHealth).order_by(SourceHealth.source_type, SourceHealth.source_key).all()
    quals = db.query(BacktestQualification).all()
    return {
        "users_total": db.query(User).count(),
        "users_active": db.query(User).filter(User.is_active == True).count(),  # noqa: E712
        "trades_total": db.query(SignalTrade).count(),
        "trades_open": db.query(SignalTrade).filter(SignalTrade.status.in_(["PENDING_LIMIT", "ACTIVE", "TP1_HIT", "TP2_HIT"])).count(),
        "news_total": db.query(NewsItem).count(),
        "eligible_pairs_count": sum(1 for q in quals if q.eligible_for_telegram),
        "total_pairs_tf": len(quals),
        "data_mode": settings.nexvora_data_mode,
        "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_channel_id),
        "telegram_dry_run": settings.telegram_dry_run,
        "twelvedata_configured": bool(settings.twelve_data_api_key),
        "llm_configured": bool(settings.llm_api_key and settings.llm_api_base_url),
        "sources": [SourceHealthOut.model_validate(s).model_dump() for s in sources],
    }


@router.get("/users", response_model=List[UserOut])
def admin_list_users(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [UserOut.model_validate(u) for u in users]


@router.patch("/users/{user_id}", response_model=UserOut)
def admin_update_user(
    user_id: int,
    payload: AdminUserRoleUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
    if target.id == admin.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="نمی‌توانید حساب ادمین خودتان را غیرفعال کنید.")
    if payload.role == "SUPER_ADMIN" and admin.role != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="فقط SUPER_ADMIN می‌تواند نقش SUPER_ADMIN اختصاص دهد.")

    old_role = target.role
    target.role = payload.role
    if payload.is_active is not None:
        target.is_active = payload.is_active
    db.commit()
    db.refresh(target)

    write_audit(
        db,
        action="ADMIN_USER_UPDATED",
        actor=admin,
        target_type="user",
        target_id=str(target.id),
        ip_address=get_client_ip(request),
        details={"old_role": old_role, "new_role": target.role, "is_active": target.is_active},
    )
    return UserOut.model_validate(target)


@router.get("/engine-config")
def admin_get_engine_config(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    cfg = get_or_create_engine_config(db)
    return {
        "preset_name": cfg.preset_name,
        "tp1_rr": cfg.tp1_rr,
        "tp2_rr": cfg.tp2_rr,
        "tp3_rr": cfg.tp3_rr,
        "tp1_exit_pct": cfg.tp1_exit_pct,
        "tp2_exit_pct": cfg.tp2_exit_pct,
        "min_score_4h": cfg.min_score_4h,
        "min_score_15m": cfg.min_score_15m,
        "min_score_5m": cfg.min_score_5m,
        "min_adx": cfg.min_adx,
        "trend_ema_len": cfg.trend_ema_len,
        "require_sweep": cfg.require_sweep,
        "require_idm": cfg.require_idm,
        "require_strong_choch_body": cfg.require_strong_choch_body,
        "use_pd_filter": cfg.use_pd_filter,
        "use_session_filter": cfg.use_session_filter,
        "skip_dead_volatility": cfg.skip_dead_volatility,
        "skip_news_spikes": cfg.skip_news_spikes,
        "news_blackout_minutes": cfg.news_blackout_minutes,
        "correlation_guard": cfg.correlation_guard,
        "min_backtest_winrate": cfg.min_backtest_winrate,
        "min_backtest_pf": cfg.min_backtest_pf,
        "min_backtest_trades": cfg.min_backtest_trades,
        "telegram_send_signals": cfg.telegram_send_signals,
        "telegram_send_tracking": cfg.telegram_send_tracking,
        "telegram_send_high_news": cfg.telegram_send_high_news,
        "telegram_min_news_impact_pct": cfg.telegram_min_news_impact_pct,
        "updated_at": cfg.updated_at,
    }


@router.put("/engine-config")
def admin_update_engine_config(
    payload: EngineConfigUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    cfg = get_or_create_engine_config(db)
    changed = {}
    for k, v in payload.model_dump(exclude_none=True).items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
            changed[k] = v
    if cfg.tp1_exit_pct + cfg.tp2_exit_pct > 95.0:
        raise HTTPException(status_code=400, detail="مجموع درصد خروج TP1 و TP2 نمی‌تواند بیش از ۹۵٪ باشد.")
    db.commit()
    db.refresh(cfg)

    write_audit(
        db,
        action="ENGINE_CONFIG_UPDATED",
        actor=admin,
        target_type="engine_config",
        target_id="1",
        ip_address=get_client_ip(request),
        details=changed,
    )
    return {"status": "ok", "changed": changed}


@router.post("/actions/scan-now")
async def admin_scan_now(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    summary = run_engine_scan_cycle(db)
    write_audit(db, action="ADMIN_MANUAL_SCAN", actor=admin, ip_address=get_client_ip(request), details=summary)
    await realtime_hub.broadcast_public("engine_update", summary)
    return {"status": "ok", **summary}


@router.post("/actions/refresh-backtests")
async def admin_refresh_backtests(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    cfg = get_or_create_engine_config(db)
    rows = refresh_all_qualifications(db, cfg)
    eligible = sum(1 for r in rows if r.eligible_for_telegram)
    write_audit(
        db,
        action="ADMIN_REFRESH_BACKTESTS",
        actor=admin,
        ip_address=get_client_ip(request),
        details={"total": len(rows), "eligible": eligible},
    )
    await realtime_hub.broadcast_public("backtest_update", {"total": len(rows), "eligible": eligible})
    return {"status": "ok", "total": len(rows), "eligible_for_telegram": eligible}


@router.post("/actions/refresh-news")
async def admin_refresh_news(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    items = fetch_and_ingest_news(db)
    write_audit(
        db,
        action="ADMIN_REFRESH_NEWS",
        actor=admin,
        ip_address=get_client_ip(request),
        details={"ingested": len(items)},
    )
    await realtime_hub.broadcast_public("news_update", {"count": len(items)})
    return {"status": "ok", "ingested": len(items)}


@router.get("/telegram-health")
def admin_telegram_health(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Turns the Telegram channel into an observable subsystem instead of a black box.

    Returns the live configuration mode plus the most recent delivery/failure
    audit events so a broken bot token, a wrong channel id or a channel where the
    bot is not an admin can be diagnosed in seconds.
    """
    from app.models import AuditLog, SourceHealth

    settings = get_settings()
    configured = bool(settings.telegram_bot_token and settings.telegram_channel_id)
    mode = "LIVE" if (configured and not settings.telegram_dry_run) else ("DRY_RUN" if configured else "NOT_CONFIGURED")

    health = db.query(SourceHealth).filter(SourceHealth.source_key == "telegram_bot").first()
    recent = (
        db.query(AuditLog)
        .filter(AuditLog.action.like("TELEGRAM%"))
        .order_by(AuditLog.id.desc())
        .limit(30)
        .all()
    )
    events = [
        {
            "action": a.action,
            "outcome": a.outcome,
            "target_id": a.target_id,
            "details": a.details_json,
            "created_at": a.created_at,
        }
        for a in recent
    ]
    failures = [e for e in events if e["outcome"] != "SUCCESS"][:10]

    hints: list[str] = []
    if mode == "NOT_CONFIGURED":
        hints.append("TELEGRAM_BOT_TOKEN و TELEGRAM_CHANNEL_ID را در متغیرهای محیطی تنظیم کنید.")
    if settings.telegram_dry_run:
        hints.append("TELEGRAM_DRY_RUN=true است؛ پیام‌ها فقط ثبت می‌شوند و به تلگرام ارسال نمی‌شوند.")
    if any("chat not found" in str(e["details"]).lower() for e in failures):
        hints.append("chat_id اشتباه است یا ربات هنوز عضو کانال نیست.")
    if any("not enough rights" in str(e["details"]).lower() for e in failures):
        hints.append("ربات باید ادمین کانال با دسترسی ارسال پیام باشد.")
    if any("unauthorized" in str(e["details"]).lower() for e in failures):
        hints.append("توکن ربات نامعتبر است (BotFather را بررسی کنید).")
    if failures and not hints:
        hints.append("خطای ارسال ثبت شده است؛ جزئیات آخرین خطا را ببینید.")

    return {
        "mode": mode,
        "configured": configured,
        "dry_run": settings.telegram_dry_run,
        "channel_id_set": bool(settings.telegram_channel_id),
        "bot_token_set": bool(settings.telegram_bot_token),
        "health": {
            "status": health.status if health else "UNKNOWN",
            "requests_count": health.requests_count if health else 0,
            "failure_count": health.failure_count if health else 0,
            "last_success_at": health.last_success_at if health else None,
            "last_error_at": health.last_error_at if health else None,
            "last_error_msg": health.last_error_msg if health else "",
            "latency_ms": health.latency_ms if health else None,
        },
        "recent_events": events,
        "recent_failures": failures,
        "hints_fa": hints,
    }


@router.post("/actions/test-telegram")
def admin_test_telegram(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.telegram_bot import send_test_signal_card_to_telegram

    settings = get_settings()
    msg_id = send_test_signal_card_to_telegram(db)
    mode = "DRY_RUN" if (settings.telegram_dry_run or not settings.telegram_bot_token) else "LIVE"
    write_audit(
        db,
        action="ADMIN_TEST_TELEGRAM",
        actor=admin,
        ip_address=get_client_ip(request),
        details={"mode": mode, "ok": bool(msg_id), "message_id": msg_id, "type": "official_signal_card_png"},
    )
    return {"status": "ok" if msg_id else "error", "mode": mode, "message_id": msg_id}


@router.get("/audit-logs", response_model=List[AuditLogOut])
def admin_audit_logs(
    limit: int = Query(default=80, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [
        AuditLogOut(
            id=r.id,
            actor_user_id=r.actor_user_id,
            actor_email=r.actor_email,
            action=r.action,
            target_type=r.target_type,
            target_id=r.target_id,
            outcome=r.outcome,
            ip_address=r.ip_address,
            correlation_id=r.correlation_id,
            details=json.loads(r.details_json or "{}"),
            created_at=r.created_at,
        )
        for r in rows
    ]
