import React, { useCallback, useEffect, useState } from 'react';
import { Globe2, RefreshCw } from 'lucide-react';
import { apiFetch } from '../lib/api';
import { RISK_TIER_FA } from '../lib/format';
import { Badge, Button, DemoBanner, ErrorState, LtrValue, Skeleton } from '../components/ui';

interface MarketOverviewResp {
  strength_methodology_fa: string;
  currency_strength: Array<{
    currency: string;
    strength_score: number;
    avg_change_pct: number;
    pairs_count: number;
  }>;
  instruments: Array<{
    symbol: string;
    display: string;
    name_fa: string;
    digits: number;
    price: number;
    high_recent: number;
    low_recent: number;
    change_pct: number;
    source: string;
    is_demo_data: boolean;
    timeframes: Array<{
      timeframe: string;
      label_fa: string;
      risk_tier: string;
      state: string;
      htf_bias: string;
      adx: number;
      readiness_pct: number;
      why_no_trade_fa: string;
      eligible_for_telegram: boolean;
      backtest_win_rate: number;
      backtest_profit_factor: number;
      backtest_trades: number;
      is_demo_data: boolean;
    }>;
  }>;
}

export const MarketOverviewPage: React.FC = () => {
  const [data, setData] = useState<MarketOverviewResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setError('');
      const res = await apiFetch<MarketOverviewResp>('/api/v1/market/overview');
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در بارگذاری نمای بازار');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <Skeleton className="h-96" />;
  if (error || !data) return <ErrorState message={error || 'خطا'} onRetry={load} />;

  return (
    <div className="space-y-5">
      <DemoBanner isDemo={data.instruments.some((x) => x.is_demo_data)} />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-extrabold text-nx-text">
            <Globe2 className="h-5 w-5 text-nx-gold" />
            نمای بازار ۶ جفت‌ارز مجاز و وضعیت زنده موتور Trading Hub 3.0
          </h1>
          <p className="text-xs text-nx-muted">
            محدوده انحصاری: USDJPY، AUDUSD، EURUSD، XAUUSD، GBPUSD، EURGBP روی تایم‌فریم‌های 4H / 15m / 5m
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={load}>
          <RefreshCw className="h-3.5 w-3.5" />
          به‌روزرسانی
        </Button>
      </div>

      {/* Currency Strength Bar */}
      <div className="nx-card rounded-2xl p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-bold text-nx-text">قدرت نسبی ارزها (Currency Strength)</h2>
          <span className="text-[11px] text-nx-muted">{data.strength_methodology_fa}</span>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {data.currency_strength.map((cs) => (
            <div key={cs.currency} className="rounded-xl bg-nx-bg/60 p-3">
              <div className="flex items-center justify-between text-xs font-bold">
                <LtrValue>{cs.currency}</LtrValue>
                <LtrValue className={cs.strength_score >= 50 ? 'text-nx-profit' : 'text-nx-loss'}>
                  {cs.strength_score}/100
                </LtrValue>
              </div>
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-nx-surface">
                <div
                  className={`h-full rounded-full ${cs.strength_score >= 50 ? 'bg-nx-profit' : 'bg-nx-loss'}`}
                  style={{ width: `${cs.strength_score}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 6 Instrument Scanner Cards */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {data.instruments.map((inst) => (
          <div key={inst.symbol} className="nx-card rounded-2xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <LtrValue className="text-base font-extrabold text-nx-text">{inst.display}</LtrValue>
                  <span className="text-xs text-nx-muted">{inst.name_fa}</span>
                </div>
                <div className="text-[11px] text-nx-muted mt-0.5">منبع: {inst.source}</div>
              </div>
              <div className="text-left">
                <LtrValue className="text-lg font-bold text-nx-gold">
                  {inst.price.toFixed(inst.digits)}
                </LtrValue>
                <div>
                  <LtrValue className={`text-xs font-semibold ${inst.change_pct >= 0 ? 'text-nx-profit' : 'text-nx-loss'}`}>
                    {inst.change_pct >= 0 ? '+' : ''}{inst.change_pct}%
                  </LtrValue>
                </div>
              </div>
            </div>

            <div className="space-y-2">
              {inst.timeframes.map((tf) => {
                const rf = RISK_TIER_FA[tf.risk_tier];
                return (
                  <div key={tf.timeframe} className="rounded-xl border border-nx-border/70 bg-nx-bg/55 p-3 text-xs">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className={`rounded-md border px-2 py-0.5 text-[10px] font-bold ${rf?.color || ''}`}>
                          {rf?.short}
                        </span>
                        <Badge variant={tf.htf_bias === 'BULLISH' ? 'profit' : tf.htf_bias === 'BEARISH' ? 'loss' : 'neutral'}>
                          {tf.htf_bias}
                        </Badge>
                        <Badge variant={tf.state === 'SETUP_READY' ? 'profit' : tf.state === 'ARMED' ? 'warning' : 'neutral'}>
                          {tf.state}
                        </Badge>
                      </div>
                      <div className="flex flex-wrap items-center gap-2 text-[11px]">
                        <span>ADX: <LtrValue className="text-nx-text font-semibold">{tf.adx}</LtrValue></span>
                        <span>•</span>
                        <span className={tf.eligible_for_telegram ? 'text-nx-profit font-bold' : 'text-nx-muted'}>
                          {tf.eligible_for_telegram
                            ? `تلگرام مجاز (WR ${tf.backtest_win_rate.toFixed(0)}%)`
                            : tf.is_demo_data
                              ? 'کانال تلگرام: فقط داده زنده (این داده بازپخش است)'
                              : `کانال تلگرام: تأیید نشده (WR ${tf.backtest_win_rate.toFixed(0)}%)`}
                        </span>
                      </div>
                    </div>
                    <p className="mt-1.5 text-[11px] text-nx-muted">{tf.why_no_trade_fa}</p>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
