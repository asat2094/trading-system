export type StudyType =
  | "EMA" | "SMA" | "BB" | "VWAP" | "RSI" | "MACD" | "Stoch"
  | "VolumeProfile" | "FVG";

export type StudyConfig =
  | { id: string; type: "EMA";           period: number; color: string }
  | { id: string; type: "SMA";           period: number; color: string }
  | { id: string; type: "BB";            period: number; std: number; upperColor: string; midColor: string; lowerColor: string }
  | { id: string; type: "VWAP";          color: string }
  | { id: string; type: "RSI";           period: number; color: string }
  | { id: string; type: "MACD";          fast: number; slow: number; signal: number; macdColor: string; signalColor: string }
  | { id: string; type: "Stoch";         k: number; d: number; smooth: number; kColor: string; dColor: string }
  | { id: string; type: "VolumeProfile"; rows: number; valueAreaPct: number; upColor: string; downColor: string; pocColor: string }
  | { id: string; type: "FVG";           minGapPct: number; showLabels: boolean; extendBoxes: boolean; bullColor: string; bearColor: string; opacity: number };

export const OVERLAY_TYPES: StudyType[] = ["EMA", "SMA", "BB", "VWAP", "VolumeProfile", "FVG"];
export const OSCILLATOR_TYPES: StudyType[] = ["RSI", "MACD", "Stoch"];

export const STUDY_DEFAULTS: { [K in StudyType]: Omit<Extract<StudyConfig, { type: K }>, "id"> } = {
  EMA:           { type: "EMA",           period: 20, color: "#f7c948" },
  SMA:           { type: "SMA",           period: 20, color: "#4caf50" },
  BB:            { type: "BB",            period: 20, std: 2, upperColor: "#2196f3", midColor: "#888888", lowerColor: "#2196f3" },
  VWAP:          { type: "VWAP",          color: "#ff9800" },
  RSI:           { type: "RSI",           period: 14, color: "#ce93d8" },
  MACD:          { type: "MACD",          fast: 12, slow: 26, signal: 9, macdColor: "#2196f3", signalColor: "#f7c948" },
  Stoch:         { type: "Stoch",         k: 14, d: 3, smooth: 3, kColor: "#2196f3", dColor: "#f7c948" },
  VolumeProfile: { type: "VolumeProfile", rows: 24, valueAreaPct: 70, upColor: "#26a69a88", downColor: "#ef535088", pocColor: "#f59e0b" },
  FVG:           { type: "FVG",           minGapPct: 0.1, showLabels: true, extendBoxes: true, bullColor: "#26a69a", bearColor: "#ef5350", opacity: 0.15 },
};

export function studyLabel(s: StudyConfig): string {
  switch (s.type) {
    case "EMA":           return `EMA(${s.period})`;
    case "SMA":           return `SMA(${s.period})`;
    case "BB":            return `BB(${s.period}, ${s.std})`;
    case "VWAP":          return "VWAP";
    case "RSI":           return `RSI(${s.period})`;
    case "MACD":          return `MACD(${s.fast},${s.slow},${s.signal})`;
    case "Stoch":         return `Stoch(${s.k},${s.d})`;
    case "VolumeProfile": return `VP(${s.rows})`;
    case "FVG":           return "FVG";
  }
}
