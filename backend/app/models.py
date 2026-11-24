from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="USER", nullable=False)  # USER, PREMIUM, ADMIN, SUPER_ADMIN
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    timezone_pref: Mapped[str] = mapped_column(String(64), default="Asia/Tehran", nullable=False)
    quiet_hours_start: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # e.g. "23:00"
    quiet_hours_end: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)    # e.g. "07:00"
    notify_signals: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_tracking: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_high_news: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    user_agent: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="sessions")


class SignalTrade(Base):
    __tablename__ = "signal_trades"
    __table_args__ = (
        Index("ix_signal_trades_sym_tf_status", "symbol", "timeframe", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)

    symbol: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    market_class: Mapped[str] = mapped_column(String(16), default="FOREX", nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), index=True, nullable=False)  # 4H, 15m, 5m
    risk_tier: Mapped[str] = mapped_column(String(20), nullable=False)  # SAFE, MEDIUM_RISK, HIGH_RISK
    direction: Mapped[str] = mapped_column(String(8), nullable=False)   # LONG, SHORT

    strategy_name: Mapped[str] = mapped_column(String(64), default="Trading Hub 3.0 — High Accuracy", nullable=False)
    entry_module: Mapped[str] = mapped_column(String(32), nullable=False)  # CHoCH, SWEEP, FLIP, OB, FVG
    htf_bias: Mapped[str] = mapped_column(String(16), default="NEUTRAL", nullable=False)
    session_name: Mapped[str] = mapped_column(String(24), default="LONDON", nullable=False)

    # Lifecycle status: PENDING_LIMIT -> ACTIVE -> TP1_HIT -> TP2_HIT -> CLOSED_WIN / CLOSED_LOSS / CLOSED_BE / EXPIRED / CANCELLED
    status: Mapped[str] = mapped_column(String(24), index=True, default="PENDING_LIMIT", nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), index=True, default="OPEN", nullable=False)  # OPEN, WIN, LOSS, BE, CANCELLED

    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    fill_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_price: Mapped[float] = mapped_column(Float, nullable=False)
    initial_sl: Mapped[float] = mapped_column(Float, nullable=False)
    current_sl: Mapped[float] = mapped_column(Float, nullable=False)
    tp1: Mapped[float] = mapped_column(Float, nullable=False)
    tp2: Mapped[float] = mapped_column(Float, nullable=False)
    tp3: Mapped[float] = mapped_column(Float, nullable=False)

    tp1_exit_pct: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    tp2_exit_pct: Mapped[float] = mapped_column(Float, default=30.0, nullable=False)
    tp3_exit_pct: Mapped[float] = mapped_column(Float, default=20.0, nullable=False)
    remaining_pct: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)

    tp1_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tp2_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tp3_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    risk_pct: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    position_size_lots: Mapped[float] = mapped_column(Float, default=0.1, nullable=False)
    confluence_score: Mapped[float] = mapped_column(Float, nullable=False)
    grade: Mapped[str] = mapped_column(String(8), default="A", nullable=False)
    checklist_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    rationale_fa: Mapped[str] = mapped_column(Text, default="", nullable=False)

    realized_r: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    floating_r: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    realized_pips: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    floating_pips: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    realized_pnl_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    floating_pnl_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    fees_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    progress_to_tp1_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    backtest_win_rate_at_entry: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    backtest_profit_factor_at_entry: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    eligible_for_telegram: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    telegram_message_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    data_source: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    is_demo_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    bars_remaining: Mapped[int] = mapped_column(Integer, default=20, nullable=False)

    # Risk geometry captured at signal time (needed for honest R tracking & audit)
    risk_pips: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    risk_atr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    early_be_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), default="", nullable=False)

    # Best / worst excursion in R (position tracking quality feedback)
    max_favorable_r: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    max_adverse_r: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Hard expiry of an unfilled limit order
    pending_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    events: Mapped[list["TradeEvent"]] = relationship(
        back_populates="trade",
        cascade="all, delete-orphan",
        order_by="TradeEvent.created_at",
    )


class TradeEvent(Base):
    __tablename__ = "trade_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("signal_trades.id", ondelete="CASCADE"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    r_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pips_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    description_fa: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_reply_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    trade: Mapped["SignalTrade"] = relationship(back_populates="events")


class UserTradeJournal(Base):
    """Per-user private trade journal & watchlist — strictly isolated per user_id."""
    __tablename__ = "user_trade_journals"
    __table_args__ = (
        UniqueConstraint("user_id", "trade_id", name="uq_user_trade_journal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    trade_id: Mapped[int] = mapped_column(ForeignKey("signal_trades.id", ondelete="CASCADE"), index=True, nullable=False)
    is_following: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    personal_risk_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class BacktestQualification(Base):
    """Rolling backtest win-rate filter per (symbol, timeframe) for Telegram publishing gate."""
    __tablename__ = "backtest_qualifications"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", name="uq_backtest_sym_tf"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(20), nullable=False)
    eligible_for_telegram: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason_fa: Mapped[str] = mapped_column(Text, default="", nullable=False)

    total_trades: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    winning_trades: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losing_trades: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    breakeven_trades: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    profit_factor: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    expectancy_r: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_r: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_hold_bars: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # 1..N when this cell is one of the published channel cells, 0 otherwise.
    channel_rank: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    window_bars: Mapped[int] = mapped_column(Integer, default=500, nullable=False)

    data_source: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    is_demo_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedupe_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    source_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), default="publisher", nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(512), nullable=False)

    original_headline: Mapped[str] = mapped_column(Text, nullable=False)
    persian_title: Mapped[str] = mapped_column(Text, nullable=False)
    persian_summary: Mapped[str] = mapped_column(Text, nullable=False)
    summary_is_ai: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    category: Mapped[str] = mapped_column(String(32), index=True, default="macro", nullable=False)
    related_currencies_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    related_symbols_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    # 5 independent intelligence scores + unified Market Impact %
    impact_level: Mapped[str] = mapped_column(String(16), index=True, default="MEDIUM", nullable=False)
    market_impact_pct: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    importance_score: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    volatility_score: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    currency_relevance_score: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    direction_bias: Mapped[str] = mapped_column(String(32), default="INSUFFICIENT_EVIDENCE", nullable=False)
    direction_confidence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_trade_risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    methodology_note_fa: Mapped[str] = mapped_column(Text, default="", nullable=False)

    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    telegram_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_demo_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class EconomicEvent(Base):
    __tablename__ = "economic_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    event_name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    event_name_fa: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    related_symbols_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="macro", nullable=False)
    importance: Mapped[str] = mapped_column(String(16), index=True, default="HIGH", nullable=False)
    impact_pct: Mapped[int] = mapped_column(Integer, default=80, nullable=False)

    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(32), default="UTC", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="SCHEDULED", nullable=False)  # SCHEDULED, PUBLISHED, REVISED

    actual: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    forecast: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    previous: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    revision: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    surprise_note_fa: Mapped[str] = mapped_column(Text, default="", nullable=False)

    source_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    is_demo_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(200), nullable=False)
    message_fa: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    related_trade_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    related_news_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class EngineConfig(Base):
    """Singleton server-side configuration for Trading Hub 3.0 High Accuracy filters & Telegram."""
    __tablename__ = "engine_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    preset_name: Mapped[str] = mapped_column(String(32), default="HIGH_ACCURACY", nullable=False)
    # Version of the trading policy these values were produced for. When the
    # hard-coded policy is upgraded the scheduler resets stale rows.
    policy_version: Mapped[str] = mapped_column(String(40), default="", nullable=False)

    # Target ladder expressed in R multiples of the *structural* risk distance.
    # The unsuffixed columns are the historical 15m profile and stay the default
    # for anything that only knows one ladder; each timeframe has its own
    # explicit ladder below so the 4H "safe" profile can never be flattened into
    # the 15m profile by a single admin row.
    tp1_rr: Mapped[float] = mapped_column(Float, default=1.2, nullable=False)
    tp2_rr: Mapped[float] = mapped_column(Float, default=2.2, nullable=False)
    tp3_rr: Mapped[float] = mapped_column(Float, default=3.4, nullable=False)
    tp1_exit_pct: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    tp2_exit_pct: Mapped[float] = mapped_column(Float, default=30.0, nullable=False)

    tp1_rr_4h: Mapped[float] = mapped_column(Float, default=1.3, nullable=False)
    tp2_rr_4h: Mapped[float] = mapped_column(Float, default=2.4, nullable=False)
    tp3_rr_4h: Mapped[float] = mapped_column(Float, default=3.6, nullable=False)
    tp1_exit_pct_4h: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    tp2_exit_pct_4h: Mapped[float] = mapped_column(Float, default=30.0, nullable=False)

    tp1_rr_5m: Mapped[float] = mapped_column(Float, default=1.1, nullable=False)
    tp2_rr_5m: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)
    tp3_rr_5m: Mapped[float] = mapped_column(Float, default=3.0, nullable=False)
    tp1_exit_pct_5m: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    tp2_exit_pct_5m: Mapped[float] = mapped_column(Float, default=30.0, nullable=False)

    # Strict quality filters (derived from hub3.txt + dis.zip High Accuracy)
    min_score_4h: Mapped[float] = mapped_column(Float, default=8.0, nullable=False)
    min_score_15m: Mapped[float] = mapped_column(Float, default=8.5, nullable=False)
    min_score_5m: Mapped[float] = mapped_column(Float, default=9.0, nullable=False)
    min_adx: Mapped[float] = mapped_column(Float, default=22.0, nullable=False)
    trend_ema_len: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    require_sweep: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    require_idm: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    require_strong_choch_body: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    use_pd_filter: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    use_session_filter: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    skip_dead_volatility: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    skip_news_spikes: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    news_blackout_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    correlation_guard: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Rolling Backtest Win-Rate Qualification Gate (Target >= 70% Win Rate)
    min_backtest_winrate: Mapped[float] = mapped_column(Float, default=55.0, nullable=False)
    min_backtest_pf: Mapped[float] = mapped_column(Float, default=1.5, nullable=False)
    min_backtest_trades: Mapped[int] = mapped_column(Integer, default=8, nullable=False)

    # Telegram routing flags
    telegram_send_signals: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    telegram_send_tracking: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    telegram_send_high_news: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    telegram_min_news_impact_pct: Mapped[int] = mapped_column(Integer, default=75, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class SourceHealth(Base):
    __tablename__ = "source_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="UNKNOWN", nullable=False)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_msg: Mapped[str] = mapped_column(Text, default="", nullable=False)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    requests_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rate_limit_note: Mapped[str] = mapped_column(String(200), default="", nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    actor_email: Mapped[str] = mapped_column(String(255), default="system", nullable=False)
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), default="SUCCESS", nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)
