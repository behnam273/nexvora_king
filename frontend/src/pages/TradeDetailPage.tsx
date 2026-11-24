import React, { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  ArrowRight,
  BookOpen,
  Clock,
  Save,
  Send,
  ShieldCheck,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import type { CandlePoint, SignalTrade } from '../types';
import {
  formatDateTimeFa,
  formatPrice,
  formatSignedR,
  formatSignedUsd,
  RISK_TIER_FA,
  STATUS_FA,
  SYMBOL_DIGITS,
  SYMBOL_DISPLAY,
} from '../lib/format';
import {
  Badge,
  Button,
  CheckBadge,
  DemoBanner,
  ErrorState,
  LtrValue,
  Skeleton,
} from '../components/ui';
import { CandleChart } from '../components/charts/CandleChart';

interface TradeDetailResp {
  trade: SignalTrade;
  candles: CandlePoint[];
  candles_source: string;
  candles_is_demo: boolean;
  user_journal: {
    is_following: boolean;
    personal_risk_usd: number | null;
    notes: string;
  } | null;
}

export const TradeDetailPage: React.FC = () => {
  const { id } = useParams();
  const [data, setData] = useState<TradeDetailResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [notes, setNotes] = useState('');
  const [riskUsd, setRiskUsd] = useState('');
  const [savingJournal, setSavingJournal] = useState(false);
  const [journalMsg, setJournalMsg] = useState('');

  const load = useCallback(async () => {
    try {
      setError('');
      const res = await apiFetch<TradeDetailResp>(`/api/v1/trades/${id}`);
      setData(res);
      setNotes(res.user_journal?.notes || '');
      setRiskUsd(
        res.user_journal?.personal_risk_usd != null
          ? String(res.user_journal.personal_risk_usd)
          : ''
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت جزئیات معامله');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const saveJournal = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingJournal(true);
    setJournalMsg('');
    try {
      await apiFetch(`/api/v1/trades/${id}/journal`, {
        method: 'PUT',
        body: JSON.stringify({
          notes,
          personal_risk_usd: riskUsd ? Number(riskUsd) : null,
          is_following: true,
        }),
      });
      setJournalMsg('ژورنال شخصی شما با موفقیت ذخیره شد (کاملاً خصوصی).');
    } catch (err) {
      setJournalMsg(err instanceof Error ? err.message : 'خطا در ذخیره یادداشت');
    } finally {
      setSavingJournal(false);
    }
  };

  if (loading) return <Skeleton className="h-96" />;
  if (error || !data) return <ErrorState message={error || 'یافت نشد'} onRetry={load} />;

  const t = data.trade;
  const st = STATUS_FA[t.status] || { label: t.status, color: '' };
  const rf = RISK_TIER_FA[t.risk_tier];

  return (
    <div className="space-y-5">
      <DemoBanner isDemo={t.is_demo_data} />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link
            to="/trades/live"
            className="rounded-xl border border-nx-border bg-nx-surface p-2 text-nx-muted hover:text-nx-gold"
          >
            <ArrowRight className="h-4 w-4" />
          </Link>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-lg font-extrabold text-nx-text">
                <LtrValue>{SYMBOL_DISPLAY[t.symbol] || t.symbol}</LtrValue>
              </h1>
              <Badge variant={t.direction === 'LONG' ? 'profit' : 'loss'}>
                {t.direction === 'LONG' ? 'LONG خرید' : 'SHORT فروش'}
              </Badge>
              <span className={`rounded-lg border px-2 py-0.5 text-xs ${rf?.color || ''}`}>
                {rf?.label}
              </span>
              <span className={`rounded-lg border px-2 py-0.5 text-xs ${st.color}`}>
                {st.label}
              </span>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-nx-muted">
              <LtrValue>{t.trade_code}</LtrValue>
              <span>•</span>
              <span>{t.strategy_name}</span>
              <span>•</span>
              <span>ماژول {t.entry_module}</span>
              <span>•</span>
              <span className="text-nx-gold font-bold">
                امتیاز <LtrValue>{t.confluence_score}/10 ({t.grade})</LtrValue>
              </span>
            </div>
          </div>
        </div>

        <div className="text-left">
          <LtrValue
            className={`text-2xl font-extrabold ${
              t.realized_pnl_usd + t.floating_pnl_usd >= 0 ? 'text-nx-profit' : 'text-nx-loss'
            }`}
          >
            {formatSignedUsd(t.realized_pnl_usd + t.floating_pnl_usd)}
          </LtrValue>
          <div className="text-xs text-nx-muted">
            تحقق‌یافته: <LtrValue>{formatSignedR(t.realized_r)}</LtrValue> | شناور:{' '}
            <LtrValue>{formatSignedR(t.floating_r)}</LtrValue>
          </div>
        </div>
      </div>

      {/* Candlestick Chart with Entry / SL / TP1 / TP2 / TP3 Overlays */}
      <div className="nx-card rounded-2xl p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs">
          <span className="font-bold text-nx-text">نمودار کندل‌استیک و سطوح دقیق معامله</span>
          <span className="text-nx-muted">منبع: {data.candles_source}</span>
        </div>
        <CandleChart
          candles={data.candles}
          digits={SYMBOL_DIGITS[t.symbol] ?? 5}
          height={360}
          levels={{
            entry: t.fill_price || t.entry_price,
            sl: t.current_sl,
            tp1: t.tp1,
            tp2: t.tp2,
            tp3: t.tp3,
            beActive: t.tp1_hit,
          }}
        />
      </div>

      {/* Official NEXVORA Telegram Signal Card Preview & Download */}
      <div className="nx-card rounded-2xl p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-bold text-nx-text">کارت سیگنال رسمی کانال تلگرام NEXVORA</h2>
            <p className="text-[11px] text-nx-muted">
              تصویر ارسالی استاندارد در کانال تلگرام با نمودار زنده، EMA20/50 و سطوح دقیق مدیریت ریسک
            </p>
          </div>
          <a
            href={`/api/v1/trades/${t.id}/card.png`}
            download={`${t.trade_code}.png`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-xl border border-nx-gold/40 bg-nx-gold/15 px-3 py-1.5 text-xs font-bold text-nx-gold hover:bg-nx-gold/25 transition"
          >
            دانلود کارت سیگنال (PNG)
          </a>
        </div>
        <div className="flex justify-center rounded-xl bg-nx-bg/70 p-3">
          <img
            src={`/api/v1/trades/${t.id}/card.png`}
            alt={`کارت سیگنال ${t.symbol}`}
            className="max-h-[540px] w-auto rounded-xl border border-nx-border/60 shadow-lg"
            loading="lazy"
          />
        </div>
      </div>

      {/* Price levels + Engine rationale */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
        <div className="space-y-4 lg:col-span-7">
          <div className="nx-card rounded-2xl p-4">
            <h2 className="mb-3 text-sm font-bold text-nx-text">سطوح قیمتی و مدیریت پله‌ای</h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 text-xs">
              <div className="rounded-xl bg-nx-bg/60 p-3">
                <div className="text-nx-muted">نقطه ورود (Limit / Fill)</div>
                <div className="mt-1 text-base font-bold text-sky-300">
                  <LtrValue>{formatPrice(t.symbol, t.fill_price || t.entry_price)}</LtrValue>
                </div>
              </div>
              <div className="rounded-xl bg-nx-bg/60 p-3">
                <div className="text-nx-muted flex items-center gap-1">
                  حد ضرر فعال {t.tp1_hit && <ShieldCheck className="h-3.5 w-3.5 text-nx-gold" />}
                </div>
                <div className="mt-1 text-base font-bold text-nx-loss">
                  <LtrValue>{formatPrice(t.symbol, t.current_sl)}</LtrValue>
                </div>
                <div className="text-[10px] text-nx-muted">
                  اولیه: <LtrValue>{formatPrice(t.symbol, t.initial_sl)}</LtrValue>
                </div>
              </div>
              <div className="rounded-xl bg-nx-bg/60 p-3">
                <div className="text-nx-muted">حجم پیشنهادی (۱٪ ریسک)</div>
                <div className="mt-1 text-base font-bold text-nx-gold">
                  <LtrValue>{t.position_size_lots} lots</LtrValue>
                </div>
                <div className="text-[10px] text-nx-muted">باقی‌مانده: {t.remaining_pct}%</div>
              </div>
              <div className={`rounded-xl border p-3 ${t.tp1_hit ? 'border-nx-profit/50 bg-nx-profit/10' : 'border-nx-border bg-nx-bg/60'}`}>
                <div className="text-nx-muted">TP1 ({t.tp1_exit_pct}% + انتقال SL به BE)</div>
                <div className="mt-1 text-base font-bold text-nx-profit">
                  <LtrValue>{formatPrice(t.symbol, t.tp1)}</LtrValue>
                </div>
              </div>
              <div className={`rounded-xl border p-3 ${t.tp2_hit ? 'border-nx-profit/50 bg-nx-profit/10' : 'border-nx-border bg-nx-bg/60'}`}>
                <div className="text-nx-muted">TP2 ({t.tp2_exit_pct}% + SL به TP1)</div>
                <div className="mt-1 text-base font-bold text-nx-profit">
                  <LtrValue>{formatPrice(t.symbol, t.tp2)}</LtrValue>
                </div>
              </div>
              <div className={`rounded-xl border p-3 ${t.tp3_hit ? 'border-nx-gold/60 bg-nx-gold/10' : 'border-nx-border bg-nx-bg/60'}`}>
                <div className="text-nx-muted">TP3 ({t.tp3_exit_pct}% نهایی)</div>
                <div className="mt-1 text-base font-bold text-nx-gold">
                  <LtrValue>{formatPrice(t.symbol, t.tp3)}</LtrValue>
                </div>
              </div>
            </div>

            {/* Signal integrity: the numbers that justify (or refuse) publication */}
            <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-3">
              <div className="flex items-center justify-between rounded-lg bg-nx-bg/60 px-3 py-2">
                <span className="text-nx-muted">ریسک ساختاری</span>
                <LtrValue className="font-bold text-nx-text">
                  {(t.risk_pips ?? 0).toFixed(0)}p / {(t.risk_atr ?? 0).toFixed(1)}×ATR
                </LtrValue>
              </div>
              <div className="flex items-center justify-between rounded-lg bg-nx-bg/60 px-3 py-2">
                <span className="text-nx-muted">ریسک‌فری در</span>
                <LtrValue className="font-bold text-nx-profit">
                  {t.early_be_price ? formatPrice(t.symbol, t.early_be_price) : '—'}
                </LtrValue>
              </div>
              <div className="flex items-center justify-between rounded-lg bg-nx-bg/60 px-3 py-2">
                <span className="text-nx-muted">PF بک‌تست ورود</span>
                <LtrValue className="font-bold text-nx-gold">
                  {(t.backtest_profit_factor_at_entry ?? 0).toFixed(2)}
                </LtrValue>
              </div>
              <div className="flex items-center justify-between rounded-lg bg-nx-bg/60 px-3 py-2">
                <span className="text-nx-muted">بهترین/بدترین حرکت</span>
                <LtrValue className="font-bold text-nx-text">
                  {(t.max_favorable_r ?? 0).toFixed(1)}R / {(t.max_adverse_r ?? 0).toFixed(1)}R
                </LtrValue>
              </div>
              <div className="flex items-center justify-between rounded-lg bg-nx-bg/60 px-3 py-2">
                <span className="text-nx-muted">اعتبار سفارش</span>
                <span className="font-bold text-nx-text">
                  {t.pending_expires_at ? formatDateTimeFa(t.pending_expires_at) : '—'}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-lg bg-nx-bg/60 px-3 py-2">
                <span className="text-nx-muted">سیاست ریسک</span>
                <span className="font-bold text-nx-gold" dir="ltr">
                  {t.policy_version || '—'}
                </span>
              </div>
            </div>

            <div className="mt-4 rounded-xl border border-nx-gold/20 bg-nx-bg/50 p-3 text-xs leading-6 text-nx-muted">
              <strong className="text-nx-gold">تحلیل موتور Trading Hub 3.0: </strong>
              {t.rationale_fa}
            </div>
          </div>

          {/* 10-item Confluence Checklist */}
          <div className="nx-card rounded-2xl p-4">
            <h2 className="mb-3 text-sm font-bold text-nx-text">
              چک‌لیست ۱۰ آیتمی فیلتر سخت‌گیرانه (Trading Hub 3.0 High Accuracy)
            </h2>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {t.checklist.map((item) => (
                <CheckBadge key={item.key} ok={item.passed} label={item.label_fa} />
              ))}
            </div>
          </div>
        </div>

        {/* Right: Position Lifecycle Timeline + Private User Journal */}
        <div className="space-y-4 lg:col-span-5">
          <div className="nx-card rounded-2xl p-4">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-bold text-nx-text">
              <Clock className="h-4 w-4 text-nx-gold" />
              تایم‌لاین پیگیری پوزیشن و ریپلای‌های تلگرام
            </h2>
            <div className="space-y-3">
              {t.events.map((ev) => (
                <div
                  key={ev.id}
                  className="relative rounded-xl border border-nx-border/70 bg-nx-bg/55 p-3 text-xs"
                >
                  <div className="flex items-center justify-between gap-2">
                    <Badge variant={ev.event_type.includes('TP') ? 'profit' : ev.event_type.includes('SL') ? 'loss' : 'info'}>
                      {ev.event_type}
                    </Badge>
                    <span className="text-[11px] text-nx-muted">
                      {formatDateTimeFa(ev.source_timestamp)}
                    </span>
                  </div>
                  <p className="mt-2 leading-6 text-nx-text">{ev.description_fa}</p>
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-nx-muted">
                    {ev.price != null && (
                      <span>
                        قیمت: <LtrValue className="text-nx-text">{formatPrice(t.symbol, ev.price)}</LtrValue>
                      </span>
                    )}
                    {ev.telegram_reply_id && (
                      <span className="flex items-center gap-1 text-sky-400">
                        <Send className="h-3 w-3" />
                        ریپلای تلگرام: <LtrValue>{ev.telegram_reply_id}</LtrValue>
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Private Per-User Journal */}
          <form onSubmit={saveJournal} className="nx-card rounded-2xl p-4 space-y-3">
            <h2 className="flex items-center gap-2 text-sm font-bold text-nx-text">
              <BookOpen className="h-4 w-4 text-nx-gold" />
              ژورنال شخصی شما (کاملاً خصوصی)
            </h2>
            <div>
              <label className="mb-1 block text-xs text-nx-muted">ریسک شخصی شما (دلار)</label>
              <input
                type="number"
                dir="ltr"
                min={0}
                step="0.5"
                value={riskUsd}
                onChange={(e) => setRiskUsd(e.target.value)}
                placeholder="مثلاً 100"
                className="w-full rounded-xl border border-nx-border bg-nx-bg/70 px-3 py-2 text-xs text-nx-text"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-nx-muted">یادداشت و بررسی شخصی</label>
              <textarea
                rows={3}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="تحلیل شخصی شما درباره کیفیت ورود و مدیریت این پوزیشن..."
                className="w-full rounded-xl border border-nx-border bg-nx-bg/70 px-3 py-2 text-xs text-nx-text"
              />
            </div>
            {journalMsg && <p className="text-xs text-nx-profit">{journalMsg}</p>}
            <Button type="submit" variant="gold" size="sm" disabled={savingJournal}>
              <Save className="h-3.5 w-3.5" />
              {savingJournal ? 'در حال ذخیره...' : 'ذخیره یادداشت شخصی'}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
};
