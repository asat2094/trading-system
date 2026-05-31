import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { apiClient } from "../../api/client";
import CandlestickChart from "../Chart/CandlestickChart";
import type { ChartHandle } from "../Chart/CandlestickChart";
import type { Bar } from "../Chart/indicators";
import type { StudyConfig } from "../Chart/types";
import type { UTCTimestamp } from "lightweight-charts";
import { tsToUnix } from "../../lib/time";
import { useLiveQuotesStore } from "../../store/liveQuotes";
import * as marketWs from "../../lib/marketWs";

const TV = {
  bg: "#131722", header: "#1a1e2e", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86", accent: "#2962ff",
} as const;

const TF_MS: Record<string, number> = {
  "1min": 60_000, "5min": 300_000, "15min": 900_000,
  "30min": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
};
const TF_DAYS: Record<string, number> = {
  "1min": 3, "5min": 7, "15min": 14, "30min": 21, "1h": 60, "4h": 120, "1d": 365,
};
const TIMEFRAMES = ["1min", "5min", "15min", "30min", "1h", "4h", "1d"];

// Stable empty array — prevents CandlestickChart re-running its data effect on every render
const EMPTY_STUDIES: StudyConfig[] = [];

function candleFloor(tsMs: number, tf: string): number {
  const step = TF_MS[tf] ?? TF_MS["5min"];
  return Math.floor(tsMs / step) * step;
}

function msToTs(ms: number): string {
  return new Date(ms).toISOString().replace("Z", "").replace(/\.\d{3}$/, "");
}

interface Props {
  symbol: string;
  label:  string;
  onClose: () => void;
}

export default function FnoChartModal({ symbol, label, onClose }: Props) {
  const [timeframe, setTimeframe] = useState("15min");
  const [bars, setBars]           = useState<Bar[]>([]);
  const [loading, setLoading]     = useState(false);
  const [loadError, setLoadError] = useState<string>("");
  const chartRef = useRef<ChartHandle>(null);
  const barsRef  = useRef<Bar[]>([]);

  const tfOffsetSec = useMemo(() => (TF_MS[timeframe] ?? 0) / 1000, [timeframe]);

  const loadBars = useCallback(async (sym: string, tf: string) => {
    setLoading(true);
    setBars([]);
    setLoadError("");
    barsRef.current = [];
    try {
      const days   = TF_DAYS[tf] ?? 30;
      const toDt   = new Date().toISOString().slice(0, 19) + "Z";
      const fromDt = new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 19) + "Z";
      const isExchange = sym.startsWith("NSE:") || sym.startsWith("BSE:") || sym.startsWith("NFO:") || sym.startsWith("BFO:");
      let fetched: Bar[];
      if (isExchange) {
        const { data } = await apiClient.get("/technical/candles", {
          params: { symbol: sym, tf, from_dt: fromDt, to_dt: toDt },
        });
        fetched = (data.rows ?? []) as Bar[];
      } else {
        const { data } = await apiClient.get("/market/ohlcv", {
          params: { symbol: sym, tf, from_dt: fromDt, to_dt: toDt },
        });
        fetched = (data.rows ?? []) as Bar[];
      }
      barsRef.current = fetched;
      setBars(fetched);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } }; message?: string })
        ?.response?.data?.detail ?? (err as Error)?.message ?? "Load failed";
      setLoadError(msg);
      console.error("FnoChartModal:", msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadBars(symbol, timeframe);
  }, [symbol, timeframe, loadBars]);

  useEffect(() => {
    marketWs.subscribe([symbol]);
    return () => marketWs.unsubscribe([symbol]);
  }, [symbol]);

  useEffect(() => {
    return useLiveQuotesStore.subscribe((state) => {
      const q = state.quotes[symbol];
      if (!q) return;
      const cs = chartRef.current?.candleSeries;
      const vs = chartRef.current?.volumeSeries;
      if (!cs || barsRef.current.length === 0) return;
      const last = barsRef.current[barsRef.current.length - 1];
      const lastBarOpenTime    = tsToUnix(last.ts);
      const lastBarDisplayTime = (lastBarOpenTime + tfOffsetSec) as UTCTimestamp;
      const tickMs             = new Date(q.ts).getTime();
      const candleStartSec     = Math.floor(candleFloor(tickMs, timeframe) / 1000);
      try {
        if (candleStartSec === lastBarOpenTime) {
          const updated: Bar = {
            ...last,
            high: Math.max(last.high, q.ltp), low: Math.min(last.low, q.ltp),
            close: q.ltp, volume: last.volume + q.volume,
          };
          barsRef.current[barsRef.current.length - 1] = updated;
          cs.update({ time: lastBarDisplayTime, open: updated.open, high: updated.high, low: updated.low, close: updated.close });
          vs?.update({ time: lastBarDisplayTime, value: updated.volume, color: updated.close >= updated.open ? "#26a69a66" : "#ef535066" });
        } else if (candleStartSec > lastBarOpenTime) {
          const newBarDisplayTime = (candleStartSec + tfOffsetSec) as UTCTimestamp;
          const newBar: Bar = { ts: msToTs(candleStartSec * 1000), open: q.ltp, high: q.ltp, low: q.ltp, close: q.ltp, volume: q.volume };
          barsRef.current.push(newBar);
          cs.update({ time: newBarDisplayTime, open: q.ltp, high: q.ltp, low: q.ltp, close: q.ltp });
          vs?.update({ time: newBarDisplayTime, value: q.volume, color: "#26a69a66" });
        }
      } catch { /* ignore */ }
    });
  }, [symbol, timeframe, tfOffsetSec]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(0,0,0,0.75)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{
        width: "92vw", height: "86vh",
        background: TV.bg,
        border: `1px solid ${TV.border}`,
        borderRadius: 8,
        display: "flex", flexDirection: "column",
        overflow: "hidden",
        boxShadow: "0 8px 40px rgba(0,0,0,0.7)",
      }}>
        {/* Header */}
        <div style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "8px 14px", background: TV.header,
          borderBottom: `1px solid ${TV.border}`, flexShrink: 0,
        }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: TV.text }}>{label}</span>
          <div style={{ display: "flex", gap: 3 }}>
            {TIMEFRAMES.map(tf => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                style={{
                  background: timeframe === tf ? TV.accent : "transparent",
                  border: `1px solid ${timeframe === tf ? TV.accent : TV.border}`,
                  borderRadius: 3, color: timeframe === tf ? "#fff" : TV.muted,
                  fontSize: 10, padding: "2px 7px", cursor: "pointer",
                }}
              >{tf}</button>
            ))}
          </div>
          <div style={{ flex: 1 }} />
          <button
            onClick={onClose}
            title="Close (Esc)"
            style={{
              background: "transparent", border: `1px solid ${TV.border}`,
              borderRadius: 4, color: TV.muted,
              fontSize: 18, width: 28, height: 26,
              cursor: "pointer", lineHeight: 1,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}
          >×</button>
        </div>

        {/* Chart area — always rendered so CandlestickChart initialises immediately */}
        <div style={{ flex: 1, position: "relative", minHeight: 0 }}>
          {/* Always-mounted chart — hidden via opacity until bars load */}
          <div style={{
            position: "absolute", inset: 0,
            opacity: bars.length > 0 ? 1 : 0,
            transition: "opacity 0.2s",
          }}>
            <CandlestickChart
              ref={chartRef}
              bars={bars}
              studies={EMPTY_STUDIES}
              tfOffsetSec={tfOffsetSec}
              onVisibleRangeChange={undefined}
            />
          </div>

          {/* Overlay states */}
          {loading && (
            <div style={{
              position: "absolute", inset: 0, display: "flex",
              alignItems: "center", justifyContent: "center",
              background: "#13172299", zIndex: 5,
            }}>
              <span style={{ color: TV.muted, fontSize: 13 }}>Loading…</span>
            </div>
          )}
          {!loading && loadError && (
            <div style={{
              position: "absolute", inset: 0, display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center", gap: 8, zIndex: 5,
            }}>
              <span style={{ color: "#ef5350", fontSize: 13 }}>{loadError}</span>
              <button
                onClick={() => loadBars(symbol, timeframe)}
                style={{
                  background: TV.accent, border: "none", borderRadius: 4,
                  color: "#fff", fontSize: 12, padding: "5px 14px", cursor: "pointer",
                }}
              >Retry</button>
            </div>
          )}
          {!loading && !loadError && bars.length === 0 && (
            <div style={{
              position: "absolute", inset: 0, display: "flex",
              flexDirection: "column", alignItems: "center", justifyContent: "center",
              gap: 6, zIndex: 5,
            }}>
              <span style={{ color: TV.muted, fontSize: 13 }}>No data for {symbol}</span>
              <span style={{ color: TV.muted, fontSize: 11 }}>Symbol may not be backfilled in QuestDB</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
