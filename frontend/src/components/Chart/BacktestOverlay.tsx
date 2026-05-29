/**
 * BacktestOverlay — fetches trade markers from backtest-engine and renders them
 * on the existing candlestick series using lightweight-charts v5 createSeriesMarkers.
 *
 * Entry: green arrowUp belowBar
 * Profit exit: green arrowDown aboveBar
 * SL exit: red arrowDown aboveBar
 * Pattern annotations: amber circle belowBar
 * SL/target price lines: dashed horizontal lines per trade
 */
import { useEffect, useRef } from "react";
import {
  createSeriesMarkers,
  LineStyle,
  type IChartApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type UTCTimestamp,
} from "lightweight-charts";
import type { ChartHandle } from "./CandlestickChart";

const BACKTEST_URL = import.meta.env.VITE_BACKTEST_ENGINE_URL ?? "http://localhost:8085";

interface PriceLine {
  trade_idx: number;
  entry_time: number;
  exit_time: number;
  sl_price: number | null;
  target_price: number | null;
}

interface MarkersResponse {
  markers: Array<{
    time: number;
    position: "belowBar" | "aboveBar" | "inBar";
    color: string;
    shape: "arrowUp" | "arrowDown" | "circle" | "square";
    text: string;
  }>;
  price_lines: PriceLine[];
}

interface Props {
  runId: string | null;
  symbol: string;
  chartHandle: ChartHandle | null;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyPriceLine = any;

export default function BacktestOverlay({ runId, symbol, chartHandle }: Props) {
  const markersPluginRef = useRef<ISeriesMarkersPluginApi<UTCTimestamp> | null>(null);
  const priceLineRefs = useRef<AnyPriceLine[]>([]);

  function clearOverlay() {
    // Clear markers
    if (markersPluginRef.current) {
      markersPluginRef.current.setMarkers([]);
      markersPluginRef.current = null;
    }
    // Clear price lines
    if (chartHandle?.candleSeries) {
      for (const pl of priceLineRefs.current) {
        try { chartHandle.candleSeries.removePriceLine(pl); } catch {}
      }
    }
    priceLineRefs.current = [];
  }

  useEffect(() => {
    if (!runId || !chartHandle?.candleSeries || !chartHandle?.chart) {
      clearOverlay();
      return;
    }

    const series = chartHandle.candleSeries;
    const chart: IChartApi = chartHandle.chart;
    let cancelled = false;

    async function load() {
      try {
        const res = await fetch(`${BACKTEST_URL}/runs/${runId}/markers/${symbol}`);
        if (!res.ok || cancelled) return;
        const data: MarkersResponse = await res.json();

        if (cancelled) return;

        // Clear previous
        clearOverlay();

        // Set markers
        const lwMarkers: SeriesMarker<UTCTimestamp>[] = data.markers.map(m => ({
          time: m.time as UTCTimestamp,
          position: m.position,
          color: m.color,
          shape: m.shape,
          text: m.text,
        }));

        if (lwMarkers.length > 0) {
          markersPluginRef.current = createSeriesMarkers(series, lwMarkers);
        }

        // Add SL + target price lines
        const newLines: AnyPriceLine[] = [];
        for (const pl of data.price_lines) {
          if (pl.sl_price != null) {
            newLines.push(
              series.createPriceLine({
                price: pl.sl_price,
                color: "#ef535088",
                lineWidth: 1,
                lineStyle: LineStyle.Dashed,
                axisLabelVisible: false,
                title: `SL`,
              })
            );
          }
          if (pl.target_price != null) {
            newLines.push(
              series.createPriceLine({
                price: pl.target_price,
                color: "#26a69a88",
                lineWidth: 1,
                lineStyle: LineStyle.Dashed,
                axisLabelVisible: false,
                title: `TP`,
              })
            );
          }
        }
        priceLineRefs.current = newLines;

        // Fit content to show full backtest range
        chart.timeScale().fitContent();
      } catch (err) {
        console.warn("BacktestOverlay fetch failed:", err);
      }
    }

    load();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, symbol, chartHandle]);

  // Cleanup on unmount
  useEffect(() => () => clearOverlay(), []);

  return null; // pure overlay — no DOM output
}
