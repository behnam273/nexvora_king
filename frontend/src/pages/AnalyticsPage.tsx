import React, { useCallback, useEffect, useState } from 'react';
import { BarChart3, CheckCircle2, Send, ShieldCheck, XCircle } from 'lucide-react';
import { apiFetch } from '../lib/api';
import type { BacktestQualification, KPIStats, TradingPolicy } from '../types';
import { formatSignedR, formatSignedUsd, RISK_TIER_FA, SYMBOL_DISPLAY } from '../lib/format';
import { Badge, ErrorState, LtrValue, Skeleton, StatCard } from '../components/ui';
import { EquityChart } from '../components/charts/EquityChart';

interface BreakdownRow {
  key: string;
  trades: number;
  wins: number;
  losses: number;
  breakeven: number;
  win_rate: number;
  net_pnl_usd: number;
  avg_r: number;
  profit_factor: number;
}

interface AnalyticsResp {
  time_range_label: string;
  calculation_basis_fa: string;
  kpis: KPIStats;
  equity_curve: Array<{
    timestamp: string;
    trade_code: string;
    symbol: string;
    equity: number;
    pnl_usd: number;
    r: number;
  }>;
  by_symbol: BreakdownRow[];
  by_timeframe: BreakdownRow[];
  by_module: BreakdownRow[];
  by_session: BreakdownRow[];
}

export const AnalyticsPage: React.FC = () => {
  const [perf, setPerf] = useState<AnalyticsResp | null>(null);
  const [quals, setQuals] = useState<BacktestQualification[]>([]);
  const [policy, setPolicy] = useState<TradingPolicy | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setError('');
      const [p, q, pol] = await Promise.all([
        apiFetch<AnalyticsResp>('/api/v1/analytics/performance'),
        apiFetch<BacktestQualification[]>('/api/v1/analytics/qualifications'),
        apiFetch<TradingPolicy>('/api/v1/analytics/policy').catch(() => null),
      ]);
      setPerf(p);
      setQuals(q);
      setPolicy(pol);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت آمار');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <Skeleton className="h-96" />;
  if (error || !perf) return <ErrorState message={error || 'خطا'} onRetry={load} />;

  const k = perf.kpis;

  const renderTable = (title: string, rows: BreakdownRow[]) => (
    <div className="nx-card rounded-2xl p-4">
      <h3 className="mb-3 text-sm font-bold text-nx-text">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-xs text-nx-muted">داده بسته‌شده‌ای موجود نیست.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-right text-xs">
            <thead>
              <tr className="border-b border-nx-border text-nx-muted">
                <th className="pb-2">بخش</th>
                <th className="pb-2">تعداد</th>
                <th className="pb-2">Win Rate</th>
                <th className="pb-2">PF</th>
                <th className="pb-2">میانگین R</th>
                <th className="pb-2">سود خالص</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {rows.map((r) => (
                <tr key={r.key}>
                  <td className="py-2 font-bold">
                    <LtrValue>{SYMBOL_DISPLAY[r.key] || r.key}</LtrValue>
                  </td>
                  <td className="py-2"><LtrValue>{r.trades} ({r.wins}W/{r.losses}L)</LtrValue></td>
                  <td className="py-2">
                    <LtrValue className={r.win_rate >= 55 ? 'text-nx-profit font-bold' : 'text-nx-warning'}>
                      {r.win_rate.toFixed(1)}%
                    </LtrValue>
                  </td>
                  <td className="py-2"><LtrValue>{r.profit_factor}</LtrValue></td>
                  <td className="py-2"><LtrValue>{formatSignedR(r.avg_r)}</LtrValue></td>
                  <td className="py-2">
                    <LtrValue className={r.net_pnl_usd >= 0 ? 'text-nx-profit font-bold' : 'text-nx-loss font-bold'}>
                      {formatSignedUsd(r.net_pnl_usd)}
                    </LtrValue>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  return (
    <div className="space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-extrabold text-nx-text">
          <BarChart3 className="h-5 w-5 text-nx-gold" />
          تحلیل عملکرد و ماتریس فیلتر وین‌ریت کانال تلگرام
        </h1>
        <p className="mt-1 text-xs text-nx-muted">{perf.calculation_basis_fa}</p>
      </div>

      {/* KPI Summary */}
      <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
        <StatCard title="Win Rate" value={<LtrValue className="text-nx-profit">{k.win_rate}%</LtrValue>} subtext={`Loss: ${k.loss_rate}% | BE: ${k.breakeven_rate}%`} accent="profit" />
        <StatCard title="Profit Factor" value={<LtrValue className="text-nx-gold">{k.profit_factor}</LtrValue>} subtext={`Expectancy: ${formatSignedR(k.expectancy_r)}`} accent="gold" />
        <StatCard title="سود خالص" value={<LtrValue className={k.net_profit_usd >= 0 ? 'text-nx-profit' : 'text-nx-loss'}>{formatSignedUsd(k.net_profit_usd)}</LtrValue>} subtext={`Gross +$${k.gross_profit_usd} / -$${k.gross_loss_usd}`} accent="info" />
        <StatCard title="حداکثر افت (Max DD)" value={<LtrValue className="text-nx-loss">{k.max_drawdown_pct}%</LtrValue>} subtext={`TP1: ${k.tp1_hits} | TP2: ${k.tp2_hits} | TP3: ${k.tp3_hits}`} accent="loss" />
      </div>

      <EquityChart points={perf.equity_curve} height={210} />

      {/* Active Risk Policy — makes the "strictest filter" auditable in the product */}
      {policy && (
        <div className="nx-card rounded-2xl p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="flex items-center gap-2 text-sm font-extrabold text-nx-text">
              <ShieldCheck className="h-4 w-4 text-nx-gold" />
              سیاست ریسک فعال موتور (حداکثر سخت‌گیری)
            </h2>
            <Badge variant="neutral">
              <LtrValue>{policy.policy_version}</LtrValue>
            </Badge>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {policy.timeframes.map((tf) => {
              const rf = RISK_TIER_FA[tf.timeframe === '4H' ? 'SAFE' : tf.timeframe === '15m' ? 'MEDIUM_RISK' : 'HIGH_RISK'];
              return (
                <div key={tf.timeframe} className="rounded-xl border border-nx-border/70 bg-nx-bg/55 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <span className={`rounded-md border px-2 py-0.5 text-[10px] font-bold ${rf?.color || ''}`}>
                      <LtrValue>{tf.timeframe}</LtrValue> · {rf?.label}
                    </span>
                    <span className="text-[11px] text-nx-muted">ADX ≥ <LtrValue>{tf.min_adx}</LtrValue></span>
                  </div>
                  <div className="space-y-1 text-[11px] text-nx-muted">
                    <div className="flex items-center justify-between">
                      <span>اهداف (R)</span>
                      <LtrValue className="font-bold text-nx-text">
                        {tf.targets.map((t) => t.rr).join(' / ')}
                      </LtrValue>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>خروج پله‌ای (%)</span>
                      <LtrValue className="font-bold text-nx-text">
                        {tf.targets.map((t) => t.exit_pct).join(' / ')}
                      </LtrValue>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>ریسک‌فری در</span>
                      <LtrValue className="font-bold text-nx-profit">{tf.early_be_pct}% مسیر TP1</LtrValue>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>حد ضرر ساختاری (ATR)</span>
                      <LtrValue className="font-bold text-nx-text">
                        {tf.min_stop_atr.toFixed(1)}–{tf.max_stop_atr.toFixed(1)}
                      </LtrValue>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>حداقل امتیاز کانفلوئنس</span>
                      <LtrValue className="font-bold text-nx-gold">{tf.min_score}/10</LtrValue>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>انقضای سفارش پندینگ</span>
                      <LtrValue className="font-bold text-nx-text">{tf.pending_expiry_hours}h</LtrValue>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          <ul className="mt-3 space-y-1.5 border-t border-nx-border/70 pt-3 text-[11px] leading-6 text-nx-muted">
            {policy.gate_rules_fa.map((r, i) => (
              <li key={i} className="flex gap-2">
                <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-nx-gold" />
                <span>{r}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-nx-muted">
            محافظت پرتفوی: حداکثر <LtrValue className="text-nx-text">{policy.max_concurrent_trades}</LtrValue> پوزیشن هم‌زمان،
            فقط <LtrValue className="text-nx-text">{policy.max_concurrent_per_symbol}</LtrValue> پوزیشن در هر نماد،
            و توقف پس از <LtrValue className="text-nx-text">{policy.consecutive_loss_pause}</LtrValue> ضرر متوالی
            به مدت <LtrValue className="text-nx-text">{policy.consecutive_loss_pause_hours}</LtrValue> ساعت.
          </p>
        </div>
      )}

      {/* Backtest Win-Rate Qualification Matrix (6 symbols x 3 timeframes = 18 combinations) */}
      <div className="nx-card-gold rounded-2xl p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-extrabold text-nx-gold">
              <Send className="h-4 w-4" />
              دروازه انتخاب ارزهای با Win Rate قوی برای کانال تلگرام (۶ نماد × ۳ تایم‌فریم)
            </h2>
            <p className="mt-0.5 text-xs text-nx-muted">
              تنها ترکیب‌هایی که در بک‌تست Rolling روی هسته Trading Hub 3.0 از آستانه Win Rate و Profit Factor عبور کنند، مجوز ارسال به کانال تلگرام می‌گیرند.
            </p>
          </div>
          <Badge variant="gold">
            تأییدشده: <LtrValue>{quals.filter((q) => q.eligible_for_telegram).length} / {quals.length}</LtrValue>
          </Badge>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-right text-xs">
            <thead>
              <tr className="border-b border-nx-border text-nx-muted">
                <th className="pb-2">نماد</th>
                <th className="pb-2">تایم‌فریم و سطح ریسک</th>
                <th className="pb-2">مجوز تلگرام</th>
                <th className="pb-2">معاملات</th>
                <th className="pb-2">Win Rate</th>
                <th className="pb-2">Profit Factor</th>
                <th className="pb-2">میانگین R</th>
                <th className="pb-2">توضیح فیلتر</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {quals.map((q) => {
                const rf = RISK_TIER_FA[q.risk_tier];
                return (
                  <tr key={q.id} className="hover:bg-nx-elevated/40">
                    <td className="py-2.5 font-bold">
                      <LtrValue>{SYMBOL_DISPLAY[q.symbol] || q.symbol}</LtrValue>
                    </td>
                    <td className="py-2.5">
                      <span className={`rounded-md border px-2 py-0.5 text-[10px] ${rf?.color || ''}`}>
                        {rf?.label}
                      </span>
                    </td>
                    <td className="py-2.5">
                      {q.eligible_for_telegram ? (
                        <Badge variant="profit">
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          مجاز (ارسال به کانال)
                        </Badge>
                      ) : (
                        <Badge variant="loss">
                          <XCircle className="h-3.5 w-3.5" />
                          فیلتر شده
                        </Badge>
                      )}
                    </td>
                    <td className="py-2.5">
                      <LtrValue>{q.total_trades} ({q.winning_trades}W/{q.losing_trades}L)</LtrValue>
                    </td>
                    <td className="py-2.5 font-bold">
                      <LtrValue className={q.win_rate >= 55 ? 'text-nx-profit' : 'text-nx-muted'}>
                        {q.win_rate.toFixed(1)}%
                      </LtrValue>
                    </td>
                    <td className="py-2.5">
                      <LtrValue>{q.profit_factor.toFixed(2)}</LtrValue>
                    </td>
                    <td className="py-2.5">
                      <LtrValue className={q.avg_r >= 0 ? 'text-nx-profit' : 'text-nx-loss'}>
                        {formatSignedR(q.avg_r)}
                      </LtrValue>
                    </td>
                    <td className="py-2.5 text-[11px] text-nx-muted max-w-xs">{q.reason_fa}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Detailed Breakdowns */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {renderTable('تفکیک عملکرد بر اساس جفت‌ارز', perf.by_symbol)}
        {renderTable('تفکیک عملکرد بر اساس تایم‌فریم و ریسک', perf.by_timeframe)}
        {renderTable('تفکیک بر اساس ماژول ورود (SMC)', perf.by_module)}
        {renderTable('تفکیک بر اساس سشن معاملاتی', perf.by_session)}
      </div>
    </div>
  );
};
