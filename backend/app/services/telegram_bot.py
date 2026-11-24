from __future__ import annotations

import html
import json
import time
import uuid
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import SYMBOL_META, TIMEFRAME_META, get_settings
from app.models import NewsItem, SignalTrade, SourceHealth, TradeEvent, utcnow
from app.security import validate_external_url, write_audit

ALLOWED_TELEGRAM_HOSTS = {"api.telegram.org"}


def _record_telegram_health(
    db: Session,
    status_str: str,
    latency_ms: Optional[int] = None,
    error_msg: str = "",
) -> None:
    row = db.query(SourceHealth).filter(SourceHealth.source_key == "telegram_bot").first()
    if not row:
        row = SourceHealth(
            source_key="telegram_bot",
            source_type="telegram",
            display_name="Telegram Signal Channel Bot",
            rate_limit_note="Telegram Bot API (<= 20 msgs/min per channel)",
        )
        db.add(row)
    row.status = status_str
    row.requests_count = (row.requests_count or 0) + 1
    if latency_ms is not None:
        row.latency_ms = latency_ms
    if status_str in ("HEALTHY", "DEMO_FALLBACK"):
        row.last_success_at = utcnow()
        row.last_error_msg = ""
    elif error_msg:
        row.last_error_at = utcnow()
        row.last_error_msg = error_msg[:400]
        row.failure_count = (row.failure_count or 0) + 1
    db.commit()



# Telegram returns 429 with a `retry_after` when the channel is throttled. A
# signal that is silently dropped because of a transient limit is a *trading*
# failure, so every call is retried with backoff instead of giving up.
_TG_MAX_ATTEMPTS = 4


def _post_with_retry(
    db: Session,
    *,
    url: str,
    json_payload: Optional[dict] = None,
    data_fields: Optional[dict] = None,
    files: Optional[dict] = None,
    audit_action: str = "TELEGRAM_SEND",
    target_id: str = "",
    timeout: float = 12.0,
    extra_details: Optional[dict] = None,
) -> Optional[str]:
    last_error = ""
    for attempt in range(1, _TG_MAX_ATTEMPTS + 1):
        t0 = time.monotonic()
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                if files is not None:
                    resp = client.post(url, data=data_fields or {}, files=files)
                else:
                    resp = client.post(url, json=json_payload or {})
            latency = int((time.monotonic() - t0) * 1000)

            if resp.status_code == 200:
                payload = resp.json()
                if payload.get("ok"):
                    msg_id = str(payload["result"]["message_id"])
                    _record_telegram_health(db, "HEALTHY", latency)
                    details = {"attempt": attempt}
                    details.update(extra_details or {})
                    write_audit(
                        db,
                        action=audit_action,
                        outcome="SUCCESS",
                        target_type="telegram",
                        target_id=msg_id,
                        details=details,
                    )
                    return msg_id
                last_error = f"not ok: {str(payload)[:180]}"
            elif resp.status_code == 429:
                retry_after = 3
                try:
                    retry_after = int(resp.json().get("parameters", {}).get("retry_after", 3))
                except Exception:
                    pass
                last_error = f"429 rate limited (retry_after={retry_after}s)"
                time.sleep(min(max(retry_after, 1), 20))
            elif resp.status_code in (500, 502, 503, 504):
                last_error = f"HTTP {resp.status_code} upstream error"
                time.sleep(min(2 ** attempt, 10))
            else:
                # 400/401/403 are configuration problems (bad token/chat id):
                # retrying cannot help, surface the exact Telegram message instead.
                last_error = f"HTTP {resp.status_code}: {resp.text[:220]}"
                _record_telegram_health(db, "DEGRADED", latency, last_error)
                write_audit(
                    db,
                    action=f"{audit_action}_FAILED",
                    outcome="FAILURE",
                    target_type="telegram",
                    target_id=target_id,
                    details={"status": resp.status_code, "error": last_error, "attempt": attempt},
                )
                return None
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(min(2 ** attempt, 10))

    _record_telegram_health(db, "OFFLINE", None, last_error)
    write_audit(
        db,
        action=f"{audit_action}_FAILED",
        outcome="FAILURE",
        target_type="telegram",
        target_id=target_id,
        details={"error": last_error, "attempts": _TG_MAX_ATTEMPTS},
    )
    return None


def _send_telegram_html(
    db: Session,
    text_html: str,
    reply_to_message_id: Optional[str] = None,
    audit_action: str = "TELEGRAM_SEND",
    target_id: str = "",
) -> Optional[str]:
    settings = get_settings()
    if settings.telegram_dry_run or not settings.telegram_bot_token or not settings.telegram_channel_id:
        fake_id = f"dryrun-{uuid.uuid4().hex[:10]}"
        _record_telegram_health(db, "DEMO_FALLBACK", latency_ms=1)
        write_audit(
            db,
            action=f"{audit_action}_DRYRUN",
            outcome="SUCCESS",
            target_type="telegram",
            target_id=target_id or fake_id,
            details={"reply_to": reply_to_message_id, "preview": text_html[:220]},
        )
        return fake_id

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    if not validate_external_url(url, ALLOWED_TELEGRAM_HOSTS):
        return None

    payload: dict = {
        "chat_id": settings.telegram_channel_id,
        "text": text_html,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_to_message_id and reply_to_message_id.isdigit():
        payload["reply_to_message_id"] = int(reply_to_message_id)

    return _post_with_retry(
        db,
        url=url,
        json_payload=payload,
        audit_action=audit_action,
        target_id=target_id,
    )


def _send_telegram_photo(
    db: Session,
    photo_bytes: bytes,
    caption_html: str,
    filename: str = "nexvora-signal-card.png",
    reply_to_message_id: Optional[str] = None,
    audit_action: str = "TELEGRAM_PHOTO_SEND",
    target_id: str = "",
) -> Optional[str]:
    """Send an official NEXVORA Signal Card PNG via Telegram Bot API sendPhoto."""
    settings = get_settings()
    if settings.telegram_dry_run or not settings.telegram_bot_token or not settings.telegram_channel_id:
        fake_id = f"dryrun-photo-{uuid.uuid4().hex[:10]}"
        _record_telegram_health(db, "DEMO_FALLBACK", latency_ms=1)
        write_audit(
            db,
            action=f"{audit_action}_DRYRUN",
            outcome="SUCCESS",
            target_type="telegram",
            target_id=target_id or fake_id,
            details={"photo_bytes": len(photo_bytes), "filename": filename, "caption_preview": caption_html[:220]},
        )
        return fake_id

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendPhoto"
    if not validate_external_url(url, ALLOWED_TELEGRAM_HOSTS):
        return None

    # Telegram photo caption limit is 1024 chars
    safe_caption = caption_html[:1020]
    data_fields: dict = {
        "chat_id": settings.telegram_channel_id,
        "caption": safe_caption,
        "parse_mode": "HTML",
    }
    if reply_to_message_id and reply_to_message_id.isdigit():
        data_fields["reply_to_message_id"] = str(reply_to_message_id)

    return _post_with_retry(
        db,
        url=url,
        data_fields=data_fields,
        files={"photo": (filename, photo_bytes, "image/png")},
        audit_action=audit_action,
        target_id=target_id,
        timeout=25.0,
        extra_details={"photo_bytes": len(photo_bytes), "filename": filename},
    )


def format_signal_telegram_html(trade: SignalTrade) -> str:
    settings = get_settings()
    meta = SYMBOL_META[trade.symbol]
    tf_meta = TIMEFRAME_META[trade.timeframe]
    d = meta["digits"]
    dir_badge = "🟢 خرید (BUY / LONG)" if trade.direction == "LONG" else "🔴 فروش (SELL / SHORT)"
    risk_badge = (
        "🛡️ حالت امن (4H)" if trade.risk_tier == "SAFE"
        else "⚖️ ریسک متوسط (15m)" if trade.risk_tier == "MEDIUM_RISK"
        else "⚡ ریسک بالا — فیلتر حداکثری (5m)"
    )
    demo_tag = "\n⚠️ <i>[حالت آزمایشی/بازپخش آفلاین — داده زنده نیست]</i>" if trade.is_demo_data else ""

    return (
        f"<b>📊 سیگنال جدید NEXVORA | Trading Hub 3.0</b>{demo_tag}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>نماد:</b> <code>{meta['display']}</code> ({meta['name_fa']})\n"
        f"<b>جهت:</b> {dir_badge}\n"
        f"<b>تایم‌فریم و ریسک:</b> {risk_badge}\n"
        f"<b>ماژول ورود:</b> <code>{trade.entry_module}</code> | <b>امتیاز:</b> <code>{trade.confluence_score:.1f}/10 ({trade.grade})</code>\n"
        f"<b>وین‌ریت بک‌تست فیلتر:</b> <code>{trade.backtest_win_rate_at_entry:.1f}%</code>\n"
        f"<b>ریسک ساختاری:</b> <code>{trade.risk_pips:.0f} پیپ ≈ {trade.risk_atr:.1f}×ATR</code>"
        + (f" | <b>حجم:</b> <code>{trade.position_size_lots}</code> لات" if trade.position_size_lots else "")
        + "\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>نقطه ورود (Limit):</b> <code>{trade.entry_price:.{d}f}</code>\n"
        f"🛑 <b>حد ضرر (SL):</b> <code>{trade.initial_sl:.{d}f}</code>\n"
        f"✅ <b>TP1 ({trade.tp1_exit_pct:.0f}% + BE):</b> <code>{trade.tp1:.{d}f}</code>\n"
        f"✅ <b>TP2 ({trade.tp2_exit_pct:.0f}% + SL→TP1):</b> <code>{trade.tp2:.{d}f}</code>\n"
        f"🏆 <b>TP3 ({trade.tp3_exit_pct:.0f}% نهایی):</b> <code>{trade.tp3:.{d}f}</code>\n"
        f"🛡️ <b>ریسک‌فری در قیمت:</b> <code>{(trade.early_be_price or 0.0):.{d}f}</code> (انتقال SL به سر‌به‌سر)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>کد پیگیری:</b> <code>{trade.trade_code}</code>\n"
        f"🌐 مشاهده زنده و نمودار در PWA: {html.escape(settings.effective_public_url)}/trades/{trade.id}"
    )


def publish_signal_to_telegram(db: Session, trade: SignalTrade) -> Optional[str]:
    from app.services.signal_card import render_signal_card_png

    caption = format_signal_telegram_html(trade)
    msg_id: Optional[str] = None
    try:
        card_png = render_signal_card_png(trade)
        msg_id = _send_telegram_photo(
            db,
            photo_bytes=card_png,
            caption_html=caption,
            filename=f"{trade.trade_code}.png",
            audit_action="TELEGRAM_SIGNAL_PUBLISHED",
            target_id=trade.trade_code,
        )
    except Exception as exc:
        print(f"[NEXVORA] Signal card render/send fallback to text for {trade.trade_code}: {exc}", flush=True)

    # Graceful fallback to text HTML message if sendPhoto fails
    if not msg_id:
        msg_id = _send_telegram_html(
            db,
            text_html=caption,
            audit_action="TELEGRAM_SIGNAL_PUBLISHED",
            target_id=trade.trade_code,
        )
    if msg_id:
        trade.telegram_message_id = msg_id
        db.commit()
    return msg_id


def send_test_signal_card_to_telegram(db: Session) -> Optional[str]:
    """Renders and sends a live official NEXVORA Signal Card PNG to the configured Telegram channel."""
    from datetime import datetime, timezone
    from app.engine.market_data import get_market_series
    from app.services.signal_card import render_signal_card_png

    sample_trade = db.query(SignalTrade).order_by(SignalTrade.created_at.desc()).first()
    if sample_trade is None:
        series = get_market_series("XAUUSD", "15m", limit=120, db=db)
        px = float(series.candles[-1].close)
        risk = max(round(px * 0.0024, 2), 3.0)
        sample_trade = SignalTrade(
            trade_code="NXV-CARD-TEST",
            symbol="XAUUSD",
            timeframe="15m",
            risk_tier="MEDIUM_RISK",
            direction="SHORT",
            entry_module="SWEEP",
            status="ACTIVE",
            outcome="OPEN",
            entry_price=round(px, 2),
            initial_sl=round(px + risk, 2),
            current_sl=round(px + risk, 2),
            tp1=round(px - risk * 1.2, 2),
            tp2=round(px - risk * 2.2, 2),
            tp3=round(px - risk * 3.2, 2),
            tp1_exit_pct=50.0,
            tp2_exit_pct=30.0,
            tp3_exit_pct=20.0,
            confluence_score=9.2,
            grade="A+",
            htf_bias="BEARISH",
            session_name="NEW YORK",
            backtest_win_rate_at_entry=78.5,
            eligible_for_telegram=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        candles = series.candles
    else:
        candles = None

    png = render_signal_card_png(sample_trade, candles=candles)
    caption = (
        f"<b>✅ NEXVORA — تست رسمی کارت سیگنال تلگرام</b>\n"
        f"نماد نمونه: <code>{sample_trade.symbol}</code> ({sample_trade.timeframe}) | "
        f"جهت: <code>{sample_trade.direction}</code>\n"
        f"موتور Trading Hub 3.0 و ارسال کارت گرافیکی رسمی فعال است."
    )
    return _send_telegram_photo(
        db=db,
        photo_bytes=png,
        caption_html=caption,
        filename=f"{sample_trade.trade_code}-test.png",
        audit_action="ADMIN_TEST_TELEGRAM",
        target_id="manual_test_card",
    )


def publish_position_update_reply(db: Session, trade: SignalTrade, event: TradeEvent) -> Optional[str]:
    meta = SYMBOL_META[trade.symbol]
    d = meta["digits"]
    icon_map = {
        "LIMIT_FILLED": "▶️",
        "SL_MOVED_BE": "🛡️",
        "TP1_HIT": "🎯",
        "TP2_HIT": "🎯🎯",
        "TP3_HIT": "🏆",
        "SL_HIT": "🛑",
        "BE_HIT": "🛡️",
        "TP1_LOCK_HIT": "✅",
        "EXPIRED": "⏳",
        "CANCELLED": "❌",
    }
    icon = icon_map.get(event.event_type, "📌")
    price_str = f"<code>{event.price:.{d}f}</code>" if event.price is not None else "-"
    text = (
        f"{icon} <b>به‌روزرسانی پیگیری پوزیشن | <code>{trade.trade_code}</code></b>\n"
        f"<b>نماد:</b> <code>{meta['display']}</code> ({trade.timeframe}) | <b>وضعیت:</b> <code>{trade.status}</code>\n"
        f"<b>قیمت رویداد:</b> {price_str} | <b>حد ضرر فعال:</b> <code>{trade.current_sl:.{d}f}</code>\n"
        f"<b>سود/زیان تحقق‌یافته:</b> <code>{trade.realized_r:+.2f}R</code> (<code>{trade.realized_pips:+.1f} pips</code>)\n"
        f"📝 {html.escape(event.description_fa)}"
    )
    reply_id = _send_telegram_html(
        db,
        text_html=text,
        reply_to_message_id=trade.telegram_message_id,
        audit_action="TELEGRAM_TRACKING_REPLY",
        target_id=f"{trade.trade_code}:{event.event_type}",
    )
    if reply_id:
        event.telegram_reply_id = reply_id
        db.commit()
    return reply_id


def publish_high_impact_news_to_telegram(db: Session, news: NewsItem) -> Optional[str]:
    syms = ", ".join(json.loads(news.related_symbols_json or "[]"))
    curs = ", ".join(json.loads(news.related_currencies_json or "[]"))
    demo_tag = "\n⚠️ <i>[خبر نمونه آفلاین — داده زنده نیست]</i>" if news.is_demo_data else ""
    text = (
        f"🚨 <b>خبر مهم بازار مالی | تاثیر: {news.market_impact_pct}% ({news.impact_level})</b>{demo_tag}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>{html.escape(news.persian_title)}</b>\n\n"
        f"{html.escape(news.persian_summary)}\n\n"
        f"💱 <b>ارزهای متاثر:</b> <code>{html.escape(curs)}</code>\n"
        f"📊 <b>نمادهای مرتبط:</b> <code>{html.escape(syms)}</code>\n"
        f"📈 <b>نوسان تخمینی:</b> <code>{news.volatility_score}%</code> | <b>ریسک پوزیشن‌های باز:</b> <code>{news.active_trade_risk_score}%</code>\n"
        f"📰 <b>منبع اصلی:</b> <a href=\"{html.escape(news.canonical_url)}\">{html.escape(news.source_name)}</a>"
    )
    msg_id = _send_telegram_html(
        db,
        text_html=text,
        audit_action="TELEGRAM_HIGH_NEWS_PUBLISHED",
        target_id=str(news.id),
    )
    if msg_id:
        news.telegram_sent = True
        db.commit()
    return msg_id
