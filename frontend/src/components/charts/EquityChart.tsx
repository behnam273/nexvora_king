import React from 'react';
import { LtrValue } from '../ui';

interface EquityPoint {
  timestamp: string;
  trade_code: string;
  symbol: string;
  equity: number;
  pnl_usd: number;
  r: number;
}

export const EquityChart: React.FC<{ points: EquityPoint[]; height?: number }> = ({
  points,
  height = 170,
}) => {
  if (!points || points.length < 2) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-center rounded-xl border border-nx-border/60 bg-nx-bg/40 text-xs text-nx-muted"
      >
        داده معاملات بسته‌شده کافی برای رسم منحنی رشد سرمایه وجود ندارد.
      </div>
    );
  }

  const values = [10000, ...points.map((p) => p.equity)];
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const span = Math.max(maxV - minV, 1);

  const w = 600;
  const h = height;
  const padX = 12;
  const padY = 16;

  const coords = values.map((v, idx) => {
    const x = padX + (idx / (values.length - 1)) * (w - padX * 2);
    const y = h - padY - ((v - minV) / span) * (h - padY * 2);
    return { x, y, v };
  });

  const linePath = coords.map((c, i) => `${i === 0 ? 'M' : 'L'} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(' ');
  const areaPath = `${linePath} L ${coords[coords.length - 1].x.toFixed(1)} ${h - padY} L ${coords[0].x.toFixed(1)} ${h - padY} Z`;
  const lastVal = values[values.length - 1];
  const isPositive = lastVal >= 10000;
  const stroke = isPositive ? '#18B889' : '#E45D68';

  return (
    <div className="w-full rounded-xl border border-nx-border/60 bg-nx-bg/40 p-3">
      <div className="mb-2 flex items-center justify-between text-xs text-nx-muted">
        <span>منحنی رشد سرمایه (پایه 10,000$)</span>
        <LtrValue className={`font-bold ${isPositive ? 'text-nx-profit' : 'text-nx-loss'}`}>
          ${lastVal.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </LtrValue>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full overflow-visible" style={{ height: height - 30 }}>
        <defs>
          <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity="0.32" />
            <stop offset="100%" stopColor={stroke} stopOpacity="0.01" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill="url(#eqFill)" />
        <path d={linePath} fill="none" stroke={stroke} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <circle
          cx={coords[coords.length - 1].x}
          cy={coords[coords.length - 1].y}
          r="4"
          fill={stroke}
          stroke="#0B1220"
          strokeWidth="2"
        />
      </svg>
    </div>
  );
};
