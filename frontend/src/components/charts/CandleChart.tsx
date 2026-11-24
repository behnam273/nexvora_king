import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, LineStyle, IChartApi } from 'lightweight-charts';
import type { CandlePoint } from '../../types';

interface OverlayLevels {
  entry?: number;
  sl?: number;
  tp1?: number;
  tp2?: number;
  tp3?: number;
  beActive?: boolean;
}

interface CandleChartProps {
  candles: CandlePoint[];
  digits?: number;
  height?: number;
  levels?: OverlayLevels;
}

export const CandleChart: React.FC<CandleChartProps> = ({
  candles,
  digits = 5,
  height = 320,
  levels,
}) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart = createChart(el, {
      width: el.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: '#0E1728' },
        textColor: '#A8B4C7',
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      },
      grid: {
        vertLines: { color: 'rgba(168, 180, 199, 0.06)' },
        horzLines: { color: 'rgba(168, 180, 199, 0.06)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(168, 180, 199, 0.14)',
      },
      timeScale: {
        borderColor: 'rgba(168, 180, 199, 0.14)',
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        vertLine: { color: 'rgba(210, 180, 106, 0.45)', style: LineStyle.Dashed },
        horzLine: { color: 'rgba(210, 180, 106, 0.45)', style: LineStyle.Dashed },
      },
    });
    chartRef.current = chart;

    const series = chart.addCandlestickSeries({
      upColor: '#18B889',
      downColor: '#E45D68',
      borderVisible: false,
      wickUpColor: '#18B889',
      wickDownColor: '#E45D68',
      priceFormat: {
        type: 'price',
        precision: digits,
        minMove: Number((1 / Math.pow(10, digits)).toFixed(digits)),
      },
    });

    if (candles.length > 0) {
      // Ensure strictly ascending unique timestamps
      const sorted = [...candles].sort((a, b) => a.time - b.time);
      const unique: CandlePoint[] = [];
      let prevTime = -1;
      for (const c of sorted) {
        if (c.time > prevTime) {
          unique.push(c);
          prevTime = c.time;
        }
      }
      series.setData(unique as never);
    }

    if (levels?.entry) {
      series.createPriceLine({
        price: levels.entry,
        color: '#38BDF8',
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: 'ENTRY',
      });
    }
    if (levels?.sl) {
      series.createPriceLine({
        price: levels.sl,
        color: levels.beActive ? '#D2B46A' : '#E45D68',
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: levels.beActive ? 'SL (BE/LOCKED)' : 'STOP LOSS',
      });
    }
    if (levels?.tp1) {
      series.createPriceLine({
        price: levels.tp1,
        color: '#18B889',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'TP1',
      });
    }
    if (levels?.tp2) {
      series.createPriceLine({
        price: levels.tp2,
        color: '#34D399',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'TP2',
      });
    }
    if (levels?.tp3) {
      series.createPriceLine({
        price: levels.tp3,
        color: '#D2B46A',
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: 'TP3',
      });
    }

    chart.timeScale().fitContent();

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 0) {
          chart.applyOptions({ width: entry.contentRect.width });
        }
      }
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [candles, digits, height, levels?.entry, levels?.sl, levels?.tp1, levels?.tp2, levels?.tp3, levels?.beActive]);

  return (
    <div dir="ltr" className="w-full overflow-hidden rounded-xl border border-nx-border/70 bg-[#0E1728]">
      <div ref={containerRef} style={{ height }} />
    </div>
  );
};
