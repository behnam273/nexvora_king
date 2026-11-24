import React from 'react';
import { AlertTriangle, CheckCircle2, Info, RefreshCw, Wifi, WifiOff } from 'lucide-react';
import type { WsStatus } from '../../lib/ws';

export const LtrValue: React.FC<{ children: React.ReactNode; className?: string }> = ({
  children,
  className = '',
}) => (
  <span dir="ltr" className={`ltr-num inline-block ${className}`}>
    {children}
  </span>
);

export const Badge: React.FC<{
  children: React.ReactNode;
  variant?: 'gold' | 'profit' | 'loss' | 'warning' | 'info' | 'neutral';
  className?: string;
}> = ({ children, variant = 'neutral', className = '' }) => {
  const styles: Record<string, string> = {
    gold: 'text-nx-gold bg-nx-gold/10 border-nx-gold/30',
    profit: 'text-nx-profit bg-nx-profit/12 border-nx-profit/30',
    loss: 'text-nx-loss bg-nx-loss/12 border-nx-loss/30',
    warning: 'text-nx-warning bg-nx-warning/12 border-nx-warning/30',
    info: 'text-sky-300 bg-sky-500/12 border-sky-500/30',
    neutral: 'text-nx-muted bg-slate-700/30 border-slate-600/40',
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-lg border px-2 py-0.5 text-xs font-medium ${styles[variant]} ${className}`}
    >
      {children}
    </span>
  );
};

export const Button: React.FC<
  React.ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: 'primary' | 'gold' | 'secondary' | 'danger' | 'ghost';
    size?: 'sm' | 'md';
  }
> = ({ variant = 'primary', size = 'md', className = '', children, ...props }) => {
  const variants: Record<string, string> = {
    primary: 'bg-indigo-600 hover:bg-indigo-500 text-white border border-indigo-400/30',
    gold: 'bg-gradient-to-l from-[#D2B46A] to-[#B99B57] hover:brightness-110 text-[#0B1220] font-bold',
    secondary: 'bg-nx-elevated hover:bg-nx-border text-nx-text border border-nx-border',
    danger: 'bg-nx-loss/20 hover:bg-nx-loss/30 text-nx-loss border border-nx-loss/40',
    ghost: 'bg-transparent hover:bg-nx-elevated/70 text-nx-muted hover:text-nx-text',
  };
  const sizes: Record<string, string> = {
    sm: 'px-3 py-1.5 text-xs rounded-lg',
    md: 'px-4 py-2 text-sm rounded-xl',
  };
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-2 transition disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-nx-gold/60 ${variants[variant]} ${sizes[size]} ${className}`}
    >
      {children}
    </button>
  );
};

export const StatCard: React.FC<{
  title: string;
  value: React.ReactNode;
  subtext?: React.ReactNode;
  icon?: React.ReactNode;
  accent?: 'gold' | 'profit' | 'loss' | 'info';
}> = ({ title, value, subtext, icon, accent = 'info' }) => {
  const accentBar: Record<string, string> = {
    gold: 'from-nx-gold/20 to-transparent border-nx-gold/25',
    profit: 'from-nx-profit/15 to-transparent border-nx-profit/25',
    loss: 'from-nx-loss/15 to-transparent border-nx-loss/25',
    info: 'from-indigo-500/15 to-transparent border-indigo-400/20',
  };
  return (
    <div className={`nx-card rounded-2xl p-4 bg-gradient-to-br ${accentBar[accent]}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs text-nx-muted">{title}</p>
          <div className="mt-2 text-2xl font-bold text-nx-text">{value}</div>
          {subtext && <div className="mt-1.5 text-xs text-nx-muted">{subtext}</div>}
        </div>
        {icon && (
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-nx-bg/60 border border-white/10">
            {icon}
          </div>
        )}
      </div>
    </div>
  );
};

export const Skeleton: React.FC<{ className?: string }> = ({ className = 'h-24 w-full' }) => (
  <div className={`animate-pulse rounded-2xl bg-nx-elevated/70 ${className}`} />
);

export const EmptyState: React.FC<{ title: string; description?: string; action?: React.ReactNode }> = ({
  title,
  description,
  action,
}) => (
  <div className="nx-card rounded-2xl p-8 text-center">
    <Info className="mx-auto mb-3 h-8 w-8 text-nx-muted/70" />
    <h3 className="text-base font-semibold text-nx-text">{title}</h3>
    {description && <p className="mt-1 text-sm text-nx-muted">{description}</p>}
    {action && <div className="mt-4">{action}</div>}
  </div>
);

export const ErrorState: React.FC<{ message: string; onRetry?: () => void }> = ({ message, onRetry }) => (
  <div className="nx-card rounded-2xl border-nx-loss/30 p-6 text-center">
    <AlertTriangle className="mx-auto mb-2 h-8 w-8 text-nx-loss" />
    <p className="text-sm font-medium text-nx-text">{message}</p>
    {onRetry && (
      <div className="mt-4">
        <Button variant="secondary" size="sm" onClick={onRetry}>
          <RefreshCw className="h-3.5 w-3.5" />
          تلاش مجدد
        </Button>
      </div>
    )}
  </div>
);

export const ConnectionStatus: React.FC<{ wsStatus: WsStatus; isOnline: boolean }> = ({
  wsStatus,
  isOnline,
}) => {
  if (!isOnline) {
    return (
      <Badge variant="loss">
        <WifiOff className="h-3.5 w-3.5" />
        آفلاین (داده کش‌شده)
      </Badge>
    );
  }
  if (wsStatus === 'connected') {
    return (
      <Badge variant="profit">
        <span className="h-2 w-2 rounded-full bg-nx-profit animate-pulse" />
        آنلاین
      </Badge>
    );
  }
  if (wsStatus === 'reconnecting') {
    return (
      <Badge variant="warning">
        <Wifi className="h-3.5 w-3.5 animate-pulse" />
        اتصال مجدد...
      </Badge>
    );
  }
  return (
    <Badge variant="neutral">
      <WifiOff className="h-3.5 w-3.5" />
      قطع ارتباط زنده
    </Badge>
  );
};

export const DemoBanner: React.FC<{ isDemo: boolean; message?: string }> = ({ isDemo, message }) => {
  if (!isDemo) return null;
  return (
    <div className="mb-4 flex items-start gap-3 rounded-2xl border border-nx-warning/35 bg-nx-warning/10 px-4 py-3 text-xs text-amber-200">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-nx-warning" />
      <div className="leading-6">
        <span className="font-bold text-nx-warning">حالت بازپخش آفلاین (Demo/Replay): </span>
        {message ||
          'این محیط به سایت‌های خارجی بازار/تلگرام متصل نیست؛ تمام محاسبات Trading Hub 3.0، بک‌تست و پیگیری پوزیشن واقعی است اما داده‌های قیمتی/خبری از شبیه‌ساز آفلاین خوانده شده‌اند. در سرور تولیدی با تنظیم .env به داده‌های رایگان لایو متصل می‌شود.'}
      </div>
    </div>
  );
};

export const CheckBadge: React.FC<{ ok: boolean; label: string }> = ({ ok, label }) => (
  <div
    className={`flex items-center justify-between rounded-xl border px-3 py-2 text-xs ${
      ok
        ? 'border-nx-profit/25 bg-nx-profit/10 text-nx-text'
        : 'border-nx-border bg-nx-bg/40 text-nx-muted'
    }`}
  >
    <span>{label}</span>
    {ok ? (
      <CheckCircle2 className="h-4 w-4 shrink-0 text-nx-profit" />
    ) : (
      <span className="h-2 w-2 rounded-full bg-nx-muted/40" />
    )}
  </div>
);
