/**
 * Dashboard persistent store.
 * Saved to localStorage key "trading-dashboard".
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type IndicatorType =
  | "EMA" | "SMA" | "BB" | "VWAP" | "RSI" | "MACD" | "Stoch"
  | "VolumeProfile" | "FVG" | "Pivot";

export interface IndicatorConfig {
  id: string;
  type: IndicatorType;
  inputs: Record<string, number | string | boolean>;
  style: Record<string, string>;
  visible: boolean;
  linkId?: string;  // shared across all panes when added via addIndicatorToAll
}

export interface PaneConfig {
  id: string;
  symbol: string;
  timeframe: string;
  dataSource: "auto" | "upstox" | "hyperliquid";
  indicators: IndicatorConfig[];
}

export const DEFAULT_INDICATOR_INPUTS: Record<IndicatorType, Record<string, number | string | boolean>> = {
  EMA:           { period: 20, source: "close" },
  SMA:           { period: 20, source: "close" },
  BB:            { period: 20, std: 2 },
  VWAP:          { showBands: false },
  RSI:           { period: 14 },
  MACD:          { fast: 12, slow: 26, signal: 9 },
  Stoch:         { k: 14, d: 3, smooth: 3 },
  VolumeProfile: { rows: 24, valueAreaPct: 70 },
  FVG:           { minGapPct: 0.1, showLabels: true, extendBoxes: true },
  Pivot:         { pivotType: "standard", pivotPeriod: "daily" },
};

export const DEFAULT_INDICATOR_STYLE: Record<IndicatorType, Record<string, string>> = {
  EMA:           { color: "#f7c948" },
  SMA:           { color: "#4caf50" },
  BB:            { upperColor: "#2196f3", midColor: "#888888", lowerColor: "#2196f3" },
  VWAP:          { color: "#ff9800", band1Color: "#ff980055", band2Color: "#ff980033", band3Color: "#ff980022" },
  RSI:           { color: "#ce93d8" },
  MACD:          { macdColor: "#2196f3", signalColor: "#f7c948" },
  Stoch:         { kColor: "#2196f3", dColor: "#f7c948" },
  VolumeProfile: { upColor: "#26a69a88", downColor: "#ef535088", pocColor: "#f59e0b" },
  FVG:           { bullColor: "#26a69a", bearColor: "#ef5350", opacity: "0.15" },
  Pivot:         { ppColor: "#2196f3", rColor: "#26a69a", sColor: "#ef5350" },
};

function newPane(symbol: string, timeframe = "15min"): PaneConfig {
  return {
    id: Math.random().toString(36).slice(2, 10),
    symbol,
    timeframe,
    dataSource: "auto",
    indicators: [],
  };
}

const DEFAULT_PANES: PaneConfig[] = [
  newPane("NSE:RELIANCE", "15min"),
  newPane("NSE:NIFTY 50", "15min"),
  newPane("CRYPTO:BTC",   "1h"),
  newPane("CRYPTO:ETH",   "1h"),
];

export function makeDefaultIndicator(type: IndicatorType): IndicatorConfig {
  return {
    id: Math.random().toString(36).slice(2, 10),
    type,
    inputs: { ...DEFAULT_INDICATOR_INPUTS[type] },
    style:  { ...DEFAULT_INDICATOR_STYLE[type] },
    visible: true,
  };
}

interface DashboardStore {
  paneCount: 1 | 2 | 4 | 6 | 8;
  panes: PaneConfig[];
  focusedPaneId: string | null;
  setPaneCount:    (n: 1 | 2 | 4 | 6 | 8) => void;
  setPaneSymbol:   (paneId: string, symbol: string) => void;
  setPaneTimeframe:(paneId: string, tf: string) => void;
  setFocusedPane:  (paneId: string | null) => void;
  addIndicator:         (paneId: string, type: IndicatorType) => void;
  addIndicatorToAll:    (type: IndicatorType) => void;
  updateIndicator:      (paneId: string, ind: IndicatorConfig) => void;
  removeIndicator:      (paneId: string, indicatorId: string) => void;
  removeIndicatorFromAll: (type: IndicatorType) => void;
  updateIndicatorByTypeAll: (type: IndicatorType, patch: Pick<IndicatorConfig, "inputs" | "style" | "visible">) => void;
  updateIndicatorByLinkId: (linkId: string, patch: Pick<IndicatorConfig, "inputs" | "style" | "visible">) => void;
  removeIndicatorByLinkId: (linkId: string) => void;
}

const EXTRA_SYMBOLS = [
  "NSE:RELIANCE","CRYPTO:BTC","NSE:INFY","CRYPTO:ETH",
  "NSE:TCS","CRYPTO:SOL","NSE:HDFC","CRYPTO:BNB",
];

export const useDashboardStore = create<DashboardStore>()(
  persist(
    (set) => ({
      paneCount: 4,
      panes: DEFAULT_PANES,
      focusedPaneId: DEFAULT_PANES[0].id,

      setPaneCount: (n) => set((s) => {
        const cur = s.panes;
        if (n > cur.length) {
          const extras = Array.from({ length: n - cur.length }, (_, i) =>
            newPane(EXTRA_SYMBOLS[cur.length + i] ?? "NSE:RELIANCE")
          );
          return { paneCount: n, panes: [...cur, ...extras] };
        }
        return { paneCount: n, panes: cur.slice(0, n) };
      }),

      setPaneSymbol: (paneId, symbol) => set((s) => ({
        panes: s.panes.map((p) => p.id === paneId ? { ...p, symbol } : p),
      })),

      setPaneTimeframe: (paneId, tf) => set((s) => ({
        panes: s.panes.map((p) => p.id === paneId ? { ...p, timeframe: tf } : p),
      })),

      setFocusedPane: (paneId) => set({ focusedPaneId: paneId }),

      addIndicator: (paneId, type) => set((s) => ({
        panes: s.panes.map((p) =>
          p.id === paneId
            ? { ...p, indicators: [...p.indicators, makeDefaultIndicator(type)] }
            : p
        ),
      })),

      addIndicatorToAll: (type) => set((s) => {
        const linkId = Math.random().toString(36).slice(2, 10);
        return {
          panes: s.panes.map((p) => ({
            ...p, indicators: [...p.indicators, { ...makeDefaultIndicator(type), linkId }],
          })),
        };
      }),

      updateIndicator: (paneId, ind) => set((s) => ({
        panes: s.panes.map((p) =>
          p.id === paneId
            ? { ...p, indicators: p.indicators.map((i) => i.id === ind.id ? ind : i) }
            : p
        ),
      })),

      removeIndicator: (paneId, indicatorId) => set((s) => ({
        panes: s.panes.map((p) =>
          p.id === paneId
            ? { ...p, indicators: p.indicators.filter((i) => i.id !== indicatorId) }
            : p
        ),
      })),

      removeIndicatorFromAll: (type) => set((s) => ({
        panes: s.panes.map((p) => ({
          ...p, indicators: p.indicators.filter((i) => i.type !== type),
        })),
      })),

      updateIndicatorByTypeAll: (type, patch) => set((s) => ({
        panes: s.panes.map((p) => ({
          ...p,
          indicators: p.indicators.map((i) =>
            i.type === type ? { ...i, ...patch } : i
          ),
        })),
      })),

      updateIndicatorByLinkId: (linkId, patch) => set((s) => ({
        panes: s.panes.map((p) => ({
          ...p,
          indicators: p.indicators.map((i) =>
            i.linkId === linkId ? { ...i, ...patch } : i
          ),
        })),
      })),

      removeIndicatorByLinkId: (linkId) => set((s) => ({
        panes: s.panes.map((p) => ({
          ...p, indicators: p.indicators.filter((i) => i.linkId !== linkId),
        })),
      })),
    }),
    {
      name: "trading-dashboard",
      partialize: (s) => ({ paneCount: s.paneCount, panes: s.panes, focusedPaneId: s.focusedPaneId }),
    }
  )
);
