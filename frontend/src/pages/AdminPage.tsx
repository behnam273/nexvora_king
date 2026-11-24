import React, { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  Play,
  RefreshCw,
  Send,
  Shield,
  Sliders,
  Users,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { formatDateTimeFa } from '../lib/format';
import { Badge, Button, ErrorState, LtrValue, Skeleton } from '../components/ui';

interface SourceHealth {
  source_key: string;
  source_type: string;
  display_name: string;
  status: string;
  last_success_at: string | null;
  last_error_msg: string;
  latency_ms: number | null;
  requests_count: number;
  failure_count: number;
}

interface AdminOverviewResp {
  users_total: number;
  users_active: number;
  trades_total: number;
  trades_open: number;
  news_total: number;
  eligible_pairs_count: number;
  total_pairs_tf: number;
  data_mode: string;
  telegram_configured: boolean;
  telegram_dry_run: boolean;
  twelvedata_configured: boolean;
  llm_configured: boolean;
  sources: SourceHealth[];
}

interface EngineConfigResp {
  preset_name: string;
  tp1_rr: number;
  tp2_rr: number;
  tp3_rr: number;
  tp1_exit_pct: number;
  tp2_exit_pct: number;
  min_score_4h: number;
  min_score_15m: number;
  min_score_5m: number;
  min_adx: number;
  trend_ema_len: number;
  require_sweep: boolean;
  require_idm: boolean;
  require_strong_choch_body: boolean;
  use_pd_filter: boolean;
  use_session_filter: boolean;
  skip_dead_volatility: boolean;
  skip_news_spikes: boolean;
  news_blackout_minutes: number;
  correlation_guard: boolean;
  min_backtest_winrate: number;
  min_backtest_pf: number;
  min_backtest_trades: number;
  telegram_send_signals: boolean;
  telegram_send_tracking: boolean;
  telegram_send_high_news: boolean;
  telegram_min_news_impact_pct: number;
}

interface AuditLogRow {
  id: number;
  actor_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  outcome: string;
  ip_address: string | null;
  created_at: string;
}

interface UserRow {
  id: number;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  mfa_enabled: boolean;
}

export const AdminPage: React.FC = () => {
  const [overview, setOverview] = useState<AdminOverviewResp | null>(null);
  const [cfg, setCfg] = useState<EngineConfigResp | null>(null);
  const [logs, setLogs] = useState<AuditLogRow[]>([]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [banner, setBanner] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setError('');
      const [ov, c, l, u] = await Promise.all([
        apiFetch<AdminOverviewResp>('/api/v1/admin/overview'),
        apiFetch<EngineConfigResp>('/api/v1/admin/engine-config'),
        apiFetch<AuditLogRow[]>('/api/v1/admin/audit-logs?limit=25'),
        apiFetch<UserRow[]>('/api/v1/admin/users'),
      ]);
      setOverview(ov);
      setCfg(c);
      setLogs(l);
      setUsers(u);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در بارگذاری پنل ادمین');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const runAction = async (label: string, path: string, body?: object) => {
    setBusy(label);
    setBanner('');
    try {
      const res = await apiFetch<Record<string, unknown>>(path, {
        method: 'POST',
        body: body ? JSON.stringify(body) : undefined,
      });
      setBanner(`${label} انجام شد: ${JSON.stringify(res)}`);
      await load();
    } catch (err) {
      setBanner(err instanceof Error ? err.message : 'خطا در اجرای عملیات');
    } finally {
      setBusy('');
    }
  };

  const saveConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!cfg) return;
    setBusy('ذخیره تنظیمات');
    try {
      await apiFetch('/api/v1/admin/engine-config', {
        method: 'PUT',
        body: JSON.stringify(cfg),
      });
      setBanner('تنظیمات موتور و فیلترهای سخت‌گیرانه Trading Hub 3.0 با موفقیت ذخیره و در Audit Log ثبت شد.');
      await load();
    } catch (err) {
      setBanner(err instanceof Error ? err.message : 'خطا در ذخیره تنظیمات');
    } finally {
      setBusy('');
    }
  };

  if (loading) return <Skeleton className="h-96" />;
  if (error || !cfg || !overview) return <ErrorState message={error || 'خطا'} onRetry={load} />;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-extrabold text-nx-text">
            <Shield className="h-5 w-5 text-nx-gold" />
            مرکز کنترل ادمین و تنظیمات Trading Hub 3.0 + تلگرام
          </h1>
          <p className="text-xs text-nx-muted">
            تنظیم فیلترهای سخت‌گیرانه، اجرای دستی بک‌تست و اسکن، پایش سلامت منابع داده و ممیزی امنیتی
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            onClick={() => runAction('اسکن موتور سیگنال', '/api/v1/admin/actions/scan-now')}
            disabled={!!busy}
          >
            <Play className="h-3.5 w-3.5" />
            اجرای اسکن سیگنال
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => runAction('بک‌تست ۱۸ ترکیب', '/api/v1/admin/actions/refresh-backtests')}
            disabled={!!busy}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            به‌روزرسانی ماتریس Win Rate
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => runAction('به‌روزرسانی اخبار', '/api/v1/admin/actions/refresh-news')}
            disabled={!!busy}
          >
            دریافت اخبار
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => runAction('تست کانال تلگرام', '/api/v1/admin/actions/test-telegram')}
            disabled={!!busy}
          >
            <Send className="h-3.5 w-3.5" />
            تست تلگرام
          </Button>
        </div>
      </div>

      {/* Quick System Status Pills */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant="gold">حالت داده: {overview.data_mode}</Badge>
        <Badge variant={overview.telegram_configured && !overview.telegram_dry_run ? 'profit' : 'warning'}>
          تلگرام: {overview.telegram_configured && !overview.telegram_dry_run ? 'متصل (Live)' : 'DRY-RUN (ثبت در لاگ)'}
        </Badge>
        <Badge variant={overview.twelvedata_configured ? 'profit' : 'neutral'}>
          TwelveData: {overview.twelvedata_configured ? 'کلید تنظیم شده' : 'کلید خالی (Fallback)'}
        </Badge>
        <Badge variant="info">
          ترکیب‌های مجاز تلگرام: {overview.eligible_pairs_count} / {overview.total_pairs_tf}
        </Badge>
      </div>

      {banner && (
        <div className="rounded-xl border border-nx-gold/40 bg-nx-gold/10 px-4 py-3 text-xs text-nx-gold break-words">
          {banner}
        </div>
      )}

      {/* Engine & Filter Config Form */}
      <form onSubmit={saveConfig} className="nx-card rounded-2xl p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-bold text-nx-text">
            <Sliders className="h-4 w-4 text-nx-gold" />
            تنظیمات فیلترهای سخت‌گیرانه ({cfg.preset_name})
          </h2>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5 text-xs">
          <label className="space-y-1">
            <span className="text-nx-muted">حداقل ADX</span>
            <input
              type="number"
              step="0.5"
              value={cfg.min_adx}
              onChange={(e) => setCfg({ ...cfg, min_adx: Number(e.target.value) })}
              className="w-full rounded-xl border border-nx-border bg-nx-bg px-2.5 py-2 font-mono"
            />
          </label>
          <label className="space-y-1">
            <span className="text-nx-muted">حداقل امتیاز 4H (امن)</span>
            <input
              type="number"
              step="0.1"
              value={cfg.min_score_4h}
              onChange={(e) => setCfg({ ...cfg, min_score_4h: Number(e.target.value) })}
              className="w-full rounded-xl border border-nx-border bg-nx-bg px-2.5 py-2 font-mono"
            />
          </label>
          <label className="space-y-1">
            <span className="text-nx-muted">حداقل امتیاز 15m (متوسط)</span>
            <input
              type="number"
              step="0.1"
              value={cfg.min_score_15m}
              onChange={(e) => setCfg({ ...cfg, min_score_15m: Number(e.target.value) })}
              className="w-full rounded-xl border border-nx-border bg-nx-bg px-2.5 py-2 font-mono"
            />
          </label>
          <label className="space-y-1">
            <span className="text-nx-muted">حداقل امتیاز 5m (بالا)</span>
            <input
              type="number"
              step="0.1"
              value={cfg.min_score_5m}
              onChange={(e) => setCfg({ ...cfg, min_score_5m: Number(e.target.value) })}
              className="w-full rounded-xl border border-nx-border bg-nx-bg px-2.5 py-2 font-mono"
            />
          </label>
          <label className="space-y-1">
            <span className="text-nx-muted">حداقل Win Rate تلگرام (%)</span>
            <input
              type="number"
              step="1"
              value={cfg.min_backtest_winrate}
              onChange={(e) => setCfg({ ...cfg, min_backtest_winrate: Number(e.target.value) })}
              className="w-full rounded-xl border border-nx-border bg-nx-bg px-2.5 py-2 font-mono"
            />
          </label>
          <label className="space-y-1">
            <span className="text-nx-muted">حداقل Profit Factor</span>
            <input
              type="number"
              step="0.1"
              value={cfg.min_backtest_pf}
              onChange={(e) => setCfg({ ...cfg, min_backtest_pf: Number(e.target.value) })}
              className="w-full rounded-xl border border-nx-border bg-nx-bg px-2.5 py-2 font-mono"
            />
          </label>
          <label className="space-y-1">
            <span className="text-nx-muted">تارگت اول TP1 (R)</span>
            <input
              type="number"
              step="0.5"
              value={cfg.tp1_rr}
              onChange={(e) => setCfg({ ...cfg, tp1_rr: Number(e.target.value) })}
              className="w-full rounded-xl border border-nx-border bg-nx-bg px-2.5 py-2 font-mono"
            />
          </label>
          <label className="space-y-1">
            <span className="text-nx-muted">تارگت دوم TP2 (R)</span>
            <input
              type="number"
              step="0.5"
              value={cfg.tp2_rr}
              onChange={(e) => setCfg({ ...cfg, tp2_rr: Number(e.target.value) })}
              className="w-full rounded-xl border border-nx-border bg-nx-bg px-2.5 py-2 font-mono"
            />
          </label>
          <label className="space-y-1">
            <span className="text-nx-muted">تارگت سوم TP3 (R)</span>
            <input
              type="number"
              step="0.5"
              value={cfg.tp3_rr}
              onChange={(e) => setCfg({ ...cfg, tp3_rr: Number(e.target.value) })}
              className="w-full rounded-xl border border-nx-border bg-nx-bg px-2.5 py-2 font-mono"
            />
          </label>
          <label className="space-y-1">
            <span className="text-nx-muted">حداقل درصد خبر تلگرام</span>
            <input
              type="number"
              step="5"
              value={cfg.telegram_min_news_impact_pct}
              onChange={(e) => setCfg({ ...cfg, telegram_min_news_impact_pct: Number(e.target.value) })}
              className="w-full rounded-xl border border-nx-border bg-nx-bg px-2.5 py-2 font-mono"
            />
          </label>
        </div>

        <div className="flex flex-wrap gap-4 text-xs pt-1">
          {[
            { key: 'require_sweep', label: 'الزام Liquidity Sweep' },
            { key: 'require_idm', label: 'الزام IDM (Inducement)' },
            { key: 'require_strong_choch_body', label: 'بدنه قوی CHoCH' },
            { key: 'use_pd_filter', label: 'فیلتر Premium/Discount' },
            { key: 'use_session_filter', label: 'فیلتر سشن لندن/نیویورک' },
            { key: 'correlation_guard', label: 'گارد همبستگی ارزی' },
            { key: 'telegram_send_signals', label: 'ارسال سیگنال به تلگرام' },
            { key: 'telegram_send_tracking', label: 'ارسال پیگیری پوزیشن به تلگرام' },
            { key: 'telegram_send_high_news', label: 'ارسال اخبار High Impact به تلگرام' },
          ].map((t) => (
            <label key={t.key} className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={Boolean(cfg[t.key as keyof EngineConfigResp])}
                onChange={(e) => setCfg({ ...cfg, [t.key]: e.target.checked })}
                className="accent-nx-gold h-4 w-4"
              />
              <span>{t.label}</span>
            </label>
          ))}
        </div>

        <Button type="submit" disabled={!!busy}>
          ذخیره تنظیمات موتور
        </Button>
      </form>

      {/* Source Health + Users */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <div className="nx-card rounded-2xl p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-bold text-nx-text">
            <Activity className="h-4 w-4 text-nx-gold" />
            سلامت منابع داده و تلگرام
          </h2>
          <div className="space-y-2 text-xs">
            {overview.sources.map((h) => (
              <div key={h.source_key} className="flex items-center justify-between rounded-xl bg-nx-bg/60 p-3">
                <div>
                  <div className="font-bold text-nx-text">{h.display_name}</div>
                  <div className="text-[11px] text-nx-muted">
                    {h.source_type} • درخواست‌ها: {h.requests_count}
                    {h.latency_ms ? ` • ${h.latency_ms}ms` : ''}
                    {h.last_error_msg ? ` • ${h.last_error_msg}` : ''}
                  </div>
                </div>
                <Badge
                  variant={
                    h.status === 'HEALTHY'
                      ? 'profit'
                      : h.status === 'DEMO_MODE' || h.status === 'DRY_RUN' || h.status === 'DEGRADED'
                        ? 'warning'
                        : 'loss'
                  }
                >
                  {h.status}
                </Badge>
              </div>
            ))}
          </div>
        </div>

        <div className="nx-card rounded-2xl p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-bold text-nx-text">
            <Users className="h-4 w-4 text-nx-gold" />
            کاربران و نقش‌ها (RBAC)
          </h2>
          <div className="space-y-2 text-xs">
            {users.map((u) => (
              <div key={u.id} className="flex items-center justify-between rounded-xl bg-nx-bg/60 p-3">
                <div>
                  <div className="font-bold text-nx-text">{u.full_name}</div>
                  <div className="text-[11px] text-nx-muted"><LtrValue>{u.email}</LtrValue></div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="gold">{u.role}</Badge>
                  <Badge variant={u.is_active ? 'profit' : 'loss'}>{u.is_active ? 'فعال' : 'مسدود'}</Badge>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Audit Logs */}
      <div className="nx-card rounded-2xl p-4 overflow-x-auto">
        <h2 className="mb-3 text-sm font-bold text-nx-text">گزارش ممیزی امنیتی (Audit Log)</h2>
        <table className="w-full text-right text-xs">
          <thead>
            <tr className="border-b border-nx-border text-nx-muted">
              <th className="pb-2">عملیات</th>
              <th className="pb-2">کاربر</th>
              <th className="pb-2">هدف</th>
              <th className="pb-2">وضعیت</th>
              <th className="pb-2">IP</th>
              <th className="pb-2">زمان</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {logs.map((l) => (
              <tr key={l.id}>
                <td className="py-2 font-mono text-[11px] text-nx-gold"><LtrValue>{l.action}</LtrValue></td>
                <td className="py-2"><LtrValue>{l.actor_email || '-'}</LtrValue></td>
                <td className="py-2 text-nx-muted"><LtrValue>{l.target_type ? `${l.target_type}#${l.target_id || ''}` : '-'}</LtrValue></td>
                <td className="py-2">
                  <Badge variant={l.outcome === 'SUCCESS' ? 'profit' : 'loss'}>{l.outcome}</Badge>
                </td>
                <td className="py-2 text-nx-muted"><LtrValue>{l.ip_address || '-'}</LtrValue></td>
                <td className="py-2 text-nx-muted">{formatDateTimeFa(l.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
