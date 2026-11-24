import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Download, History, Search } from 'lucide-react';
import { apiFetch } from '../lib/api';
import type { SignalTrade } from '../types';
import {
  formatDateTimeFa,
  formatPrice,
  formatSignedR,
  formatSignedUsd,
  RISK_TIER_FA,
  STATUS_FA,
  SYMBOL_DISPLAY,
} from '../lib/format';
import { Badge, Button, EmptyState, ErrorState, LtrValue, Skeleton } from '../components/ui';

export const TradeHistoryPage: React.FC = () => {
  const [items, setItems] = useState<SignalTrade[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [symbol, setSymbol] = useState('');
  const [timeframe, setTimeframe] = useState('');
  const [outcome, setOutcome] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setError('');
      const params = new URLSearchParams({ page: String(page), page_size: '15' });
      if (search.trim()) params.set('search', search.trim());
      if (symbol) params.set('symbol', symbol);
      if (timeframe) params.set('timeframe', timeframe);
      if (outcome) params.set('outcome', outcome);
      const res = await apiFetch<{ total: number; items: SignalTrade[] }>(
        `/api/v1/trades/history?${params.toString()}`
      );
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت تاریخچه');
    } finally {
      setLoading(false);
    }
  }, [page, search, symbol, timeframe, outcome]);

  useEffect(() => {
    load();
  }, [load]);

  const exportUrl = () => {
    const params = new URLSearchParams();
    if (symbol) params.set('symbol', symbol);
    if (timeframe) params.set('timeframe', timeframe);
    if (outcome) params.set('outcome', outcome);
    return `/api/v1/trades/export.csv?${params.toString()}`;
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-extrabold text-nx-text">
            <History className="h-5 w-5 text-nx-gold" />
            تاریخچه جامع معاملات و سیگنال‌ها
          </h1>
          <p className="text-xs text-nx-muted">مجموع رکوردها: {total}</p>
        </div>
        <a href={exportUrl()} download="nexvora_trades.csv">
          <Button variant="secondary" size="sm">
            <Download className="h-3.5 w-3.5" />
            خروجی CSV امن
          </Button>
        </a>
      </div>

      {/* Filters */}
      <div className="nx-card grid grid-cols-1 gap-2.5 rounded-2xl p-3.5 sm:grid-cols-2 lg:grid-cols-4">
        <div className="relative">
          <Search className="pointer-events-none absolute right-3 top-2.5 h-4 w-4 text-nx-muted" />
          <input
            type="text"
            value={search}
            onChange={(e) => {
              setPage(1);
              setSearch(e.target.value);
            }}
            placeholder="جستجوی کد معامله یا ماژول..."
            className="w-full rounded-xl border border-nx-border bg-nx-bg pr-9 pl-3 py-2 text-xs text-nx-text"
          />
        </div>
        <select
          value={symbol}
          onChange={(e) => {
            setPage(1);
            setSymbol(e.target.value);
          }}
          className="rounded-xl border border-nx-border bg-nx-bg px-3 py-2 text-xs text-nx-text"
        >
          <option value="">همه ۶ جفت‌ارز</option>
          {Object.keys(SYMBOL_DISPLAY).map((s) => (
            <option key={s} value={s}>
              {SYMBOL_DISPLAY[s]}
            </option>
          ))}
        </select>
        <select
          value={timeframe}
          onChange={(e) => {
            setPage(1);
            setTimeframe(e.target.value);
          }}
          className="rounded-xl border border-nx-border bg-nx-bg px-3 py-2 text-xs text-nx-text"
        >
          <option value="">همه تایم‌فریم‌ها</option>
          <option value="4H">4H — حالت امن</option>
          <option value="15m">15m — ریسک متوسط</option>
          <option value="5m">5m — ریسک بالا</option>
        </select>
        <select
          value={outcome}
          onChange={(e) => {
            setPage(1);
            setOutcome(e.target.value);
          }}
          className="rounded-xl border border-nx-border bg-nx-bg px-3 py-2 text-xs text-nx-text"
        >
          <option value="">همه نتایج</option>
          <option value="WIN">برنده (WIN)</option>
          <option value="LOSS">ضرر (LOSS)</option>
          <option value="BE">سر‌به‌سر (BE)</option>
          <option value="OPEN">باز / فعال</option>
          <option value="CANCELLED">منقضی / لغوشده</option>
        </select>
      </div>

      {loading ? (
        <Skeleton className="h-72" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : items.length === 0 ? (
        <EmptyState title="معامله‌ای با این فیلتر یافت نشد" />
      ) : (
        <div className="nx-card rounded-2xl p-4 overflow-x-auto">
          <table className="w-full text-right text-xs">
            <thead>
              <tr className="border-b border-nx-border text-nx-muted">
                <th className="pb-2.5">کد</th>
                <th className="pb-2.5">نماد</th>
                <th className="pb-2.5">تایم‌فریم</th>
                <th className="pb-2.5">جهت</th>
                <th className="pb-2.5">ماژول / امتیاز</th>
                <th className="pb-2.5">ورود</th>
                <th className="pb-2.5">تارگت‌ها</th>
                <th className="pb-2.5">نتیجه (R)</th>
                <th className="pb-2.5">سود/زیان ($)</th>
                <th className="pb-2.5">وضعیت</th>
                <th className="pb-2.5">زمان</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {items.map((t) => {
                const st = STATUS_FA[t.status] || { label: t.status, color: '' };
                const rf = RISK_TIER_FA[t.risk_tier];
                return (
                  <tr key={t.id} className="hover:bg-nx-elevated/40">
                    <td className="py-2.5">
                      <Link to={`/trades/${t.id}`} className="text-nx-gold hover:underline">
                        <LtrValue>{t.trade_code}</LtrValue>
                      </Link>
                    </td>
                    <td className="py-2.5 font-bold">
                      <LtrValue>{SYMBOL_DISPLAY[t.symbol] || t.symbol}</LtrValue>
                    </td>
                    <td className="py-2.5">
                      <span className={`rounded-md border px-1.5 py-0.5 text-[10px] ${rf?.color || ''}`}>
                        {rf?.short}
                      </span>
                    </td>
                    <td className="py-2.5">
                      <Badge variant={t.direction === 'LONG' ? 'profit' : 'loss'}>
                        {t.direction}
                      </Badge>
                    </td>
                    <td className="py-2.5">
                      <span>{t.entry_module}</span>{' '}
                      <LtrValue className="text-nx-gold">({t.confluence_score})</LtrValue>
                    </td>
                    <td className="py-2.5">
                      <LtrValue>{formatPrice(t.symbol, t.fill_price || t.entry_price)}</LtrValue>
                    </td>
                    <td className="py-2.5 text-[11px]">
                      <span className={t.tp1_hit ? 'text-nx-profit font-bold' : 'text-nx-muted'}>TP1</span> /{' '}
                      <span className={t.tp2_hit ? 'text-nx-profit font-bold' : 'text-nx-muted'}>TP2</span> /{' '}
                      <span className={t.tp3_hit ? 'text-nx-gold font-bold' : 'text-nx-muted'}>TP3</span>
                    </td>
                    <td className="py-2.5">
                      <LtrValue className={t.realized_r >= 0 ? 'text-nx-profit font-bold' : 'text-nx-loss font-bold'}>
                        {formatSignedR(t.realized_r)}
                      </LtrValue>
                    </td>
                    <td className="py-2.5">
                      <LtrValue className={t.realized_pnl_usd >= 0 ? 'text-nx-profit font-bold' : 'text-nx-loss font-bold'}>
                        {formatSignedUsd(t.realized_pnl_usd)}
                      </LtrValue>
                    </td>
                    <td className="py-2.5">
                      <span className={`rounded-md border px-1.5 py-0.5 text-[10px] ${st.color}`}>
                        {st.label}
                      </span>
                    </td>
                    <td className="py-2.5 text-[11px] text-nx-muted">
                      {formatDateTimeFa(t.created_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* Pagination */}
          {total > 15 && (
            <div className="mt-4 flex items-center justify-between border-t border-white/5 pt-3 text-xs">
              <span className="text-nx-muted">
                صفحه {page} از {Math.ceil(total / 15)}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  قبلی
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={page * 15 >= total}
                  onClick={() => setPage((p) => p + 1)}
                >
                  بعدی
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
