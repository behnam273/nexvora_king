import React, { useCallback, useEffect, useState } from 'react';
import { CalendarDays, ExternalLink } from 'lucide-react';
import { apiFetch } from '../lib/api';
import type { EconomicEvent } from '../types';
import { formatDateTimeFa, SYMBOL_DISPLAY } from '../lib/format';
import { Badge, DemoBanner, EmptyState, ErrorState, LtrValue, Skeleton } from '../components/ui';

export const CalendarPage: React.FC = () => {
  const [items, setItems] = useState<EconomicEvent[]>([]);
  const [currency, setCurrency] = useState('ALL');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setError('');
      const params = new URLSearchParams();
      if (currency !== 'ALL') params.set('currency', currency);
      if (statusFilter !== 'ALL') params.set('status', statusFilter);
      const res = await apiFetch<{ items: EconomicEvent[] }>(`/api/v1/calendar?${params.toString()}`);
      setItems(res.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت تقویم اقتصادی');
    } finally {
      setLoading(false);
    }
  }, [currency, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-4">
      <DemoBanner isDemo={items.some((x) => x.is_demo_data)} />

      <div>
        <h1 className="flex items-center gap-2 text-lg font-extrabold text-nx-text">
          <CalendarDays className="h-5 w-5 text-nx-gold" />
          تقویم اقتصادی فارکس (با تفکیک زمان‌بندی‌شده و منتشرشده)
        </h1>
        <p className="mt-0.5 text-xs text-nx-muted">
          رویدادهای کلیدی اقتصاد کلان مؤثر بر ۶ نماد مجاز + گارد خبری خودکار ۳۰ دقیقه قبل و بعد از اخبار High Impact
        </p>
      </div>

      <div className="nx-card flex flex-wrap items-center gap-3 rounded-2xl p-3.5">
        <select
          value={currency}
          onChange={(e) => setCurrency(e.target.value)}
          className="rounded-xl border border-nx-border bg-nx-bg px-3 py-1.5 text-xs text-nx-text"
        >
          <option value="ALL">همه ارزها</option>
          {['USD', 'EUR', 'GBP', 'JPY', 'AUD'].map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-xl border border-nx-border bg-nx-bg px-3 py-1.5 text-xs text-nx-text"
        >
          <option value="ALL">همه وضعیت‌ها</option>
          <option value="SCHEDULED">زمان‌بندی‌شده (پیش‌رو)</option>
          <option value="PUBLISHED">منتشرشده (عدد واقعی ثبت شده)</option>
        </select>
      </div>

      {loading ? (
        <Skeleton className="h-72" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : items.length === 0 ? (
        <EmptyState title="رویدادی یافت نشد" />
      ) : (
        <div className="nx-card rounded-2xl p-4 overflow-x-auto">
          <table className="w-full text-right text-xs">
            <thead>
              <tr className="border-b border-nx-border text-nx-muted">
                <th className="pb-2.5">رویداد اقتصادی</th>
                <th className="pb-2.5">ارز / نمادها</th>
                <th className="pb-2.5">تاثیر</th>
                <th className="pb-2.5">وضعیت</th>
                <th className="pb-2.5">زمان</th>
                <th className="pb-2.5">واقعی (Actual)</th>
                <th className="pb-2.5">پیش‌بینی</th>
                <th className="pb-2.5">قبلی</th>
                <th className="pb-2.5">منبع</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {items.map((ev) => (
                <tr key={ev.id} className="hover:bg-nx-elevated/40">
                  <td className="py-3 max-w-xs">
                    <div className="font-bold text-nx-text">{ev.event_name_fa}</div>
                    <div className="text-[11px] text-nx-muted mt-0.5">{ev.surprise_note_fa}</div>
                  </td>
                  <td className="py-3">
                    <Badge variant="gold">{ev.currency}</Badge>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {ev.related_symbols.slice(0, 3).map((s) => (
                        <span key={s} className="text-[10px] text-nx-muted">
                          <LtrValue>{SYMBOL_DISPLAY[s] || s}</LtrValue>
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="py-3">
                    <Badge variant={ev.importance === 'HIGH' ? 'loss' : 'warning'}>
                      {ev.impact_pct}%
                    </Badge>
                  </td>
                  <td className="py-3">
                    <Badge variant={ev.status === 'PUBLISHED' ? 'profit' : 'info'}>
                      {ev.status === 'PUBLISHED' ? 'منتشرشده' : 'زمان‌بندی‌شده'}
                    </Badge>
                  </td>
                  <td className="py-3 text-nx-muted">{formatDateTimeFa(ev.scheduled_at)}</td>
                  <td className="py-3 font-bold text-nx-gold">
                    <LtrValue>{ev.actual ?? 'منتشر نشده'}</LtrValue>
                  </td>
                  <td className="py-3">
                    <LtrValue>{ev.forecast ?? '-'}</LtrValue>
                  </td>
                  <td className="py-3 text-nx-muted">
                    <LtrValue>{ev.previous ?? '-'}</LtrValue>
                  </td>
                  <td className="py-3">
                    {ev.source_url ? (
                      <a
                        href={ev.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-nx-gold hover:underline"
                      >
                        {ev.source_name}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    ) : (
                      ev.source_name
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
