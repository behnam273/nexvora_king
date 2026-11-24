import React, { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import {
  Activity,
  BarChart3,
  Bell,
  CalendarDays,
  Globe2,
  History,
  LayoutDashboard,
  LogOut,
  Menu,
  Newspaper,
  Settings,
  Shield,
  X,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { apiFetch } from '../../lib/api';
import type { NotificationItem } from '../../types';
import { ConnectionStatus } from '../ui';

const NAV_ITEMS = [
  { to: '/', label: 'داشبورد', icon: LayoutDashboard, end: true },
  { to: '/trades/live', label: 'معاملات زنده و پیگیری', icon: Activity },
  { to: '/trades/history', label: 'تاریخچه معاملات', icon: History },
  { to: '/analytics', label: 'تحلیل عملکرد و بک‌تست', icon: BarChart3 },
  { to: '/news', label: 'اخبار بازار (فارسی)', icon: Newspaper },
  { to: '/calendar', label: 'تقویم اقتصادی', icon: CalendarDays },
  { to: '/market', label: 'نمای ۶ جفت‌ارز', icon: Globe2 },
  { to: '/notifications', label: 'اعلان‌ها', icon: Bell },
  { to: '/settings', label: 'پروفایل و امنیت', icon: Settings },
];

export const AppShell: React.FC = () => {
  const { user, wsStatus, isOnline, logout, lastWsEvent } = useAuth();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const navigate = useNavigate();

  const isAdmin = user?.role === 'ADMIN' || user?.role === 'SUPER_ADMIN';

  useEffect(() => {
    apiFetch<NotificationItem[]>('/api/v1/notifications?unread_only=true&limit=50')
      .then((rows) => setUnreadCount(rows.length))
      .catch(() => {});
  }, [lastWsEvent]);

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const renderLinks = (onSelect?: () => void) => (
    <nav className="flex-1 space-y-1 px-3 py-4" aria-label="منوی اصلی">
      {NAV_ITEMS.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onSelect}
            className={({ isActive }) =>
              `flex items-center justify-between rounded-xl px-3.5 py-2.5 text-sm font-medium transition ${
                isActive
                  ? 'bg-gradient-to-l from-indigo-600/80 to-indigo-500/30 text-white border border-indigo-400/30 shadow-md'
                  : 'text-nx-muted hover:bg-nx-elevated/70 hover:text-nx-text'
              }`
            }
          >
            <span className="flex items-center gap-3">
              <Icon className="h-4 w-4 shrink-0" />
              <span>{item.label}</span>
            </span>
            {item.to === '/notifications' && unreadCount > 0 && (
              <span className="rounded-full bg-nx-loss px-1.5 py-0.5 text-[10px] font-bold text-white">
                {unreadCount}
              </span>
            )}
          </NavLink>
        );
      })}
      {isAdmin && (
        <NavLink
          to="/admin"
          onClick={onSelect}
          className={({ isActive }) =>
            `mt-3 flex items-center gap-3 rounded-xl border px-3.5 py-2.5 text-sm font-medium transition ${
              isActive
                ? 'border-nx-gold/50 bg-nx-gold/15 text-nx-gold'
                : 'border-nx-gold/20 text-nx-softgold hover:bg-nx-gold/10'
            }`
          }
        >
          <Shield className="h-4 w-4 shrink-0" />
          <span>مرکز کنترل ادمین</span>
        </NavLink>
      )}
    </nav>
  );

  return (
    <div className="min-h-screen bg-nx-bg text-nx-text flex flex-col lg:flex-row">
      {/* Desktop Sidebar */}
      <aside className="hidden lg:flex lg:w-64 lg:shrink-0 lg:flex-col border-l border-nx-border/70 bg-nx-surface/90 sticky top-0 h-screen">
        <div className="flex items-center gap-3 border-b border-nx-border/60 px-5 py-4">
          <img src="/icons/nexvora-icon.svg" alt="NEXVORA" className="h-10 w-10 rounded-xl" />
          <div>
            <div className="text-base font-extrabold tracking-wide text-nx-text">NEXVORA</div>
            <div className="text-[11px] text-nx-gold">Trading Hub 3.0 SMC</div>
          </div>
        </div>

        {renderLinks()}

        <div className="border-t border-nx-border/60 p-4">
          <div className="rounded-xl bg-nx-bg/60 p-3 text-xs">
            <div className="font-semibold text-nx-text truncate">{user?.full_name}</div>
            <div className="mt-0.5 text-[11px] text-nx-muted truncate" dir="ltr">
              {user?.email}
            </div>
            <div className="mt-2 flex items-center justify-between">
              <span className="rounded-md bg-nx-gold/15 px-2 py-0.5 text-[10px] font-bold text-nx-gold">
                {user?.role}
              </span>
              <button
                onClick={handleLogout}
                className="inline-flex items-center gap-1 text-nx-loss hover:underline"
              >
                <LogOut className="h-3.5 w-3.5" />
                خروج
              </button>
            </div>
          </div>
        </div>
      </aside>

      {/* Mobile Drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <div
            className="fixed inset-0 bg-black/70 backdrop-blur-sm"
            onClick={() => setDrawerOpen(false)}
          />
          <div className="relative z-10 flex w-72 max-w-[85vw] flex-col bg-nx-surface border-l border-nx-border h-full">
            <div className="flex items-center justify-between border-b border-nx-border/60 px-4 py-4">
              <div className="flex items-center gap-2.5">
                <img src="/icons/nexvora-icon.svg" alt="NEXVORA" className="h-8 w-8 rounded-lg" />
                <span className="font-extrabold">NEXVORA</span>
              </div>
              <button
                onClick={() => setDrawerOpen(false)}
                className="rounded-lg p-1.5 text-nx-muted hover:bg-nx-elevated"
                aria-label="بستن منو"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            {renderLinks(() => setDrawerOpen(false))}
            <div className="border-t border-nx-border/60 p-4">
              <button
                onClick={handleLogout}
                className="flex w-full items-center justify-center gap-2 rounded-xl border border-nx-loss/35 bg-nx-loss/10 py-2 text-sm text-nx-loss"
              >
                <LogOut className="h-4 w-4" />
                خروج از حساب کاربری
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex min-w-0 flex-1 flex-col pb-20 lg:pb-0">
        {/* Topbar */}
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-nx-border/70 bg-nx-bg/85 px-4 py-3 backdrop-blur-md lg:px-6">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setDrawerOpen(true)}
              className="rounded-xl border border-nx-border bg-nx-surface p-2 text-nx-text lg:hidden"
              aria-label="باز کردن منو"
            >
              <Menu className="h-5 w-5" />
            </button>
            <div>
              <div className="text-sm font-bold text-nx-text">
                سلام، {user?.full_name || 'معامله‌گر حرفه‌ای'}
              </div>
              <div className="hidden text-[11px] text-nx-muted sm:block">
                فیلتر سخت‌گیرانه Trading Hub 3.0 روی ۶ جفت‌ارز فارکس و طلا (4H / 15m / 5m)
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <ConnectionStatus wsStatus={wsStatus} isOnline={isOnline} />
            <Link
              to="/notifications"
              className="relative rounded-xl border border-nx-border bg-nx-surface p-2 text-nx-muted hover:text-nx-gold"
              aria-label="اعلان‌ها"
            >
              <Bell className="h-4 w-4" />
              {unreadCount > 0 && (
                <span className="absolute -top-1 -left-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-nx-loss px-1 text-[10px] font-bold text-white">
                  {unreadCount}
                </span>
              )}
            </Link>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1540px] flex-1 p-4 lg:p-6">
          <Outlet />
        </main>
      </div>

      {/* Mobile Bottom Navigation */}
      <nav
        className="fixed bottom-0 inset-x-0 z-40 grid grid-cols-5 border-t border-nx-border bg-nx-surface/95 px-1 py-1.5 backdrop-blur-md lg:hidden"
        aria-label="ناوبری موبایل"
      >
        {[
          { to: '/', label: 'خانه', icon: LayoutDashboard, end: true },
          { to: '/trades/live', label: 'معاملات', icon: Activity },
          { to: '/analytics', label: 'عملکرد', icon: BarChart3 },
          { to: '/news', label: 'اخبار', icon: Newspaper },
          { to: '/settings', label: 'حساب', icon: Settings },
        ].map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex flex-col items-center justify-center gap-0.5 rounded-xl py-1 text-[10px] font-medium ${
                  isActive ? 'text-nx-gold bg-nx-gold/10' : 'text-nx-muted'
                }`
              }
            >
              <Icon className="h-4 w-4" />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </nav>
    </div>
  );
};
