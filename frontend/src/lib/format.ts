export const SYMBOL_DISPLAY: Record<string, string> = {
  EURUSD: 'EUR/USD',
  GBPUSD: 'GBP/USD',
  USDJPY: 'USD/JPY',
  AUDUSD: 'AUD/USD',
  EURGBP: 'EUR/GBP',
  XAUUSD: 'XAU/USD',
};

export const SYMBOL_DIGITS: Record<string, number> = {
  EURUSD: 5,
  GBPUSD: 5,
  USDJPY: 3,
  AUDUSD: 5,
  EURGBP: 5,
  XAUUSD: 2,
};

export const RISK_TIER_FA: Record<string, { label: string; short: string; color: string }> = {
  SAFE: {
    label: '۴ ساعته — حالت امن',
    short: 'امن (4H)',
    color: 'text-nx-profit bg-nx-profit/10 border-nx-profit/30',
  },
  MEDIUM_RISK: {
    label: '۱۵ دقیقه — ریسک متوسط',
    short: 'ریسک متوسط (15m)',
    color: 'text-nx-warning bg-nx-warning/10 border-nx-warning/30',
  },
  HIGH_RISK: {
    label: '۵ دقیقه — ریسک بالا',
    short: 'ریسک بالا (5m)',
    color: 'text-nx-loss bg-nx-loss/10 border-nx-loss/30',
  },
};

export const STATUS_FA: Record<string, { label: string; color: string }> = {
  PENDING_LIMIT: { label: 'در انتظار ورود (Limit)', color: 'text-nx-warning bg-nx-warning/10 border-nx-warning/30' },
  ACTIVE: { label: 'پوزیشن فعال', color: 'text-sky-400 bg-sky-500/10 border-sky-500/30' },
  TP1_HIT: { label: 'TP1 زده شد (ریسک‌فری BE)', color: 'text-nx-profit bg-nx-profit/15 border-nx-profit/35' },
  TP2_HIT: { label: 'TP2 زده شد (SL روی TP1)', color: 'text-nx-profit bg-nx-profit/20 border-nx-profit/45' },
  CLOSED_WIN: { label: 'بسته شده با سود', color: 'text-nx-profit bg-nx-profit/15 border-nx-profit/35' },
  CLOSED_LOSS: { label: 'حد ضرر خورده', color: 'text-nx-loss bg-nx-loss/15 border-nx-loss/35' },
  CLOSED_BE: { label: 'سر‌به‌سر (BE)', color: 'text-nx-muted bg-slate-500/15 border-slate-500/30' },
  EXPIRED: { label: 'منقضی شده', color: 'text-nx-muted bg-slate-500/10 border-slate-500/25' },
  CANCELLED: { label: 'لغو شده', color: 'text-nx-muted bg-slate-500/10 border-slate-500/25' },
};

export const CATEGORY_FA: Record<string, string> = {
  central_bank: 'بانک مرکزی',
  inflation: 'تورم و CPI',
  employment: 'اشتغال و NFP',
  gdp_growth: 'رشد اقتصادی',
  geopolitics: 'ژئوپلیتیک',
  gold_commodities: 'طلا و کالاها',
  forex_technical: 'فارکس',
  macro: 'اقتصاد کلان',
};

export function formatPrice(symbol: string, val: number | null | undefined): string {
  if (val === null || val === undefined || Number.isNaN(val)) return '-';
  const d = SYMBOL_DIGITS[symbol] ?? 5;
  return val.toFixed(d);
}

export function formatSignedUsd(val: number): string {
  const sign = val > 0 ? '+' : val < 0 ? '-' : '';
  return `${sign}$${Math.abs(val).toFixed(2)}`;
}

export function formatSignedR(val: number): string {
  const sign = val > 0 ? '+' : '';
  return `${sign}${val.toFixed(2)}R`;
}

export function formatDateTimeFa(iso: string | null | undefined): string {
  if (!iso) return '-';
  try {
    const dt = new Date(iso);
    return new Intl.DateTimeFormat('fa-IR', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(dt);
  } catch {
    return iso;
  }
}

export function formatRelativeFa(iso: string): string {
  try {
    const diffSec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (diffSec < 60) return 'لحظاتی پیش';
    const min = Math.floor(diffSec / 60);
    if (min < 60) return `${min} دقیقه پیش`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr} ساعت پیش`;
    const days = Math.floor(hr / 24);
    return `${days} روز پیش`;
  } catch {
    return '-';
  }
}
