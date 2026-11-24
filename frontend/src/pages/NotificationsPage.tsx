import React, { useCallback, useEffect, useState } from 'react';
import { Bell, CheckCheck } from 'lucide-react';
import { apiFetch } from '../lib/api';
import type { NotificationItem } from '../types';
import { formatDateTimeFa } from '../lib/format';
import { Badge, Button, EmptyState, ErrorState, Skeleton } from '../components/ui';

export const NotificationsPage: React.FC = () => {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setError('');
      const res = await apiFetch<NotificationItem[]>('/api/v1/notifications');
      setItems(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت اعلان‌ها');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const unread = items.filter((i) => !i.is_read).length;

  const markAllRead = async () => {
    await apiFetch('/api/v1/notifications/read-all', { method: 'POST' });
    load();
  };

  const markRead = async (id: number) => {
    await apiFetch(`/api/v1/notifications/${id}/read`, { method: 'POST' });
    load();
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-extrabold text-nx-text">
            <Bell className="h-5 w-5 text-nx-gold" />
            مرکز اعلان‌ها و رویدادهای پوزیشن
          </h1>
          <p className="text-xs text-nx-muted">خوانده‌نشده: {unread}</p>
        </div>
        {unread > 0 && (
          <Button variant="secondary" size="sm" onClick={markAllRead}>
            <CheckCheck className="h-4 w-4" />
            علامت‌گذاری همه به‌عنوان خوانده‌شده
          </Button>
        )}
      </div>

      {loading ? (
        <Skeleton className="h-72" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : items.length === 0 ? (
        <EmptyState title="اعلانی ثبت نشده است" />
      ) : (
        <div className="space-y-2.5">
          {items.map((n) => (
            <div
              key={n.id}
              onClick={() => !n.is_read && markRead(n.id)}
              className={`nx-card cursor-pointer rounded-2xl p-4 transition ${
                n.is_read ? 'opacity-75' : 'border-nx-gold/40 bg-nx-elevated/40'
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  {!n.is_read && <span className="h-2 w-2 rounded-full bg-nx-gold" />}
                  <h3 className="text-sm font-bold text-nx-text">{n.title_fa}</h3>
                  <Badge
                    variant={
                      n.severity === 'danger'
                        ? 'loss'
                        : n.severity === 'warning'
                          ? 'warning'
                          : n.severity === 'success'
                            ? 'profit'
                            : 'info'
                    }
                  >
                    {n.kind}
                  </Badge>
                </div>
                <span className="text-[11px] text-nx-muted">{formatDateTimeFa(n.created_at)}</span>
              </div>
              <p className="mt-1.5 text-xs leading-6 text-nx-muted">{n.message_fa}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
