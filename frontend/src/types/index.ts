export interface User {
  id: number;
  email: string;
  full_name: string;
  role: 'USER' | 'PREMIUM' | 'ADMIN' | 'SUPER_ADMIN';
  is_active: boolean;
  mfa_enabled: boolean;
  timezone_pref: string;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  notify_signals: boolean;
  notify_tracking: boolean;
  notify_high_news: boolean;
  created_at: string;
}

export interface TradeEvent {
  id: number;
  trade_id: number;
  event_type: string;
  price: number | null;
  r_value: number | null;
  pips_value: number | null;
  description_fa: string;
  telegram_reply_id: string | null;
  source_timestamp: string;
  created_at: string;
}

export interface ChecklistItem {
  key: string;
  label_fa: string;
  passed: boolean;
}

export interface SignalTrade {
  id: number;
  trade_code: string;
  symbol: string;
  display_symbol?: string;
  market_class: string;
  timeframe: '4H' | '15m' | '5m';
  timeframe_label_fa?: string;
  risk_tier: 'SAFE' | 'MEDIUM_RISK' | 'HIGH_RISK';
  direction: 'LONG' | 'SHORT';
  strategy_name: string;
  entry_module: string;
  htf_bias: string;
  session_name: string;
  status: string;
  outcome: string;
  entry_price: number;
  fill_price: number | null;
  current_price: number;
  initial_sl: number;
  current_sl: number;
  tp1: number;
  tp2: number;
  tp3: number;
  tp1_exit_pct: number;
  tp2_exit_pct: number;
  tp3_exit_pct: number;
  remaining_pct: number;
  tp1_hit: boolean;
  tp2_hit: boolean;
  tp3_hit: boolean;
  risk_pct: number;
  position_size_lots: number;
  confluence_score: number;
  grade: string;
  checklist: ChecklistItem[];
  rationale_fa: string;
  realized_r: number;
  floating_r: number;
  realized_pips: number;
  floating_pips: number;
  realized_pnl_usd: number;
  floating_pnl_usd: number;
  fees_usd: number;
  progress_to_tp1_pct: number;
  backtest_win_rate_at_entry: number;
  backtest_profit_factor_at_entry?: number;
  risk_pips?: number;
  risk_atr?: number;
  early_be_price?: number;
  max_favorable_r?: number;
  max_adverse_r?: number;
  policy_version?: string;
  pending_expires_at?: string | null;
  eligible_for_telegram: boolean;
  telegram_message_id: string | null;
  data_source: string;
  is_demo_data: boolean;
  bars_remaining: number;
  created_at: string;
  opened_at: string | null;
  closed_at: string | null;
  updated_at: string;
  events: TradeEvent[];
}

export interface CandlePoint {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface BacktestQualification {
  id: number;
  symbol: string;
  timeframe: '4H' | '15m' | '5m';
  risk_tier: 'SAFE' | 'MEDIUM_RISK' | 'HIGH_RISK';
  eligible_for_telegram: boolean;
  reason_fa: string;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  breakeven_trades: number;
  win_rate: number;
  profit_factor: number;
  expectancy_r: number;
  max_drawdown_pct: number;
  avg_r: number;
  avg_hold_bars?: number;
  channel_rank?: number;
  window_bars: number;
  data_source: string;
  is_demo_data: boolean;
  policy_version?: string;
  evaluated_at: string;
}

export interface PolicyTarget {
  label: string;
  rr: number;
  exit_pct: number;
}

export interface TimeframePolicy {
  timeframe: '4H' | '15m' | '5m';
  risk_tier: 'SAFE' | 'MEDIUM_RISK' | 'HIGH_RISK';
  sl_buf_atr: number;
  min_stop_atr: number;
  max_stop_atr: number;
  targets: PolicyTarget[];
  early_be_pct: number;
  min_score: number;
  min_adx: number;
  min_rr_tp1: number;
  require_session: boolean;
  require_dual_htf: boolean;
  require_di_alignment: boolean;
  require_idm: boolean;
  pending_expiry_hours: number;
}

export interface TradingPolicy {
  policy_version: string;
  max_concurrent_trades: number;
  max_concurrent_per_symbol: number;
  consecutive_loss_pause: number;
  consecutive_loss_pause_hours: number;
  timeframes: TimeframePolicy[];
  gate_rules_fa: string[];
}

export interface NewsItem {
  id: number;
  source_name: string;
  source_type: string;
  canonical_url: string;
  original_headline: string;
  persian_title: string;
  persian_summary: string;
  summary_is_ai: boolean;
  category: string;
  related_currencies: string[];
  related_symbols: string[];
  impact_level: 'HIGH' | 'MEDIUM' | 'LOW';
  market_impact_pct: number;
  importance_score: number;
  volatility_score: number;
  currency_relevance_score: number;
  direction_bias: string;
  direction_confidence: number;
  active_trade_risk_score: number;
  methodology_note_fa: string;
  published_at: string;
  first_seen_at: string;
  updated_at: string;
  telegram_sent: boolean;
  is_demo_data: boolean;
}

export interface EconomicEvent {
  id: number;
  event_name_en: string;
  event_name_fa: string;
  country: string;
  currency: string;
  related_symbols: string[];
  category: string;
  importance: 'HIGH' | 'MEDIUM' | 'LOW';
  impact_pct: number;
  scheduled_at: string;
  timezone_name: string;
  status: 'SCHEDULED' | 'PUBLISHED' | 'REVISED';
  actual: string | null;
  forecast: string | null;
  previous: string | null;
  revision: string | null;
  surprise_note_fa: string;
  source_name: string;
  source_url: string;
  is_demo_data: boolean;
}

export interface NotificationItem {
  id: number;
  kind: string;
  title_fa: string;
  message_fa: string;
  severity: 'info' | 'success' | 'warning' | 'danger';
  related_trade_id: number | null;
  related_news_id: number | null;
  is_read: boolean;
  created_at: string;
}

export interface SessionInfo {
  id: number;
  ip_address: string | null;
  user_agent: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  is_current: boolean;
}

export interface KPIStats {
  total_trades: number;
  total_signals_all: number;
  active_trades: number;
  cancelled_or_expired: number;
  winning_trades: number;
  losing_trades: number;
  breakeven_trades: number;
  win_rate: number;
  loss_rate: number;
  breakeven_rate: number;
  gross_profit_usd: number;
  gross_loss_usd: number;
  net_profit_usd: number;
  return_pct: number;
  profit_factor: number;
  avg_win_usd: number;
  avg_loss_usd: number;
  expectancy_r: number;
  avg_r: number;
  max_drawdown_pct: number;
  tp1_hits: number;
  tp2_hits: number;
  tp3_hits: number;
  target_hits_total: number;
  sl_hits: number;
}
