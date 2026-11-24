import React from 'react';
import { AlertTriangle, ExternalLink, Globe, ShieldAlert } from 'lucide-react';
import type { NewsItem } from '../../types';
import { CATEGORY_FA, formatRelativeFa, SYMBOL_DISPLAY } from '../../lib/format';
import { Badge, LtrValue } from '../ui';

export const NewsCard: React.FC<{ item: NewsItem; compact?: boolean }> = ({
  item,
  compact = false,
}) => {
  const impactVariant =
    item.impact_level === 'HIGH' ? 'loss' : item.impact_level === 'MEDIUM' ? 'warning' : 'info';
  const impactLabel =
    item.impact_level === 'HIGH'
      ? 'تاثیر بالا (High)'
      : item.impact_level === 'MEDIUM'
      ? 'تاثیر متوسط'
      : 'تاثیر کم';

  const barColor =
    item.market_impact_pct >= 80
      ? 'from-nx-loss to-nx-warning'
      : item.market_impact_pct >= 60
      ? 'from-nx-warning to-nx-gold'
      : 'from-sky-500 to-nx-profit';

  return (
    <article className="nx-card rounded-2xl p-4 transition hover:border-nx-gold/30">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1 font-semibold text-nx-gold">
            <Globe className="h-3.5 w-3.5" />
            {item.source_name}
          </span>
          <span className="text-nx-muted">•</span>
          <span className="text-nx-muted">{formatRelativeFa(item.published_at)}</span>
          {item.is_demo_data && <Badge variant="warning">نمونه آفلاین</Badge>}
        </div>
        <div className="flex items-center gap-1.5">
          <Badge variant="neutral">{CATEGORY_FA[item.category] || item.category}</Badge>
          <Badge variant={impactVariant}>{impactLabel}</Badge>
        </div>
      </div>

      <h3 className="mt-2.5 text-sm font-bold leading-6 text-nx-text">{item.persian_title}</h3>

      {!compact && (
        <p className="mt-1.5 text-xs leading-6 text-nx-muted">{item.persian_summary}</p>
      )}

      {/* Market Impact % Progress Bar */}
      <div className="mt-3 rounded-xl bg-nx-bg/60 p-2.5">
        <div className="mb-1.5 flex items-center justify-between text-xs">
          <span className="text-nx-muted">درصد تاثیر روی بازار (Market Impact)</span>
          <LtrValue className="font-bold text-nx-text">{item.market_impact_pct}%</LtrValue>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-nx-surface">
          <div
            className={`h-full rounded-full bg-gradient-to-l ${barColor}`}
            style={{ width: `${item.market_impact_pct}%` }}
          />
        </div>

        {!compact && (
          <div className="mt-2.5 grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
            <div className="rounded-lg bg-nx-surface/80 px-2 py-1">
              <span className="text-nx-muted">اهمیت: </span>
              <LtrValue className="font-semibold text-nx-text">{item.importance_score}%</LtrValue>
            </div>
            <div className="rounded-lg bg-nx-surface/80 px-2 py-1">
              <span className="text-nx-muted">نوسان: </span>
              <LtrValue className="font-semibold text-nx-warning">{item.volatility_score}%</LtrValue>
            </div>
            <div className="rounded-lg bg-nx-surface/80 px-2 py-1">
              <span className="text-nx-muted">ارتباط ارزی: </span>
              <LtrValue className="font-semibold text-sky-300">{item.currency_relevance_score}%</LtrValue>
            </div>
            <div className="rounded-lg bg-nx-surface/80 px-2 py-1">
              <span className="text-nx-muted">ریسک پوزیشن باز: </span>
              <LtrValue
                className={`font-semibold ${
                  item.active_trade_risk_score >= 70 ? 'text-nx-loss' : 'text-nx-profit'
                }`}
              >
                {item.active_trade_risk_score}%
              </LtrValue>
            </div>
          </div>
        )}
      </div>

      {/* Footer: Related currencies / symbols & original source link */}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="flex flex-wrap items-center gap-1.5">
          {item.related_symbols.slice(0, 4).map((s) => (
            <Badge key={s} variant="gold">
              <LtrValue>{SYMBOL_DISPLAY[s] || s}</LtrValue>
            </Badge>
          ))}
          {item.active_trade_risk_score >= 70 && (
            <Badge variant="loss">
              <ShieldAlert className="h-3 w-3" />
              تداخل با پوزیشن باز
            </Badge>
          )}
        </div>
        <a
          href={item.canonical_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-nx-gold hover:underline"
        >
          <span>منبع اصلی</span>
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </div>

      {!compact && item.methodology_note_fa && (
        <div className="mt-2.5 flex items-start gap-1.5 border-t border-white/5 pt-2 text-[11px] text-nx-muted">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-nx-softgold" />
          <span>{item.methodology_note_fa}</span>
        </div>
      )}
    </article>
  );
};
