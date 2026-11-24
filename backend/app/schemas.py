from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


EMAIL_PATTERN = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"


# -------------------- Auth & Users --------------------

class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255, pattern=EMAIL_PATTERN)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=1, max_length=128)
    mfa_code: Optional[str] = Field(default=None, max_length=10)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    timezone_pref: Optional[str] = Field(default=None, max_length=64)
    quiet_hours_start: Optional[str] = Field(default=None, max_length=5)
    quiet_hours_end: Optional[str] = Field(default=None, max_length=5)
    notify_signals: Optional[bool] = None
    notify_tracking: Optional[bool] = None
    notify_high_news: Optional[bool] = None


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    mfa_enabled: bool
    timezone_pref: str
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    notify_signals: bool
    notify_tracking: bool
    notify_high_news: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    user: UserOut
    csrf_token: str


class SessionOut(BaseModel):
    id: int
    ip_address: str
    user_agent: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    is_current: bool = False


# -------------------- Trades & Signals --------------------

class TradeEventOut(BaseModel):
    id: int
    trade_id: int
    event_type: str
    price: Optional[float]
    r_value: Optional[float]
    pips_value: Optional[float]
    description_fa: str
    telegram_reply_id: Optional[str]
    source_timestamp: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class SignalTradeOut(BaseModel):
    id: int
    trade_code: str
    symbol: str
    market_class: str
    timeframe: str
    risk_tier: str
    direction: str
    strategy_name: str
    entry_module: str
    htf_bias: str
    session_name: str
    status: str
    outcome: str
    entry_price: float
    fill_price: Optional[float]
    current_price: float
    initial_sl: float
    current_sl: float
    tp1: float
    tp2: float
    tp3: float
    tp1_exit_pct: float
    tp2_exit_pct: float
    tp3_exit_pct: float
    remaining_pct: float
    tp1_hit: bool
    tp2_hit: bool
    tp3_hit: bool
    risk_pct: float
    position_size_lots: float
    confluence_score: float
    grade: str
    checklist: List[dict] = Field(default_factory=list)
    rationale_fa: str
    realized_r: float
    floating_r: float
    realized_pips: float
    floating_pips: float
    realized_pnl_usd: float
    floating_pnl_usd: float
    fees_usd: float
    progress_to_tp1_pct: float
    backtest_win_rate_at_entry: float
    backtest_profit_factor_at_entry: float = 0.0
    risk_pips: float = 0.0
    risk_atr: float = 0.0
    early_be_price: Optional[float] = None
    max_favorable_r: float = 0.0
    max_adverse_r: float = 0.0
    policy_version: str = ""
    pending_expires_at: Optional[datetime] = None
    eligible_for_telegram: bool
    telegram_message_id: Optional[str]
    data_source: str
    is_demo_data: bool
    bars_remaining: int
    created_at: datetime
    opened_at: Optional[datetime]
    closed_at: Optional[datetime]
    updated_at: datetime
    events: List[TradeEventOut] = Field(default_factory=list)


class UserJournalUpdate(BaseModel):
    is_following: Optional[bool] = None
    personal_risk_usd: Optional[float] = Field(default=None, ge=0, le=1000000)
    notes: Optional[str] = Field(default=None, max_length=2000)


class UserJournalOut(BaseModel):
    id: int
    trade_id: int
    is_following: bool
    personal_risk_usd: Optional[float]
    notes: str
    updated_at: datetime

    model_config = {"from_attributes": True}


# -------------------- Backtest Qualification --------------------

class BacktestQualificationOut(BaseModel):
    id: int
    symbol: str
    timeframe: str
    risk_tier: str
    eligible_for_telegram: bool
    reason_fa: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate: float
    profit_factor: float
    expectancy_r: float
    max_drawdown_pct: float
    avg_r: float
    avg_hold_bars: float = 0.0
    channel_rank: int = 0
    window_bars: int
    data_source: str
    is_demo_data: bool
    evaluated_at: datetime

    model_config = {"from_attributes": True}


# -------------------- News & Calendar --------------------

class NewsItemOut(BaseModel):
    id: int
    source_name: str
    source_type: str
    canonical_url: str
    original_headline: str
    persian_title: str
    persian_summary: str
    summary_is_ai: bool
    category: str
    related_currencies: List[str]
    related_symbols: List[str]
    impact_level: str
    market_impact_pct: int
    importance_score: int
    volatility_score: int
    currency_relevance_score: int
    direction_bias: str
    direction_confidence: int
    active_trade_risk_score: int
    methodology_note_fa: str
    published_at: datetime
    first_seen_at: datetime
    updated_at: datetime
    telegram_sent: bool
    is_demo_data: bool


class EconomicEventOut(BaseModel):
    id: int
    event_name_en: str
    event_name_fa: str
    country: str
    currency: str
    related_symbols: List[str]
    category: str
    importance: str
    impact_pct: int
    scheduled_at: datetime
    timezone_name: str
    status: str
    actual: Optional[str]
    forecast: Optional[str]
    previous: Optional[str]
    revision: Optional[str]
    surprise_note_fa: str
    source_name: str
    source_url: str
    is_demo_data: bool


# -------------------- Notifications --------------------

class NotificationOut(BaseModel):
    id: int
    kind: str
    title_fa: str
    message_fa: str
    severity: str
    related_trade_id: Optional[int]
    related_news_id: Optional[int]
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# -------------------- Admin --------------------

class EngineConfigUpdate(BaseModel):
    tp1_rr: Optional[float] = Field(default=None, ge=1.0, le=6.0)
    tp2_rr: Optional[float] = Field(default=None, ge=1.5, le=10.0)
    tp3_rr: Optional[float] = Field(default=None, ge=2.0, le=15.0)
    tp1_exit_pct: Optional[float] = Field(default=None, ge=10.0, le=80.0)
    tp2_exit_pct: Optional[float] = Field(default=None, ge=10.0, le=80.0)
    min_score_4h: Optional[float] = Field(default=None, ge=5.0, le=10.0)
    min_score_15m: Optional[float] = Field(default=None, ge=5.0, le=10.0)
    min_score_5m: Optional[float] = Field(default=None, ge=5.0, le=10.0)
    min_adx: Optional[float] = Field(default=None, ge=10.0, le=50.0)
    trend_ema_len: Optional[int] = Field(default=None, ge=20, le=400)
    require_sweep: Optional[bool] = None
    require_idm: Optional[bool] = None
    require_strong_choch_body: Optional[bool] = None
    use_pd_filter: Optional[bool] = None
    use_session_filter: Optional[bool] = None
    skip_dead_volatility: Optional[bool] = None
    skip_news_spikes: Optional[bool] = None
    news_blackout_minutes: Optional[int] = Field(default=None, ge=0, le=120)
    correlation_guard: Optional[bool] = None
    min_backtest_winrate: Optional[float] = Field(default=None, ge=30.0, le=90.0)
    min_backtest_pf: Optional[float] = Field(default=None, ge=1.0, le=5.0)
    min_backtest_trades: Optional[int] = Field(default=None, ge=1, le=100)
    telegram_send_signals: Optional[bool] = None
    telegram_send_tracking: Optional[bool] = None
    telegram_send_high_news: Optional[bool] = None
    telegram_min_news_impact_pct: Optional[int] = Field(default=None, ge=50, le=100)


class AdminUserRoleUpdate(BaseModel):
    role: str = Field(pattern="^(USER|PREMIUM|ADMIN|SUPER_ADMIN)$")
    is_active: Optional[bool] = None


class SourceHealthOut(BaseModel):
    source_key: str
    source_type: str
    display_name: str
    status: str
    last_success_at: Optional[datetime]
    last_error_at: Optional[datetime]
    last_error_msg: str
    latency_ms: Optional[int]
    requests_count: int
    failure_count: int
    rate_limit_note: str

    model_config = {"from_attributes": True}


class AuditLogOut(BaseModel):
    id: int
    actor_user_id: Optional[int]
    actor_email: str
    action: str
    target_type: str
    target_id: str
    outcome: str
    ip_address: str
    correlation_id: str
    details: Any
    created_at: datetime
