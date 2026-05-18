import { useEffect, useRef } from "react";
import { createChart, type IChartApi, type ISeriesApi, CandlestickSeries, type UTCTimestamp } from "lightweight-charts";

interface Bar { ts: string; open: number; high: number; low: number; close: number }

export default function CandlestickChart({ bars }: { bars: Bar[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    chartRef.current = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight || 500,
      layout: { background: { color: "#131722" }, textColor: "#787b86" },
      grid: { vertLines: { color: "#1e222d" }, horzLines: { color: "#1e222d" } },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: "#2a2e39" },
      timeScale: { borderColor: "#2a2e39", timeVisible: true },
    });
    seriesRef.current = chartRef.current.addSeries(CandlestickSeries, {
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
    });

    const ro = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    });
    ro.observe(containerRef.current);
    return () => { ro.disconnect(); chartRef.current?.remove(); };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || bars.length === 0) return;
    const formatted = bars.map((b) => ({
      time: (new Date(b.ts.split("T")[0]).getTime() / 1000) as UTCTimestamp,
      open: b.open, high: b.high, low: b.low, close: b.close,
    }));
    seriesRef.current.setData(formatted);
    chartRef.current?.timeScale().fitContent();
  }, [bars]);

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
}
