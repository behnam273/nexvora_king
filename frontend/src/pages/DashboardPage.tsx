import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  Award,
  CheckCircle2,
  Newspaper,
  Send,
  ShieldAlert,
  TrendingUp,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import type { CandlePoint, KPIStats, NewsItem, SignalTrade } from '../types';
import {
  formatPrice,
  formatSignedR,
  formatSignedUsd,
  RISK_TIER_FA,
  STATUS_FA,
  SYMBOL_DIGITS,
  SYMBOL_DISPLAY,
} from '../lib/format';
import { Badge, DemoBanner, ErrorState, LtrValue, Skeleton, StatCard } from '../components/ui';
import { CandleChart } from '../components/charts/CandleChart';
import { EquityChart } from '../components/charts/EquityChart';
import { TradeCard } from '../components/trades/TradeCard';
import { NewsCard } from '../components/news/NewsCard';

interface DashboardData {
  server_time: string;
  is_demo_data: boolean;
  demo_notice_fa: string;
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
  active_trades: SignalTrade[];
  recent_closed: SignalTrade[];
  market_strip: Array<{
    symbol: string;
    display: string;
    name_fa: string;
    price: number;
    change_pct: number;
    digits: number;
    source: string;
    is_demo_data: boolean;
  }>;
  top_news: NewsItem[];
  telegram_eligible_count: number;
  telegram_total_pairs_tf: number;
}

const SYMBOLS = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'EURGBP', 'XAUUSD'] as const;
const TIMEFRAMES = [
  { id: '4H', label: '4H امن' },
  { id: '15m', label: '15m متوسط' },
  { id: '5m', label: '5m ریسک بالا' },
] as const;

export const DashboardPage: React.FC = () => {
  const { lastWsEvent } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [chartSym, setChartSym] = useState<string>('EURUSD');
  const [chartTf, setChartTf] = useState<string>('4H');
  const [candles, setCandles] = useState<CandlePoint[]>([]);
  const [chartSource, setChartSource] = useState('');

  const loadDashboard = useCallback(async () => {
    try {
      setError('');
      const res = await apiFetch<DashboardData>('/api/v1/dashboard');
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت اطلاعات داشبورد');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadCandles = useCallback(async (sym: string, tf: string) => {
    try {
      const res = await apiFetch<{ candles: CandlePoint[]; source: string }>(
        `/api/v1/market/candles?symbol=${sym}&timeframe=${tf}&limit=140`
      );
      setCandles(res.candles);
      setChartSource(res.source);
    } catch {
      setCandles([]);
    }
  }, []);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard, lastWsEvent]);

  useEffect(() => {
    loadCandles(chartSym, chartTf);
  }, [chartSym, chartTf, loadCandles]);

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Skeleton />
          <Skeleton />
          <Skeleton />
          <Skeleton />
        </div>
        <Skeleton className="h-80" />
      </div>
    );
  }

  if (error || !data) {
    return <ErrorState message={error || 'خطا در بارگذاری'} onRetry={loadDashboard} />;
  }

  const k = data.kpis;
  const featuredTrade = data.active_trades[0] || null;
  const chartTradeOverlay =
    featuredTrade && featuredTrade.symbol === chartSym && featuredTrade.timeframe === chartTf
      ? {
          entry: featuredTrade.fill_price || featuredTrade.entry_price,
          sl: featuredTrade.current_sl,
          tp1: featuredTrade.tp1,
          tp2: featuredTrade.tp2,
          tp3: featuredTrade.tp3,
          beActive: featuredTrade.tp1_hit,
        }
      : undefined;

  return (
    <div className="space-y-5">
      <DemoBanner isDemo={data.is_demo_data} message={data.demo_notice_fa} />

      {/* 6 Allowed Symbols Ticker Strip */}
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-6">
        {data.market_strip.map((m) => (
          <button
            key={m.symbol}
            type="button"
            onClick={() => setChartSym(m.symbol)}
            className={`nx-card rounded-xl px-3 py-2.5 text-right transition ${
              chartSym === m.symbol ? 'border-nx-gold/60 shadow-gold' : 'hover:border-nx-border'
            }`}
          >
            <div className="flex items-center justify-between">
              <LtrValue className="text-xs font-bold text-nx-text">{m.display}</LtrValue>
              <LtrValue
                className={`text-[11px] font-semibold ${
                  m.change_pct >= 0 ? 'text-nx-profit' : 'text-nx-loss'
                }`}
              >
                {m.change_pct >= 0 ? '+' : ''}
                {m.change_pct}%
              </LtrValue>
            </div>
            <div className="mt-1 flex items-center justify-between">
              <span className="text-[10px] text-nx-muted truncate">{m.name_fa}</span>
              <LtrValue className="text-xs font-mono text-nx-gold">
                {m.price.toFixed(m.digits)}
              </LtrValue>
            </div>
          </button>
        ))}
      </div>

      {/* Top 4 KPI Cards (modeled on concept board + strict formula transparency) */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title={`نرخ برد (Win Rate) — ${data.time_range_label}`}
          value={
            <LtrValue className="text-nx-profit">{k.win_rate.toFixed(1)}%</LtrValue>
          }
          subtext={
            <span>
              <LtrValue>{k.winning_trades}</LtrValue> برنده از{' '}
              <LtrValue>{k.total_trades}</LtrValue> معامله بسته‌شده معتبر
            </span>
          }
          accent="profit"
          icon={<TrendingUp className="h-5 w-5 text-nx-profit" />}
        />
        <StatCard
          title="سود خالص و Profit Factor"
          value={
            <LtrValue className={k.net_profit_usd >= 0 ? 'text-nx-profit' : 'text-nx-loss'}>
              {formatSignedUsd(k.net_profit_usd)}
            </LtrValue>
          }
          subtext={
            <span>
              PF: <LtrValue className="text-nx-gold font-semibold">{k.profit_factor}</LtrValue> •
              میانگین: <LtrValue>{formatSignedR(k.avg_r)}</LtrValue>
            </span>
          }
          accent="gold"
          icon={<Award className="h-5 w-5 text-nx-gold" />}
        />
        <StatCard
          title="تارگت‌های خورده (پله‌ای)"
          value={<LtrValue className="text-nx-gold">{k.target_hits_total}</LtrValue>}
          subtext={
            <LtrValue className="text-[11px]">
              TP1: {k.tp1_hits} | TP2: {k.tp2_hits} | TP3: {k.tp3_hits}
            </LtrValue>
          }
          accent="info"
          icon={<CheckCircle2 className="h-5 w-5 text-sky-400" />}
        />
        <StatCard
          title="حدضرر / پوزیشن فعال / تلگرام"
          value={
            <div className="flex items-baseline gap-2">
              <LtrValue className="text-nx-loss">{k.sl_hits}</LtrValue>
              <span className="text-xs font-normal text-nx-muted">حدضرر</span>
              <span className="text-nx-border">|</span>
              <LtrValue className="text-sky-400">{k.active_trades}</LtrValue>
              <span className="text-xs font-normal text-nx-muted">فعال</span>
            </div>
          }
          subtext={
            <span className="flex items-center gap-1">
              <Send className="h-3 w-3 text-sky-400" />
              مجاز تلگرام: <LtrValue>{data.telegram_eligible_count}/{data.telegram_total_pairs_tf}</LtrValue> ترکیب
            </span>
          }
          accent="loss"
          icon={<ShieldAlert className="h-5 w-5 text-nx-loss" />}
        />
      </div>

      {/* Main Split: Chart + Active Trade (Left/Center 8 cols) & Persian News Panel (Right 4 cols) */}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-12">
        <div className="space-y-5 xl:col-span-8">
          {/* Interactive Candlestick Chart Card */}
          <div className="nx-card rounded-2xl p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-1.5">
                {SYMBOLS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setChartSym(s)}
                    className={`rounded-lg px-2.5 py-1 text-xs font-bold transition ${
                      chartSym === s
                        ? 'bg-nx-gold text-[#0B1220]'
                        : 'bg-nx-bg/70 text-nx-muted hover:text-nx-text'
                    }`}
                  >
                    <LtrValue>{SYMBOL_DISPLAY[s]}</LtrValue>
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-1.5">
                {TIMEFRAMES.map((tf) => (
                  <button
                    key={tf.id}
                    type="button"
                    onClick={() => setChartTf(tf.id)}
                    className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition ${
                      chartTf === tf.id
                        ? 'border-indigo-400/60 bg-indigo-600/30 text-white'
                        : 'border-nx-border bg-nx-bg/60 text-nx-muted hover:text-nx-text'
                    }`}
                  >
                    {tf.label}
                  </button>
                ))}
              </div>
            </div>

            <CandleChart
              candles={candles}
              digits={SYMBOL_DIGITS[chartSym] ?? 5}
              height={320}
              levels={chartTradeOverlay}
            />

            <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 text-[11px] text-nx-muted">
              <span>منبع قیمت: {chartSource || 'در حال دریافت...'}</span>
              <span>{data.calculation_basis_fa}</span>
            </div>
          </div>

          {/* Active Trades & Equity Curve */}
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="flex items-center gap-2 text-sm font-bold text-nx-text">
                  <Activity className="h-4 w-4 text-nx-gold" />
                  معاملات جاری و پیگیری زنده
                </h2>
                <Link to="/trades/live" className="text-xs text-nx-gold hover:underline">
                  مشاهده همه ←
                </Link>
              </div>
              {data.active_trades.length > 0 ? (
                <div className="space-y-3">
                  {data.active_trades.slice(0, 2).map((t) => (
                    <TradeCard key={t.id} trade={t} />
                  ))}
                </div>
              ) : (
                <div className="nx-card rounded-2xl p-6 text-center text-xs text-nx-muted">
                  در حال حاضر پوزیشن بازی وجود ندارد؛ موتور Trading Hub 3.0 در حال اسکن دقیق ۶ جفت‌ارز است.
                </div>
              )}
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-bold text-nx-text">منحنی رشد سرمایه (Equity)</h2>
                <Link to="/analytics" className="text-xs text-nx-gold hover:underline">
                  گزارش کامل ←
                </Link>
              </div>
              <EquityChart points={data.equity_curve} height={240} />
              <div className="nx-card rounded-2xl p-3.5 text-xs flex items-center justify-between">
                <span className="text-nx-muted">حداکثر افت سرمایه (Max DD):</span>
                <LtrValue className="font-bold text-nx-loss">{k.max_drawdown_pct}%</LtrValue>
              </div>
            </div>
          </div>

          {/* Recent Closed Trades Table */}
          <div className="nx-card rounded-2xl p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-bold text-nx-text">آخرین معاملات بسته‌شده</h2>
              <Link to="/trades/history" className="text-xs text-nx-gold hover:underline">
                تاریخچه کامل ←
              </Link>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-right text-xs">
                <thead>
                  <tr className="border-b border-nx-border text-nx-muted">
                    <th className="pb-2 font-medium">جفت‌ارز</th>
                    <th className="pb-2 font-medium">تایم‌فریم</th>
                    <th className="pb-2 font-medium">جهت</th>
                    <th className="pb-2 font-medium">ورود</th>
                    <th className="pb-2 font-medium">نتیجه (R)</th>
                    <th className="pb-2 font-medium">سود/زیان</th>
                    <th className="pb-2 font-medium">وضعیت</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {data.recent_closed.map((t) => {
                    const st = STATUS_FA[t.status] || { label: t.status, color: '' };
                    const rf = RISK_TIER_FA[t.risk_tier];
                    return (
                      <tr key={t.id} className="hover:bg-nx-elevated/40">
                        <td className="py-2.5 font-bold">
                          <Link to={`/trades/${t.id}`} className="hover:text-nx-gold">
                            <LtrValue>{SYMBOL_DISPLAY[t.symbol] || t.symbol}</LtrValue>
                          </Link>
                        </td>
                        <td className="py-2.5">
                          <span className={`rounded-md border px-1.5 py-0.5 text-[10px] ${rf?.color || ''}`}>
                            {rf?.short || t.timeframe}
                          </span>
                        </td>
                        <td className="py-2.5">
                          <Badge variant={t.direction === 'LONG' ? 'profit' : 'loss'}>
                            {t.direction}
                          </Badge>
                        </td>
                        <td className="py-2.5">
                          <LtrValue>{formatPrice(t.symbol, t.fill_price || t.entry_price)}</LtrValue>
                        </td>
                        <td className="py-2.5">
                          <LtrValue
                            className={`font-semibold ${
                              t.realized_r >= 0 ? 'text-nx-profit' : 'text-nx-loss'
                            }`}
                          >
                            {formatSignedR(t.realized_r)}
                          </LtrValue>
                        </td>
                        <td className="py-2.5">
                          <LtrValue
                            className={`font-semibold ${
                              t.realized_pnl_usd >= 0 ? 'text-nx-profit' : 'text-nx-loss'
                            }`}
                          >
                            {formatSignedUsd(t.realized_pnl_usd)}
                          </LtrValue>
                        </td>
                        <td className="py-2.5">
                          <span className={`rounded-md border px-1.5 py-0.5 text-[10px] ${st.color}`}>
                            {st.label}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Right Column: Persian Market News with Impact % */}
        <div className="space-y-3 xl:col-span-4">
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-bold text-nx-text">
              <Newspaper className="h-4 w-4 text-nx-gold" />
              اخبار بازار مالی (فارسی + درصد تاثیر)
            </h2>
            <Link to="/news" className="text-xs text-nx-gold hover:underline">
              مشاهده همه ←
            </Link>
          </div>
          <div className="space-y-3">
            {data.top_news.map((n) => (
              <NewsCard key={n.id} item={n} compact />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
