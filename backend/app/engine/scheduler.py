from __future__ import annotations

import asyncio
from datetime import timedelta, timezone
import hashlib
import json
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import ALLOWED_SYMBOLS, ALLOWED_TIMEFRAMES, SYMBOL_META, TIMEFRAME_META, get_settings
from app.database import SessionLocal
from app.engine.backtester import (
    build_params_for_timeframe,
    evaluate_pair_backtest,
    refresh_all_qualifications,
)
from app.engine.policy import (
    CONSECUTIVE_LOSS_PAUSE,
    CONSECUTIVE_LOSS_PAUSE_HOURS,
    MAX_CONCURRENT_PER_SYMBOL,
    MAX_CONCURRENT_TRADES,
    TRADING_POLICY_VERSION,
    get_policy,
)
from app.engine.market_data import get_market_series
from app.engine.position_tracker import track_open_trade_with_candle
from app.engine.trading_hub3 import TradeSetupSignal, run_trading_hub3_engine
from app.models import (
    BacktestQualification,
    EngineConfig,
    NewsItem,
    Notification,
    SignalTrade,
    TradeEvent,
    User,
    utcnow,
)
from app.security import hash_password
from app.services.news_engine import fetch_and_ingest_news, is_news_blackout_for_symbol
from app.services.realtime import realtime_hub
from app.services.telegram_bot import (
    publish_high_impact_news_to_telegram,
    publish_position_update_reply,
    publish_signal_to_telegram,
)


def _reset_config_to_policy_defaults(cfg: EngineConfig) -> None:
    """Bring a stale EngineConfig row in line with the current hard policy."""
    bases = {tf: get_policy(tf) for tf in ALLOWED_TIMEFRAMES}
    cfg.policy_version = TRADING_POLICY_VERSION
    # The stored ladder mirrors the 15m profile (the reference intraday profile);
    # every timeframe still applies its own policy at scan time.
    ref = bases["15m"]
    cfg.tp1_rr = ref.tp1_rr
    cfg.tp2_rr = ref.tp2_rr
    cfg.tp3_rr = ref.tp3_rr
    cfg.tp1_exit_pct = ref.tp1_exit_pct
    cfg.tp2_exit_pct = ref.tp2_exit_pct
    cfg.min_score_4h = bases["4H"].min_score
    cfg.min_score_15m = bases["15m"].min_score
    cfg.min_score_5m = bases["5m"].min_score
    cfg.min_adx = bases["15m"].min_adx
    cfg.use_session_filter = True
    cfg.require_sweep = True
    cfg.require_idm = True
    cfg.require_strong_choch_body = True
    cfg.use_pd_filter = True
    cfg.skip_dead_volatility = True
    cfg.skip_news_spikes = True
    cfg.min_backtest_winrate = 55.0
    cfg.min_backtest_pf = 1.5
    cfg.min_backtest_trades = 8


def get_or_create_engine_config(db: Session) -> EngineConfig:
    cfg = db.query(EngineConfig).filter(EngineConfig.id == 1).first()
    if not cfg:
        cfg = EngineConfig(id=1)
        _reset_config_to_policy_defaults(cfg)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    elif (cfg.policy_version or "") != TRADING_POLICY_VERSION:
        # Legacy / stale configuration: migrate it instead of silently letting an
        # outdated target ladder (e.g. 1.2R TP1) break the expectancy of the model.
        _reset_config_to_policy_defaults(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def ensure_initial_admin(db: Session) -> User:
    settings = get_settings()
    admin = db.query(User).filter(User.email == settings.initial_admin_email.lower()).first()
    if not admin:
        admin = User(
            email=settings.initial_admin_email.lower(),
            full_name="مدیر سیستم NEXVORA",
            password_hash=hash_password(settings.initial_admin_password),
            role="SUPER_ADMIN",
            is_active=True,
            mfa_enabled=False,
            timezone_pref="Asia/Tehran",
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
    return admin


def _open_trades(db: Session) -> List[SignalTrade]:
    return (
        db.query(SignalTrade)
        .filter(SignalTrade.status.in_(["PENDING_LIMIT", "ACTIVE", "TP1_HIT", "TP2_HIT"]))
        .all()
    )


def _portfolio_guard_reason(db: Session, symbol: str, direction: str, cfg: EngineConfig) -> Optional[str]:
    """Portfolio-level risk gates that must hold before any new signal is accepted."""
    open_trades = _open_trades(db)

    # 1) hard cap of concurrent positions
    if len(open_trades) >= MAX_CONCURRENT_TRADES:
        return f"سقف پوزیشن‌های هم‌زمان ({MAX_CONCURRENT_TRADES}) پر است."

    # 2) no pyramiding on the same symbol
    same_symbol = [t for t in open_trades if t.symbol == symbol]
    if len(same_symbol) >= MAX_CONCURRENT_PER_SYMBOL:
        return f"پوزیشن باز روی {symbol} وجود دارد (بدون هرم‌سازی)."

    # 3) correlation guard
    if cfg.correlation_guard and _has_open_correlated_trade(db, symbol, direction):
        return "همبستگی ارزی: پوزیشن هم‌جهت روی جفت‌ارز مرتبط باز است."

    # 4) losing streak pause per (symbol, timeframe) is handled by caller
    return None


def _is_cell_paused(db: Session, symbol: str, timeframe: str) -> bool:
    """Pause a symbol/timeframe cell after N consecutive losses."""
    closed = (
        db.query(SignalTrade)
        .filter(
            SignalTrade.symbol == symbol,
            SignalTrade.timeframe == timeframe,
            SignalTrade.outcome.in_(["WIN", "LOSS", "BE"]),
        )
        .order_by(SignalTrade.closed_at.desc())
        .limit(CONSECUTIVE_LOSS_PAUSE)
        .all()
    )
    if len(closed) < CONSECUTIVE_LOSS_PAUSE:
        return False
    if not all(t.outcome == "LOSS" for t in closed):
        return False
    newest = closed[0].closed_at or closed[0].updated_at
    if newest is None:
        return False
    newest = newest if newest.tzinfo else newest.replace(tzinfo=timezone.utc)
    return (utcnow() - newest) < timedelta(hours=CONSECUTIVE_LOSS_PAUSE_HOURS)


def _has_open_correlated_trade(db: Session, symbol: str, direction: str) -> bool:
    corr_group = SYMBOL_META[symbol]["corr_group"]
    for t in _open_trades(db):
        if t.symbol == symbol:
            return True
        if SYMBOL_META[t.symbol]["corr_group"] == corr_group and t.direction == direction:
            return True
    return False


def _create_trade_from_signal(
    db: Session,
    sig: TradeSetupSignal,
    qual: Optional[BacktestQualification],
    data_source: str,
    is_demo_data: bool,
    current_price: float,
    cfg: EngineConfig,
    publish_telegram: bool = True,
) -> Optional[SignalTrade]:
    idem_raw = f"{sig.symbol}:{sig.timeframe}:{sig.direction}:{sig.timestamp.isoformat()}:{sig.entry_price}"
    idem_key = hashlib.sha256(idem_raw.encode("utf-8")).hexdigest()[:48]
    if db.query(SignalTrade).filter(SignalTrade.idempotency_key == idem_key).first():
        return None

    count_existing = db.query(SignalTrade).count()
    trade_code = f"NXV-{sig.symbol}-{sig.timeframe}-{count_existing + 1:04d}"
    # Fail-closed publication gate:
    #   * only cells with a *statistically valid* positive-edge backtest may be
    #     published, and
    #   * replay/demo candles are NEVER pushed to the public channel.
    qual_ok = bool(qual.eligible_for_telegram) if qual else False
    if qual is not None and (qual.total_trades or 0) < 8:
        qual_ok = False
    eligible = qual_ok and not is_demo_data
    bt_wr = float(qual.win_rate) if qual else 0.0
    bt_pf = float(qual.profit_factor) if qual else 0.0

    trade = SignalTrade(
        trade_code=trade_code,
        idempotency_key=idem_key,
        symbol=sig.symbol,
        market_class=SYMBOL_META[sig.symbol]["market_class"],
        timeframe=sig.timeframe,
        risk_tier=sig.risk_tier,
        direction=sig.direction,
        strategy_name="Trading Hub 3.0 — High Accuracy",
        entry_module=sig.entry_module,
        htf_bias=sig.htf_bias,
        session_name=sig.session_name,
        status="PENDING_LIMIT",
        outcome="OPEN",
        entry_price=sig.entry_price,
        current_price=current_price,
        initial_sl=sig.sl,
        current_sl=sig.sl,
        tp1=sig.tp1,
        tp2=sig.tp2,
        tp3=sig.tp3,
        tp1_exit_pct=sig.tp1_exit_pct,
        tp2_exit_pct=sig.tp2_exit_pct,
        tp3_exit_pct=sig.tp3_exit_pct,
        remaining_pct=100.0,
        risk_pct=1.0,
        position_size_lots=sig.position_size_lots,
        confluence_score=sig.confluence_score,
        grade=sig.grade,
        checklist_json=json.dumps(sig.checklist, ensure_ascii=False),
        rationale_fa=sig.rationale_fa,
        backtest_win_rate_at_entry=bt_wr,
        backtest_profit_factor_at_entry=bt_pf,
        eligible_for_telegram=eligible,
        data_source=data_source,
        is_demo_data=is_demo_data,
        bars_remaining=sig.bars_valid,
        risk_pips=sig.risk_pips,
        risk_atr=sig.risk_atr,
        early_be_price=sig.early_be_price,
        policy_version=TRADING_POLICY_VERSION,
        pending_expires_at=sig.timestamp + timedelta(hours=sig.pending_expiry_hours),
        created_at=sig.timestamp,
    )
    db.add(trade)
    db.flush()

    ev = TradeEvent(
        trade_id=trade.id,
        event_type="SIGNAL_CREATED",
        price=sig.entry_price,
        r_value=0.0,
        pips_value=0.0,
        description_fa=(
            f"سیگنال جدید {sig.direction} ({sig.entry_module}) روی {sig.symbol} ({TIMEFRAME_META[sig.timeframe]['label_fa']}) "
            f"با امتیاز {sig.confluence_score:.1f}/10 ثبت شد. "
            + (
                "مجاز برای کانال تلگرام (وین‌ریت و Profit Factor بک‌تست تأیید شده)."
                if eligible
                else (
                    "فقط پایش در PWA — داده بازپخش آزمایشی هرگز به کانال تلگرام ارسال نمی‌شود."
                    if is_demo_data
                    else f"فقط پایش در PWA — این ترکیب هنوز تأییدیه آماری کانال را نگرفته است "
                         f"(وین‌ریت {bt_wr:.1f}% / PF {bt_pf:.2f} / {qual.total_trades if qual else 0} معامله)."
                )
            )
        ),
        source_timestamp=sig.timestamp,
    )
    db.add(ev)

    # In-app notification for active users
    users = db.query(User).filter(User.is_active == True, User.notify_signals == True).all()  # noqa: E712
    for u in users:
        db.add(
            Notification(
                user_id=u.id,
                kind="NEW_SIGNAL",
                title_fa=f"سیگنال جدید {sig.direction} — {SYMBOL_META[sig.symbol]['display']} ({sig.timeframe})",
                message_fa=f"ماژول {sig.entry_module} | امتیاز {sig.confluence_score:.1f}/10 ({sig.grade}) | ورود: {sig.entry_price}",
                severity="success" if eligible else "info",
                related_trade_id=trade.id,
            )
        )

    db.commit()
    db.refresh(trade)

    if publish_telegram and eligible and cfg.telegram_send_signals:
        publish_signal_to_telegram(db, trade)

    return trade


def run_engine_scan_cycle(db: Session) -> Dict[str, int]:
    """
    Runs a full scan across the 6 allowed symbols x 3 timeframes:
    1. Checks High Accuracy Trading Hub 3.0 setups
    2. Enforces News Blackout Guard & Correlation Guard
    3. Verifies Backtest Win-Rate Qualification before Telegram publishing
    4. Tracks all open positions with latest candles and sends Telegram reply updates
    """
    cfg = get_or_create_engine_config(db)
    created_count = 0
    tracking_events_count = 0
    skipped: List[dict] = []

    # Ensure qualifications exist
    quals = {
        (q.symbol, q.timeframe): q
        for q in db.query(BacktestQualification).all()
    }
    if not quals:
        for q in refresh_all_qualifications(db, cfg):
            quals[(q.symbol, q.timeframe)] = q

    for sym in ALLOWED_SYMBOLS:
        blackout = is_news_blackout_for_symbol(db, sym, cfg.news_blackout_minutes)
        for tf in ALLOWED_TIMEFRAMES:
            tf_meta = TIMEFRAME_META[tf]
            series = get_market_series(sym, tf, limit=600, db=db)
            htf1 = get_market_series(sym, tf_meta["htf_primary"], limit=300, db=db)
            htf2 = (
                get_market_series(sym, tf_meta["htf_secondary"], limit=300, db=db)
                if tf_meta["htf_secondary"] != tf_meta["htf_primary"]
                else htf1
            )

            # 1) Track existing open trades on (sym, tf) with latest closed candle
            open_trades = (
                db.query(SignalTrade)
                .filter(
                    SignalTrade.symbol == sym,
                    SignalTrade.timeframe == tf,
                    SignalTrade.status.in_(["PENDING_LIMIT", "ACTIVE", "TP1_HIT", "TP2_HIT"]),
                )
                .all()
            )
            latest_candle = series.candles[-1]
            for ot in open_trades:
                evs = track_open_trade_with_candle(db, ot, latest_candle)
                tracking_events_count += len(evs)
                for ev in evs:
                    if cfg.telegram_send_tracking and ot.telegram_message_id:
                        publish_position_update_reply(db, ot, ev)

            # 2) Scan for new confirmed Trading Hub 3.0 signal
            ev_res = run_trading_hub3_engine(
                symbol=sym,
                timeframe=tf,
                candles=series.candles,
                params=build_params_for_timeframe(cfg, tf),
                htf1_candles=htf1.candles,
                htf2_candles=htf2.candles,
                news_blackout_active=blackout,
            )
            if ev_res.latest_signal is not None:
                sig = ev_res.latest_signal
                guard = _portfolio_guard_reason(db, sym, sig.direction, cfg)
                if guard is None and _is_cell_paused(db, sym, tf):
                    guard = (
                        f"{CONSECUTIVE_LOSS_PAUSE} ضرر متوالی روی این ترکیب؛ "
                        f"{CONSECUTIVE_LOSS_PAUSE_HOURS} ساعت توقف."
                    )
                if guard is not None:
                    skipped.append({"symbol": sym, "timeframe": tf, "reason_fa": guard})
                    continue
                qual = quals.get((sym, tf))
                created = _create_trade_from_signal(
                    db=db,
                    sig=sig,
                    qual=qual,
                    data_source=series.source,
                    is_demo_data=series.is_demo_data,
                    current_price=latest_candle.close,
                    cfg=cfg,
                    publish_telegram=True,
                )
                if created:
                    created_count += 1

    return {
        "signals_created": created_count,
        "tracking_events": tracking_events_count,
        "guard_skips": skipped,
        "policy_version": TRADING_POLICY_VERSION,
    }


def bootstrap_initial_engine_data(db: Session) -> None:
    """
    On first boot with an empty trade ledger, runs the real Trading Hub 3.0 engine & backtester
    across the 6 allowed symbols x 3 timeframes, materializing genuine historical closed trades
    and current active positions (with exact `is_demo_data` provenance flag) so the PWA and
    analytics reflect authentic engine execution immediately without any fabricated numbers.
    """
    ensure_initial_admin(db)
    cfg = get_or_create_engine_config(db)

    # 1. Run backtest qualification across all 6 symbols x 3 timeframes
    qual_map: Dict[tuple[str, str], BacktestQualification] = {}
    try:
        quals = refresh_all_qualifications(db, cfg)
        qual_map = {(q.symbol, q.timeframe): q for q in quals}
        print(
            f"[NEXVORA] bootstrap step 1/3: backtest qualifications={len(quals)} "
            f"(eligible={sum(1 for q in quals if q.eligible_for_telegram)})",
            flush=True,
        )
    except Exception as exc:
        db.rollback()
        print(f"[NEXVORA] bootstrap step 1/3 error: {exc}", flush=True)

    # 2. Materialize recent (<= 7 days) genuine Trading Hub 3.0 signals from qualified cells only
    created_trades = 0
    recent_cutoff = utcnow() - timedelta(days=7)
    if db.query(SignalTrade).count() == 0:
        for sym in ALLOWED_SYMBOLS:
            for tf in ALLOWED_TIMEFRAMES:
                try:
                    qual = qual_map.get((sym, tf))
                    tf_meta = TIMEFRAME_META[tf]
                    series = get_market_series(sym, tf, limit=600, db=db)
                    htf1 = get_market_series(sym, tf_meta["htf_primary"], limit=300, db=db)
                    htf2 = (
                        get_market_series(sym, tf_meta["htf_secondary"], limit=300, db=db)
                        if tf_meta["htf_secondary"] != tf_meta["htf_primary"]
                        else htf1
                    )
                    eval_res = run_trading_hub3_engine(
                        symbol=sym,
                        timeframe=tf,
                        candles=series.candles,
                        params=build_params_for_timeframe(cfg, tf),
                        htf1_candles=htf1.candles,
                        htf2_candles=htf2.candles,
                    )
                    # Materialize the most recent genuine setups of each cell so the
                    # PWA shows a real (honestly timestamped) track record on first
                    # boot. Signals older than the feed window stay in history only.
                    picked: List[TradeSetupSignal] = []
                    for s in eval_res.historical_signals[-6:]:
                        if picked and s.bar_idx - picked[-1].bar_idx < 18:
                            continue
                        picked.append(s)

                    for sig in picked[-3:]:
                        trade = _create_trade_from_signal(
                            db=db,
                            sig=sig,
                            qual=qual,
                            data_source=series.source,
                            is_demo_data=series.is_demo_data,
                            current_price=float(series.candles[sig.bar_idx].close),
                            cfg=cfg,
                            publish_telegram=False,
                        )
                        if not trade:
                            continue
                        created_trades += 1
                        # Replay subsequent candles through the real Position Tracker!
                        for future_c in series.candles[sig.bar_idx + 1 :]:
                            track_open_trade_with_candle(db, trade, future_c)
                            if trade.status in ("CLOSED_WIN", "CLOSED_LOSS", "CLOSED_BE", "EXPIRED", "CANCELLED"):
                                break

                        # If this trade is still active and eligible, register its Telegram publication
                        if trade.status in ("PENDING_LIMIT", "ACTIVE", "TP1_HIT", "TP2_HIT") and trade.eligible_for_telegram and cfg.telegram_send_signals:
                            publish_signal_to_telegram(db, trade)
                except Exception as exc:
                    db.rollback()
                    print(f"[NEXVORA] bootstrap trade error for {sym} {tf}: {exc}", flush=True)
        print(f"[NEXVORA] bootstrap step 2/3: materialized trades={created_trades}", flush=True)

    # 3. Ingest multi-source Persian news & economic calendar
    try:
        news_items = fetch_and_ingest_news(db)
        print(f"[NEXVORA] bootstrap step 3/3: news ingested={len(news_items)}", flush=True)
        if cfg.telegram_send_high_news:
            for ni in news_items:
                if not ni.telegram_sent and ni.market_impact_pct >= cfg.telegram_min_news_impact_pct:
                    publish_high_impact_news_to_telegram(db, ni)
    except Exception as exc:
        db.rollback()
        print(f"[NEXVORA] bootstrap step 3/3 news error: {exc}", flush=True)


def _background_tick_sync(tick: int) -> dict:
    """Execute synchronous DB/HTTP scan work in a worker thread so FastAPI event loop stays responsive."""
    out = {"engine": None, "news_count": 0, "backtest_refreshed": False}
    db = SessionLocal()
    try:
        summary = run_engine_scan_cycle(db)
        if summary["signals_created"] > 0 or summary["tracking_events"] > 0:
            out["engine"] = summary

        # Refresh news every ~5 ticks
        if tick % 5 == 0:
            cfg = get_or_create_engine_config(db)
            new_news = fetch_and_ingest_news(db)
            if new_news and cfg.telegram_send_high_news:
                for ni in new_news:
                    if not ni.telegram_sent and ni.market_impact_pct >= cfg.telegram_min_news_impact_pct:
                        publish_high_impact_news_to_telegram(db, ni)
            out["news_count"] = len(new_news)

        # Refresh backtest qualification every ~30 ticks
        if tick % 30 == 0:
            cfg = get_or_create_engine_config(db)
            refresh_all_qualifications(db, cfg)
            out["backtest_refreshed"] = True
    finally:
        db.close()
    return out


async def background_engine_loop(
    stop_event: asyncio.Event,
    bootstrap_done: Optional[asyncio.Event] = None,
) -> None:
    """Periodic async worker for position tracking, signal scanning, and news updates."""
    settings = get_settings()
    if bootstrap_done is not None:
        # Wait until initial bootstrap finishes so SQLite/Postgres never faces concurrent startup writes
        while not bootstrap_done.is_set() and not stop_event.is_set():
            try:
                await asyncio.wait_for(bootstrap_done.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
    tick = 0
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(15, settings.position_track_interval_sec))
            break
        except asyncio.TimeoutError:
            pass

        tick += 1
        try:
            res = await asyncio.to_thread(_background_tick_sync, tick)
            if res["engine"]:
                await realtime_hub.broadcast_public("engine_update", res["engine"])
            if res["news_count"]:
                await realtime_hub.broadcast_public("news_update", {"count": res["news_count"]})
            if res["backtest_refreshed"]:
                await realtime_hub.broadcast_public("backtest_update", {"refreshed_at": utcnow().isoformat()})
        except Exception:
            pass
