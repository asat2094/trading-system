import { useState, useEffect } from "react";
import ChartUnit from "../Chart/ChartUnit";

const TV = {
  bg: "#131722", header: "#1a1e2e", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86", accent: "#2962ff",
} as const;

const TIMEFRAMES = ["1min", "5min", "15min", "30min", "1h", "4h", "1d"];

interface Props {
  symbol: string;
  label:  string;
  onClose: () => void;
}

export default function FnoChartModal({ symbol, label, onClose }: Props) {
  const [timeframe, setTimeframe] = useState("15min");

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
              >
                {tf}
              </button>
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

        {/* ChartUnit — full feature chart (drawing drawer, indicators, live ticks, price labels) */}
        <ChartUnit symbol={symbol} timeframe={timeframe} />
      </div>
    </div>
  );
}
