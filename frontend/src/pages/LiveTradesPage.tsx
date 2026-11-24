import React, { useCallback, useEffect, useState } from 'react';
import { Activity, Filter, RefreshCw } from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import type { SignalTrade } from '../types';
import { SYMBOL_DISPLAY } from '../lib/format';
import { Button, DemoBanner, EmptyState, ErrorState, Skeleton } from '../components/ui';
import { TradeCard } from '../components/trades/TradeCard';

const SYMBOLS = ['ALL', 'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'EURGBP', 'XAUUSD'];
const RISK_TIERS = [
  { id: 'ALL', label: 'همه تایم‌فریم‌ها' },
  { id: 'SAFE', label: '4H — حالت امن' },
  { id: 'MEDIUM_RISK', label: '15m — ریسک متوسط' },
  { id: 'HIGH_RISK', label: '5m — ریسک بالا' },
];

export const LiveTradesPage: React.FC = () => {
  const { lastWsEvent } = useAuth();
  const [items, setItems] = useState<SignalTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [symbol, setSymbol] = useState('ALL');
  const [riskTier, setRiskTier] = useState('ALL');

  const load = useCallback(async () => {
    try {
      setError('');
      const params = new URLSearchParams();
      if (symbol !== 'ALL') params.set('symbol', symbol);
      if (riskTier !== 'ALL') params.set('risk_tier', riskTier);
      const res = await apiFetch<{ items: SignalTrade[] }>(`/api/v1/trades/live?${params.toString()}`);
      setItems(res.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در بارگذاری معاملات زنده');
    } finally {
      setLoading(false);
    }
  }, [symbol, riskTier]);

  useEffect(() => {
    load();
  }, [load, lastWsEvent]);

  const anyDemo = items.some((x) => x.is_demo_data);

  return (
    <div className="space-y-4">
      <DemoBanner isDemo={anyDemo} />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-extrabold text-nx-text">
            <Activity className="h-5 w-5 text-nx-gold" />
            معاملات زنده و پیگیری پله‌ای پوزیشن‌ها
          </h1>
          <p className="mt-0.5 text-xs text-nx-muted">
            پیگیری کامل از لحظه ثبت Limit تا فعال‌شدن، TP1 (۵۰٪ + ریسک‌فری BE)، TP2 (۳۰٪ + انتقال SL به TP1) و TP3
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={load}>
          <RefreshCw className="h-3.5 w-3.5" />
          به‌روزرسانی
        </Button>
      </div>

      {/* Filters */}
      <div className="nx-card flex flex-wrap items-center gap-3 rounded-2xl p-3.5">
        <span className="flex items-center gap-1 text-xs text-nx-muted">
          <Filter className="h-3.5 w-3.5" />
          فیلتر:
        </span>
        <select
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="rounded-xl border border-nx-border bg-nx-bg px-3 py-1.5 text-xs text-nx-text"
        >
          {SYMBOLS.map((s) => (
            <option key={s} value={s}>
              {s === 'ALL' ? 'همه ۶ جفت‌ارز مجاز' : SYMBOL_DISPLAY[s]}
            </option>
          ))}
        </select>

        <div className="flex flex-wrap items-center gap-1.5">
          {RISK_TIERS.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => setRiskTier(r.id)}
              className={`rounded-xl border px-3 py-1.5 text-xs transition ${
                riskTier === r.id
                  ? 'border-nx-gold/60 bg-nx-gold/15 text-nx-gold font-bold'
                  : 'border-nx-border bg-nx-bg/50 text-nx-muted hover:text-nx-text'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Skeleton className="h-56" />
          <Skeleton className="h-56" />
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : items.length === 0 ? (
        <EmptyState
          title="معامله فعالی با این فیلتر وجود ندارد"
          description="موتور Trading Hub 3.0 تنها ستاپ‌هایی را فعال می‌کند که از فیلترهای سخت‌گیرانه ADX، بایاس HTF، سوییپ، CHoCH قوی و امتیاز کانفلوئنس عبور کنند."
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {items.map((t) => (
            <TradeCard key={t.id} trade={t} />
          ))}
        </div>
      )}
    </div>
  );
};
