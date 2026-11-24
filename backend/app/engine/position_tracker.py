from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.config import SYMBOL_META
from app.engine.market_data import Candle
from app.engine.policy import get_policy
from app.models import Notification, SignalTrade, TradeEvent, User, utcnow


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _calc_pips(symbol: str, diff: float) -> float:
    pip_size = SYMBOL_META[symbol]["pip_size"]
    return round(diff / pip_size, 1)


def _calc_usd(symbol: str, price_diff: float, lots: float, ref_price: float) -> float:
    if symbol == "XAUUSD":
        usd_per_unit = 100.0
    elif symbol.endswith("USD"):
        usd_per_unit = 100000.0
    elif symbol == "USDJPY":
        usd_per_unit = 100000.0 / max(ref_price, 1.0)
    else:
        usd_per_unit = 100000.0 * 1.27
    return round(price_diff * usd_per_unit * lots, 2)


def _notify_users_for_trade_event(
    db: Session,
    trade: SignalTrade,
    kind: str,
    title_fa: str,
    message_fa: str,
    severity: str = "info",
) -> None:
    users = db.query(User).filter(User.is_active == True).all()  # noqa: E712
    for u in users:
        if kind == "NEW_SIGNAL" and not u.notify_signals:
            continue
        if kind != "NEW_SIGNAL" and not u.notify_tracking:
            continue
        db.add(
            Notification(
                user_id=u.id,
                kind=kind,
                title_fa=title_fa,
                message_fa=message_fa,
                severity=severity,
                related_trade_id=trade.id,
            )
        )


def track_open_trade_with_candle(
    db: Session,
    trade: SignalTrade,
    candle: Candle,
) -> List[TradeEvent]:
    """
    Core Position Lifecycle Tracking Engine:
    Updates PENDING_LIMIT -> ACTIVE -> TP1_HIT (+BE) -> TP2_HIT (+SL@TP1) -> CLOSED_WIN / CLOSED_LOSS / CLOSED_BE / EXPIRED.
    Returns any newly generated TradeEvent rows (so Telegram Reply & WebSocket can broadcast them).
    """
    if trade.status in ("CLOSED_WIN", "CLOSED_LOSS", "CLOSED_BE", "EXPIRED", "CANCELLED"):
        return []

    is_long = trade.direction == "LONG"
    entry = trade.fill_price or trade.entry_price
    risk_d = abs(entry - trade.initial_sl)
    if risk_d <= 0:
        return []

    digits = SYMBOL_META[trade.symbol]["digits"]
    new_events: List[TradeEvent] = []
    trade.current_price = round(candle.close, digits)
    trade.updated_at = utcnow()
    pol = get_policy(trade.timeframe)

    # Track best / worst excursion in R for every bar the trade is alive
    def _update_excursions(hi: float, lo: float) -> None:
        if is_long:
            fav = (hi - entry) / risk_d
            adv = (entry - lo) / risk_d
        else:
            fav = (entry - lo) / risk_d
            adv = (hi - entry) / risk_d
        trade.max_favorable_r = round(max(trade.max_favorable_r or 0.0, fav), 3)
        trade.max_adverse_r = round(max(trade.max_adverse_r or 0.0, adv), 3)

    # 1) PENDING_LIMIT state
    if trade.status == "PENDING_LIMIT":
        # Hard time-based expiry (a limit that never fills must not stay alive forever)
        expires_at = _aware(trade.pending_expires_at)
        if expires_at is None:
            created = _aware(trade.created_at) or utcnow()
            expires_at = created + timedelta(hours=pol.pending_expiry_hours)
            trade.pending_expires_at = expires_at
        if _aware(candle.timestamp) is not None and _aware(candle.timestamp) >= expires_at and not (
            candle.low <= trade.entry_price <= candle.high
        ):
            trade.status = "EXPIRED"
            trade.outcome = "CANCELLED"
            trade.closed_at = utcnow()
            ev_x = TradeEvent(
                trade_id=trade.id,
                event_type="EXPIRED",
                price=candle.close,
                r_value=0.0,
                pips_value=0.0,
                description_fa=(
                    f"سفارش لیمیت {trade.trade_code} پس از {pol.pending_expiry_hours} ساعت بدون رسیدن قیمت "
                    f"به نقطه ورود منقضی شد (اعتبار زمانی سفارش‌های {trade.timeframe})."
                ),
                source_timestamp=candle.timestamp,
            )
            db.add(ev_x)
            new_events.append(ev_x)
            db.commit()
            return new_events

        invalidated = (candle.close < trade.initial_sl) if is_long else (candle.close > trade.initial_sl)
        if invalidated:
            trade.status = "CANCELLED"
            trade.outcome = "CANCELLED"
            trade.closed_at = utcnow()
            ev = TradeEvent(
                trade_id=trade.id,
                event_type="CANCELLED",
                price=candle.close,
                r_value=0.0,
                pips_value=0.0,
                description_fa=f"سفارش لیمیت {trade.trade_code} پیش از فعال‌شدن به دلیل نقض سطح حد ضرر ({trade.initial_sl:.{digits}f}) لغو شد.",
                source_timestamp=candle.timestamp,
            )
            db.add(ev)
            new_events.append(ev)
            _notify_users_for_trade_event(
                db, trade, "TRADE_CLOSED", f"لغو سفارش {trade.symbol}", ev.description_fa, "warning"
            )
            db.commit()
            return new_events

        touched = candle.low <= trade.entry_price <= candle.high
        if touched:
            trade.status = "ACTIVE"
            trade.fill_price = trade.entry_price
            trade.opened_at = candle.timestamp
            trade.pending_expires_at = None
            ev = TradeEvent(
                trade_id=trade.id,
                event_type="LIMIT_FILLED",
                price=trade.fill_price,
                r_value=0.0,
                pips_value=0.0,
                description_fa=(
                    f"پوزیشن {trade.direction} روی {trade.symbol} ({trade.timeframe}) "
                    f"در قیمت {trade.fill_price:.{digits}f} فعال شد. حد ضرر فعال: {trade.current_sl:.{digits}f}"
                ),
                source_timestamp=candle.timestamp,
            )
            db.add(ev)
            new_events.append(ev)
            _notify_users_for_trade_event(
                db, trade, "TRADE_OPENED", f"فعال‌شدن پوزیشن {trade.symbol}", ev.description_fa, "info"
            )
        else:
            trade.bars_remaining = max(0, trade.bars_remaining - 1)
            if trade.bars_remaining == 0:
                trade.status = "EXPIRED"
                trade.outcome = "CANCELLED"
                trade.closed_at = utcnow()
                ev = TradeEvent(
                    trade_id=trade.id,
                    event_type="EXPIRED",
                    price=candle.close,
                    r_value=0.0,
                    pips_value=0.0,
                    description_fa=f"سفارش لیمیت {trade.trade_code} به دلیل عدم لمس نقطه ورود در بازه اعتبار کندلی منقضی شد.",
                    source_timestamp=candle.timestamp,
                )
                db.add(ev)
                new_events.append(ev)
            db.commit()
            return new_events

    # 2) ACTIVE / TP1_HIT / TP2_HIT state
    entry = trade.fill_price or trade.entry_price
    rem_ratio = trade.remaining_pct / 100.0
    _update_excursions(candle.high, candle.low)

    # Check stop loss first (conservative rule)
    sl_hit = (candle.low <= trade.current_sl) if is_long else (candle.high >= trade.current_sl)
    if sl_hit:
        sl_diff = (trade.current_sl - entry) if is_long else (entry - trade.current_sl)
        sl_r = sl_diff / risk_d
        sl_pips = _calc_pips(trade.symbol, sl_diff)
        sl_usd = _calc_usd(trade.symbol, sl_diff, trade.position_size_lots * rem_ratio, entry)

        trade.realized_r = round(trade.realized_r + rem_ratio * sl_r, 3)
        trade.realized_pips = round(trade.realized_pips + rem_ratio * sl_pips, 1)
        trade.realized_pnl_usd = round(trade.realized_pnl_usd + sl_usd, 2)
        trade.floating_r = 0.0
        trade.floating_pips = 0.0
        trade.floating_pnl_usd = 0.0
        trade.remaining_pct = 0.0
        trade.closed_at = candle.timestamp

        if trade.realized_r > 0.05:
            trade.status = "CLOSED_WIN"
            trade.outcome = "WIN"
            ev_type = "BE_HIT" if trade.tp1_hit and not trade.tp2_hit else "TP1_LOCK_HIT"
            desc = (
                f"باقی‌مانده پوزیشن {trade.symbol} روی استاپ محافظت‌شده ({trade.current_sl:.{digits}f}) بسته شد. "
                f"نتیجه نهایی: سود خالص +{trade.realized_r:.2f}R (+{trade.realized_pnl_usd:.2f}$)."
            )
            sev = "success"
        elif abs(trade.realized_r) <= 0.05:
            trade.status = "CLOSED_BE"
            trade.outcome = "BE"
            ev_type = "BE_HIT"
            desc = f"پوزیشن {trade.symbol} روی نقطه سر‌به‌سر ({trade.current_sl:.{digits}f}) بسته شد (0R)."
            sev = "info"
        else:
            trade.status = "CLOSED_LOSS"
            trade.outcome = "LOSS"
            ev_type = "SL_HIT"
            desc = (
                f"حد ضرر پوزیشن {trade.symbol} در قیمت {trade.current_sl:.{digits}f} فعال شد "
                f"({trade.realized_r:.2f}R | {trade.realized_pnl_usd:.2f}$)."
            )
            sev = "danger"

        ev = TradeEvent(
            trade_id=trade.id,
            event_type=ev_type,
            price=trade.current_sl,
            r_value=trade.realized_r,
            pips_value=trade.realized_pips,
            description_fa=desc,
            source_timestamp=candle.timestamp,
        )
        db.add(ev)
        new_events.append(ev)
        _notify_users_for_trade_event(
            db, trade, "SL_HIT" if trade.outcome == "LOSS" else "TRADE_CLOSED",
            f"بسته‌شدن پوزیشن {trade.symbol}", desc, sev
        )
        db.commit()
        return new_events

    # Check TP1
    if not trade.tp1_hit and ((candle.high >= trade.tp1) if is_long else (candle.low <= trade.tp1)):
        trade.tp1_hit = True
        trade.status = "TP1_HIT"
        take_ratio = min(rem_ratio, trade.tp1_exit_pct / 100.0)
        diff1 = abs(trade.tp1 - entry)
        r1 = diff1 / risk_d
        pips1 = _calc_pips(trade.symbol, diff1)
        usd1 = _calc_usd(trade.symbol, diff1, trade.position_size_lots * take_ratio, entry)

        trade.realized_r = round(trade.realized_r + take_ratio * r1, 3)
        trade.realized_pips = round(trade.realized_pips + take_ratio * pips1, 1)
        trade.realized_pnl_usd = round(trade.realized_pnl_usd + usd1, 2)
        trade.remaining_pct = round(max(0.0, trade.remaining_pct - trade.tp1_exit_pct), 1)
        rem_ratio = trade.remaining_pct / 100.0
        trade.current_sl = entry  # Automatic Move SL to Break-Even!

        ev1 = TradeEvent(
            trade_id=trade.id,
            event_type="TP1_HIT",
            price=trade.tp1,
            r_value=round(r1, 2),
            pips_value=pips1,
            description_fa=(
                f"🎯 تارگت اول (TP1) روی {trade.symbol} در قیمت {trade.tp1:.{digits}f} زده شد (+{pips1:.1f} پیپ / +{r1:.2f}R). "
                f"{trade.tp1_exit_pct:.0f}% حجم با سود بسته شد و حد ضرر به نقطه ورود ({entry:.{digits}f}) ریسک‌فری شد."
            ),
            source_timestamp=candle.timestamp,
        )
        db.add(ev1)
        new_events.append(ev1)
        _notify_users_for_trade_event(
            db, trade, "TP_HIT", f"تارگت ۱ زده شد — {trade.symbol}", ev1.description_fa, "success"
        )

    # Early Break-Even at policy fraction of entry-to-TP1 (default 70%)
    if not trade.tp1_hit and trade.status == "ACTIVE":
        early_be_px = entry + pol.early_be_fraction * (trade.tp1 - entry)
        sl_not_at_be = (trade.current_sl < entry - 1e-9) if is_long else (trade.current_sl > entry + 1e-9)
        reached_early_be = (candle.high >= early_be_px) if is_long else (candle.low <= early_be_px)
        if sl_not_at_be and reached_early_be:
            trade.current_sl = entry
            ev_be = TradeEvent(
                trade_id=trade.id,
                event_type="SL_MOVED_BE",
                price=round(early_be_px, digits),
                r_value=round(pol.early_be_fraction * abs(trade.tp1 - entry) / risk_d, 2),
                pips_value=_calc_pips(trade.symbol, abs(early_be_px - entry)),
                description_fa=(
                    f"🛡️ قیمت روی {trade.symbol} به {pol.early_be_fraction * 100:.0f}٪ مسیر تا TP1 ({early_be_px:.{digits}f}) رسید؛ "
                    f"حد ضرر به‌صورت خودکار به نقطه ورود ({entry:.{digits}f}) منتقل و معامله ریسک‌فری شد."
                ),
                source_timestamp=candle.timestamp,
            )
            db.add(ev_be)
            new_events.append(ev_be)
            _notify_users_for_trade_event(
                db, trade, "SL_MOVED_BE", f"ریسک‌فری خودکار — {trade.symbol}", ev_be.description_fa, "info"
            )

    # Check TP2
    if trade.tp1_hit and not trade.tp2_hit and ((candle.high >= trade.tp2) if is_long else (candle.low <= trade.tp2)):
        trade.tp2_hit = True
        trade.status = "TP2_HIT"
        take_ratio = min(rem_ratio, trade.tp2_exit_pct / 100.0)
        diff2 = abs(trade.tp2 - entry)
        r2 = diff2 / risk_d
        pips2 = _calc_pips(trade.symbol, diff2)
        usd2 = _calc_usd(trade.symbol, diff2, trade.position_size_lots * take_ratio, entry)

        trade.realized_r = round(trade.realized_r + take_ratio * r2, 3)
        trade.realized_pips = round(trade.realized_pips + take_ratio * pips2, 1)
        trade.realized_pnl_usd = round(trade.realized_pnl_usd + usd2, 2)
        trade.remaining_pct = round(max(0.0, trade.remaining_pct - trade.tp2_exit_pct), 1)
        rem_ratio = trade.remaining_pct / 100.0
        trade.current_sl = trade.tp1  # Automatic Move SL to TP1!

        ev2 = TradeEvent(
            trade_id=trade.id,
            event_type="TP2_HIT",
            price=trade.tp2,
            r_value=round(r2, 2),
            pips_value=pips2,
            description_fa=(
                f"🎯🎯 تارگت دوم (TP2) روی {trade.symbol} در قیمت {trade.tp2:.{digits}f} زده شد (+{pips2:.1f} پیپ / +{r2:.2f}R). "
                f"{trade.tp2_exit_pct:.0f}% دیگر بسته شد و حد ضرر برای قفل سود روی TP1 ({trade.tp1:.{digits}f}) قرار گرفت."
            ),
            source_timestamp=candle.timestamp,
        )
        db.add(ev2)
        new_events.append(ev2)
        _notify_users_for_trade_event(
            db, trade, "TP_HIT", f"تارگت ۲ زده شد — {trade.symbol}", ev2.description_fa, "success"
        )

    # Check TP3 (full target)
    if trade.tp2_hit and not trade.tp3_hit and ((candle.high >= trade.tp3) if is_long else (candle.low <= trade.tp3)):
        trade.tp3_hit = True
        diff3 = abs(trade.tp3 - entry)
        r3 = diff3 / risk_d
        pips3 = _calc_pips(trade.symbol, diff3)
        usd3 = _calc_usd(trade.symbol, diff3, trade.position_size_lots * rem_ratio, entry)

        trade.realized_r = round(trade.realized_r + rem_ratio * r3, 3)
        trade.realized_pips = round(trade.realized_pips + rem_ratio * pips3, 1)
        trade.realized_pnl_usd = round(trade.realized_pnl_usd + usd3, 2)
        trade.remaining_pct = 0.0
        trade.floating_r = 0.0
        trade.floating_pips = 0.0
        trade.floating_pnl_usd = 0.0
        trade.progress_to_tp1_pct = 100.0
        trade.status = "CLOSED_WIN"
        trade.outcome = "WIN"
        trade.closed_at = candle.timestamp

        ev3 = TradeEvent(
            trade_id=trade.id,
            event_type="TP3_HIT",
            price=trade.tp3,
            r_value=trade.realized_r,
            pips_value=trade.realized_pips,
            description_fa=(
                f"🏆 فول تارگت (TP3) روی {trade.symbol} در قیمت {trade.tp3:.{digits}f} زده شد! "
                f"سود کل پوزیشن: +{trade.realized_r:.2f}R (+{trade.realized_pnl_usd:.2f}$)."
            ),
            source_timestamp=candle.timestamp,
        )
        db.add(ev3)
        new_events.append(ev3)
        _notify_users_for_trade_event(
            db, trade, "TP_HIT", f"فول تارگت TP3 — {trade.symbol}", ev3.description_fa, "success"
        )
        db.commit()
        return new_events

    # Update live floating PnL & progress
    cur_diff = (candle.close - entry) if is_long else (entry - candle.close)
    trade.floating_r = round((cur_diff / risk_d) * rem_ratio, 3)
    trade.floating_pips = _calc_pips(trade.symbol, cur_diff)
    trade.floating_pnl_usd = _calc_usd(trade.symbol, cur_diff, trade.position_size_lots * rem_ratio, entry)

    next_target = trade.tp1 if not trade.tp1_hit else (trade.tp2 if not trade.tp2_hit else trade.tp3)
    target_span = abs(next_target - entry)
    if target_span > 0:
        prog = (cur_diff / target_span) * 100.0
        trade.progress_to_tp1_pct = round(max(0.0, min(100.0, prog)), 1)

    db.commit()
    return new_events
