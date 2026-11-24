import React, { useCallback, useEffect, useState } from 'react';
import { Newspaper, RefreshCw } from 'lucide-react';
import { apiFetch } from '../lib/api';
import type { NewsItem } from '../types';
import { Button, DemoBanner, EmptyState, ErrorState, Skeleton } from '../components/ui';
import { NewsCard } from '../components/news/NewsCard';

const CURRENCIES = ['ALL', 'USD', 'EUR', 'GBP', 'JPY', 'AUD', 'XAU'];
const IMPACTS = [
  { id: 'ALL', label: 'همه سطوح تاثیر' },
  { id: 'HIGH', label: 'فقط High Impact' },
  { id: 'MEDIUM', label: 'تاثیر متوسط' },
  { id: 'LOW', label: 'تاثیر کم' },
];

export const NewsPage: React.FC = () => {
  const [items, setItems] = useState<NewsItem[]>([]);
  const [currency, setCurrency] = useState('ALL');
  const [impact, setImpact] = useState('ALL');
  const [minPct, setMinPct] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setError('');
      const params = new URLSearchParams();
      if (currency !== 'ALL') params.set('currency', currency);
      if (impact !== 'ALL') params.set('impact', impact);
      if (minPct > 0) params.set('min_impact_pct', String(minPct));
      const res = await apiFetch<{ items: NewsItem[] }>(`/api/v1/news?${params.toString()}`);
      setItems(res.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت اخبار');
    } finally {
      setLoading(false);
    }
  }, [currency, impact, minPct]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-4">
      <DemoBanner isDemo={items.some((i) => i.is_demo_data)} />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-extrabold text-nx-text">
            <Newspaper className="h-5 w-5 text-nx-gold" />
            هوش خبری بازارهای مالی (فارسی + درصد تاثیر)
          </h1>
          <p className="mt-0.5 text-xs text-nx-muted">
            تجمیع منابع معتبر (FXStreet، ForexLive، Investing.com، فدرال رزرو، ECB، BoE) با حذف اخبار تکراری و محاسبه ۵ امتیاز مستقل
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={load}>
          <RefreshCw className="h-3.5 w-3.5" />
          بروزرسانی
        </Button>
      </div>

      {/* Filters */}
      <div className="nx-card flex flex-wrap items-center gap-3 rounded-2xl p-3.5">
        <div className="flex flex-wrap items-center gap-1.5">
          {CURRENCIES.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => setCurrency(c)}
              className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition ${
                currency === c
                  ? 'border-nx-gold bg-nx-gold/15 text-nx-gold'
                  : 'border-nx-border bg-nx-bg/50 text-nx-muted'
              }`}
            >
              {c === 'ALL' ? 'همه ارزها' : c}
            </button>
          ))}
        </div>

        <select
          value={impact}
          onChange={(e) => setImpact(e.target.value)}
          className="rounded-xl border border-nx-border bg-nx-bg px-3 py-1.5 text-xs text-nx-text"
        >
          {IMPACTS.map((im) => (
            <option key={im.id} value={im.id}>
              {im.label}
            </option>
          ))}
        </select>

        <label className="flex items-center gap-2 text-xs text-nx-muted">
          <span>حداقل درصد تاثیر:</span>
          <input
            type="range"
            min={0}
            max={90}
            step={5}
            value={minPct}
            onChange={(e) => setMinPct(Number(e.target.value))}
            className="accent-nx-gold"
          />
          <span className="font-mono text-nx-gold">{minPct}%</span>
        </label>
      </div>

      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-44" />
          <Skeleton className="h-44" />
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : items.length === 0 ? (
        <EmptyState title="خبری با این فیلتر پیدا نشد" />
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {items.map((n) => (
            <NewsCard key={n.id} item={n} />
          ))}
        </div>
      )}
    </div>
  );
};
