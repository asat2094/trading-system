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
      height: 400,
      layout: { background: { color: "#1a1a2e" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#2d2d4e" }, horzLines: { color: "#2d2d4e" } },
    });
    seriesRef.current = chartRef.current.addSeries(CandlestickSeries, {
      upColor: "#089981",
      downColor: "#f23645",
      borderVisible: false,
      wickUpColor: "#089981",
      wickDownColor: "#f23645",
    });
    return () => chartRef.current?.remove();
  }, []);

  useEffect(() => {
    if (!seriesRef.current || bars.length === 0) return;
    const formatted = bars.map((b) => ({
      time: (new Date(b.ts.split("T")[0]).getTime() / 1000) as UTCTimestamp,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    seriesRef.current.setData(formatted);
    chartRef.current?.timeScale().fitContent();
  }, [bars]);

  return <div ref={containerRef} style={{ width: "100%", height: 400 }} />;
}
