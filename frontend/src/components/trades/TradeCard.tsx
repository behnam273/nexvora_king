import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowDownRight, ArrowUpRight, CheckCircle2, Send, ShieldCheck } from 'lucide-react';
import type { SignalTrade } from '../../types';
import {
  formatPrice,
  formatSignedR,
  formatSignedUsd,
  RISK_TIER_FA,
  STATUS_FA,
  SYMBOL_DISPLAY,
} from '../../lib/format';
import { Badge, LtrValue } from '../ui';

export const TradeCard: React.FC<{ trade: SignalTrade; compact?: boolean }> = ({
  trade,
  compact = false,
}) => {
  const isLong = trade.direction === 'LONG';
  const riskMeta = RISK_TIER_FA[trade.risk_tier] || RISK_TIER_FA.MEDIUM_RISK;
  const stMeta = STATUS_FA[trade.status] || { label: trade.status, color: '' };
  const totalPnlUsd = trade.realized_pnl_usd + trade.floating_pnl_usd;
  const totalR = trade.realized_r + trade.floating_r;
  const pnlPos = totalPnlUsd >= 0;

  const steps = [
    { key: 'fill', label: 'ورود', done: trade.status !== 'PENDING_LIMIT' },
    { key: 'tp1', label: 'TP1 + BE', done: trade.tp1_hit },
    { key: 'tp2', label: 'TP2', done: trade.tp2_hit },
    { key: 'tp3', label: 'TP3', done: trade.tp3_hit },
  ];

  return (
    <Link
      to={`/trades/${trade.id}`}
      className="nx-card block rounded-2xl p-4 transition hover:border-nx-gold/40 hover:shadow-gold"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <div
            className={`flex h-9 w-9 items-center justify-center rounded-xl border ${
              isLong
                ? 'border-nx-profit/30 bg-nx-profit/15 text-nx-profit'
                : 'border-nx-loss/30 bg-nx-loss/15 text-nx-loss'
            }`}
          >
            {isLong ? <ArrowUpRight className="h-5 w-5" /> : <ArrowDownRight className="h-5 w-5" />}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <LtrValue className="text-base font-bold text-nx-text">
                {SYMBOL_DISPLAY[trade.symbol] || trade.symbol}
              </LtrValue>
              <Badge variant={isLong ? 'profit' : 'loss'}>{isLong ? 'LONG خرید' : 'SHORT فروش'}</Badge>
              <span className={`rounded-lg border px-2 py-0.5 text-[11px] font-medium ${riskMeta.color}`}>
                {riskMeta.short}
              </span>
            </div>
            <div className="mt-0.5 flex items-center gap-2 text-[11px] text-nx-muted">
              <LtrValue>{trade.trade_code}</LtrValue>
              <span>•</span>
              <span>ماژول {trade.entry_module}</span>
              <span>•</span>
              <span className="text-nx-gold">
                امتیاز <LtrValue>{trade.confluence_score}/10 ({trade.grade})</LtrValue>
              </span>
            </div>
          </div>
        </div>

        <div className="text-left">
          <LtrValue
            className={`text-lg font-extrabold ${pnlPos ? 'text-nx-profit' : 'text-nx-loss'}`}
          >
            {formatSignedUsd(totalPnlUsd)}
          </LtrValue>
          <div className="flex items-center justify-end gap-1.5 text-xs">
            <LtrValue className={pnlPos ? 'text-nx-profit' : 'text-nx-loss'}>
              {formatSignedR(totalR)}
            </LtrValue>
            <span className={`rounded-md border px-1.5 py-0.5 text-[10px] ${stMeta.color}`}>
              {stMeta.label}
            </span>
          </div>
        </div>
      </div>

      {/* Prices grid */}
      <div className="mt-3 grid grid-cols-2 gap-2 rounded-xl bg-nx-bg/55 p-3 text-xs sm:grid-cols-4">
        <div>
          <span className="text-nx-muted">نقطه ورود</span>
          <div className="mt-0.5 font-semibold text-sky-300">
            <LtrValue>{formatPrice(trade.symbol, trade.fill_price || trade.entry_price)}</LtrValue>
          </div>
        </div>
        <div>
          <span className="text-nx-muted">قیمت فعلی</span>
          <div className="mt-0.5 font-semibold text-nx-text">
            <LtrValue>{formatPrice(trade.symbol, trade.current_price)}</LtrValue>
          </div>
        </div>
        <div>
          <span className="text-nx-muted flex items-center gap-1">
            حد ضرر فعال
            {trade.tp1_hit && <ShieldCheck className="h-3.5 w-3.5 text-nx-gold" />}
          </span>
          <div className="mt-0.5 font-semibold text-nx-loss">
            <LtrValue>{formatPrice(trade.symbol, trade.current_sl)}</LtrValue>
          </div>
        </div>
        <div>
          <span className="text-nx-muted">تارگت ۱ / ۲ / ۳</span>
          <div className="mt-0.5 font-semibold text-nx-profit">
            <LtrValue>{formatPrice(trade.symbol, trade.tp1)}</LtrValue>
          </div>
        </div>
      </div>

      {/* Position tracking lifecycle stepper */}
      {!compact && (
        <div className="mt-3">
          <div className="mb-1.5 flex items-center justify-between text-[11px] text-nx-muted">
            <span>پیگیری پله‌ای پوزیشن (باقی‌مانده: {trade.remaining_pct}%)</span>
            <LtrValue className="text-nx-gold font-medium">{trade.progress_to_tp1_pct}%</LtrValue>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-nx-bg">
            <div
              className="h-full rounded-full bg-gradient-to-l from-nx-profit to-nx-gold transition-all"
              style={{ width: `${Math.min(100, Math.max(4, trade.progress_to_tp1_pct))}%` }}
            />
          </div>
          <div className="mt-2.5 flex items-center justify-between gap-1">
            {steps.map((st) => (
              <div
                key={st.key}
                className={`flex flex-1 items-center justify-center gap-1 rounded-lg border py-1 text-[11px] ${
                  st.done
                    ? 'border-nx-profit/35 bg-nx-profit/12 text-nx-profit'
                    : 'border-nx-border/60 bg-nx-bg/40 text-nx-muted'
                }`}
              >
                {st.done && <CheckCircle2 className="h-3 w-3" />}
                <span>{st.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Telegram qualification footer */}
      <div className="mt-3 flex items-center justify-between border-t border-white/5 pt-2 text-[11px] text-nx-muted">
        <span className="flex items-center gap-1">
          <Send className="h-3 w-3 text-sky-400" />
          {trade.eligible_for_telegram ? 'ارسال‌شده به کانال تلگرام (وین‌ریت قوی)' : 'فقط پایش در PWA'}
        </span>
        <LtrValue>BT WR: {trade.backtest_win_rate_at_entry.toFixed(1)}%</LtrValue>
      </div>
    </Link>
  );
};
