import { useState, useCallback, useRef, useEffect } from "react";
import { useDashboardStore } from "../../store/dashboard";
import type { IndicatorConfig } from "../../store/dashboard";
import { apiClient } from "../../api/client";
import CandlestickChart from "../Chart/CandlestickChart";
import type { ChartHandle } from "../Chart/CandlestickChart";
import type { Bar } from "../Chart/indicators";
import type { StudyConfig } from "../Chart/types";
import { STUDY_DEFAULTS } from "../Chart/types";
import TickerBar from "./TickerBar";
import PaneControls from "./PaneControls";
import IndicatorPanel from "./IndicatorPanel";
import * as marketWs from "../../lib/marketWs";

const TV = {
  bg: "#131722", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86",
  accent: "#2962ff",
} as const;

const TF_DAYS: Record<string, number> = {
  "1min": 3, "5min": 7, "15min": 14, "30min": 21,
  "1h": 60, "4h": 120, "1d": 365, "1w": 730,
};

function toStudyConfig(ind: IndicatorConfig): StudyConfig | null {
  if (!ind.visible) return null;
  const defaults = STUDY_DEFAULTS[ind.type as keyof typeof STUDY_DEFAULTS];
  if (!defaults) return null;
  const merged = { id: ind.id, ...defaults };
  for (const [k, v] of Object.entries(ind.inputs))  (merged as Record<string, unknown>)[k] = v;
  for (const [k, v] of Object.entries(ind.style))   (merged as Record<string, unknown>)[k] = v;
  return merged as StudyConfig;
}

interface Props {
  paneId: string;
  focused: boolean;
  onFocus: () => void;
}

export default function ChartPane({ paneId, focused, onFocus }: Props) {
  const pane = useDashboardStore((s) => s.panes.find((p) => p.id === paneId));
  const [bars, setBars]         = useState<Bar[]>([]);
  const [loading, setLoading]   = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const chartRef = useRef<ChartHandle>(null);

  const symbol    = pane?.symbol    ?? "NSE:RELIANCE";
  const timeframe = pane?.timeframe ?? "15min";
  const indicators = pane?.indicators ?? [];

  const studies: StudyConfig[] = indicators
    .map(toStudyConfig)
    .filter((s): s is StudyConfig => s !== null);

  const loadBars = useCallback(async (
    sym: string, tf: string, fromDt: string, toDt: string
  ): Promise<Bar[]> => {
    const isExchange = sym.startsWith("NSE:") || sym.startsWith("BSE:");
    if (isExchange) {
      const ticker = sym.split(":")[1];
      const { data } = await apiClient.get(`/technical/ohlcv/${ticker}`, {
        params: { tf, from_dt: fromDt, to_dt: toDt },
      });
      return (data.bars ?? data) as Bar[];
    } else {
      const { data } = await apiClient.get("/market/ohlcv", {
        params: { symbol: sym, tf, from_dt: fromDt, to_dt: toDt },
      });
      return (data.bars ?? data) as Bar[];
    }
  }, []);

  const loadInitial = useCallback(async () => {
    setLoading(true);
    setBars([]);
    try {
      const days = TF_DAYS[timeframe] ?? 30;
      const toDt   = new Date().toISOString().slice(0, 19);
      const fromDt = new Date(Date.now() - days * 86400_000).toISOString().slice(0, 19);
      const fetched = await loadBars(symbol, timeframe, fromDt, toDt);
      setBars(fetched);
    } catch (err) {
      console.error("ChartPane: loadInitial failed", err);
    } finally {
      setLoading(false);
    }
  }, [symbol, timeframe, loadBars]);

  const handleNeedMoreData = useCallback(async () => {
    if (bars.length === 0) return;
    try {
      const oldestTs = bars[0].ts;
      const toDt   = oldestTs;
      const days = TF_DAYS[timeframe] ?? 30;
      const fromDt = new Date(new Date(oldestTs).getTime() - days * 86400_000).toISOString().slice(0, 19);
      const older = await loadBars(symbol, timeframe, fromDt, toDt);
      if (older.length > 0) {
        setBars((prev) => [...older, ...prev]);
      }
    } catch (err) {
      console.error("ChartPane: handleNeedMoreData failed", err);
    }
  }, [bars, symbol, timeframe, loadBars]);

  // Load bars on symbol/timeframe change
  useEffect(() => {
    void loadInitial();
  }, [loadInitial]);

  // Subscribe/unsubscribe from live feed
  useEffect(() => {
    marketWs.subscribe([symbol]);
    return () => {
      marketWs.unsubscribe([symbol]);
    };
  }, [symbol]);

  const containerStyle: React.CSSProperties = {
    position: "relative",
    display: "flex",
    flexDirection: "column",
    height: "100%",
    border: focused ? `2px solid ${TV.accent}` : `1px solid ${TV.border}`,
    boxSizing: "border-box",
    background: TV.bg,
    overflow: "hidden",
  };

  return (
    <div style={containerStyle} onClick={onFocus}>
      {/* Header */}
      <div style={{ padding: "3px 8px", background: "#1a1e2e", flexShrink: 0 }}>
        <PaneControls paneId={paneId} symbol={symbol} timeframe={timeframe} />
      </div>

      {/* Ticker bar */}
      <TickerBar
        symbol={symbol}
        timeframe={timeframe}
        onOpenIndicators={() => { onFocus(); setPanelOpen((v) => !v); }}
      />

      {/* Chart area */}
      <div style={{ flex: 1, overflow: "hidden", position: "relative", minHeight: 0 }}>
        {loading && (
          <div style={{
            position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
            background: "#13172288", zIndex: 10,
          }}>
            <span style={{ color: TV.muted, fontSize: 12 }}>Loading…</span>
          </div>
        )}
        {!loading && bars.length === 0 && (
          <div style={{
            position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <span style={{ color: TV.muted, fontSize: 12 }}>No data for {symbol}</span>
          </div>
        )}
        {bars.length > 0 && (
          <CandlestickChart
            ref={chartRef}
            bars={bars}
            studies={studies}
            onNeedMoreData={handleNeedMoreData}
          />
        )}
      </div>

      {/* Indicator panel */}
      {panelOpen && pane && (
        <IndicatorPanel
          paneId={paneId}
          indicators={pane.indicators}
          onClose={() => setPanelOpen(false)}
        />
      )}
    </div>
  );
}
