import { useState } from "react";
import type { UTCTimestamp } from "lightweight-charts";

export type DrawMode =
  | "cursor" | "hline" | "trendline" | "fibonacci"
  | "long_position" | "short_position";

export type HLineD    = { id: string; type: "hline";          price: number; color: string };
export type TrendD    = { id: string; type: "trendline";      t1: UTCTimestamp; p1: number; t2: UTCTimestamp; p2: number; color: string };
export type FibD      = { id: string; type: "fibonacci";      t1: UTCTimestamp; p1: number; t2: UTCTimestamp; p2: number };
export type LongPosD  = { id: string; type: "long_position";  t: UTCTimestamp; entry: number; target: number; stop: number };
export type ShortPosD = { id: string; type: "short_position"; t: UTCTimestamp; entry: number; target: number; stop: number };
export type Drawing = HLineD | TrendD | FibD | LongPosD | ShortPosD;

const TOOLS: { mode: DrawMode; icon: string; label: string; clicks: number }[] = [
  { mode: "cursor",         icon: "↖", label: "Cursor",        clicks: 0 },
  { mode: "hline",          icon: "—", label: "H-Line",         clicks: 1 },
  { mode: "trendline",      icon: "╱", label: "Trend",          clicks: 2 },
  { mode: "fibonacci",      icon: "∿", label: "Fibonacci",      clicks: 2 },
  { mode: "long_position",  icon: "↑", label: "Long Position",  clicks: 3 },
  { mode: "short_position", icon: "↓", label: "Short Position", clicks: 3 },
];

function drawingLabel(d: Drawing): string {
  if (d.type === "hline")          return `H ${d.price.toFixed(2)}`;
  if (d.type === "trendline")      return "Trend";
  if (d.type === "fibonacci")      return "Fib";
  if (d.type === "long_position")  return `Long ${d.entry.toFixed(2)}`;
  if (d.type === "short_position") return `Short ${d.entry.toFixed(2)}`;
  return "Drawing";
}

const TV = {
  bg: "#131722", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86",
  accent: "#2962ff", up: "#26a69a", down: "#ef5350", warn: "#f59e0b",
} as const;

interface Props {
  mode: DrawMode;
  onMode: (m: DrawMode) => void;
  drawings: Drawing[];
  onClearAll: () => void;
  onRemoveDrawing: (id: string) => void;
  pendingClicks: number;
}

export default function DrawingDrawer({
  mode, onMode, drawings, onClearAll, onRemoveDrawing, pendingClicks,
}: Props) {
  const [open, setOpen] = useState(false);

  const tool    = TOOLS.find(t => t.mode === mode);
  const modeClr = mode === "long_position" ? TV.up : mode === "short_position" ? TV.down : mode !== "cursor" ? TV.accent : TV.muted;

  return (
    <div style={{
      width: open ? 148 : 26,
      transition: "width 0.15s ease",
      flexShrink: 0,
      background: TV.bg,
      borderRight: `1px solid ${TV.border}`,
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
      userSelect: "none",
    }}>
      {/* Toggle + current tool icon when collapsed */}
      <div style={{ display: "flex", alignItems: "center", flexShrink: 0 }}>
        <button
          title={open ? "Close drawings" : "Open drawings"}
          onClick={() => setOpen(v => !v)}
          style={{
            background: "transparent", border: "none",
            color: open ? TV.muted : modeClr,
            cursor: "pointer",
            width: 26, height: 26,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 13, flexShrink: 0,
          }}
        >
          {open ? "‹" : (tool?.icon ?? "✏")}
        </button>
        {open && (
          <span style={{ fontSize: 11, fontWeight: 600, color: TV.text, paddingLeft: 2 }}>Drawings</span>
        )}
      </div>

      {/* Pending click hint when collapsed */}
      {!open && pendingClicks > 0 && (
        <div style={{ width: 26, textAlign: "center", fontSize: 9, color: TV.warn, lineHeight: 1 }}>
          {pendingClicks}✦
        </div>
      )}

      {open && (
        <>
          {/* Tools */}
          <div style={{ borderTop: `1px solid ${TV.border}`, flexShrink: 0 }}>
            {TOOLS.map((t) => {
              const active = mode === t.mode;
              const clr    = t.mode === "long_position" ? TV.up : t.mode === "short_position" ? TV.down : TV.accent;
              return (
                <button
                  key={t.mode}
                  title={t.clicks > 0 ? `${t.label} (${t.clicks} clicks)` : t.label}
                  onClick={() => onMode(t.mode)}
                  style={{
                    width: "100%",
                    background: active ? clr + "18" : "transparent",
                    border: "none",
                    borderLeft: `2px solid ${active ? clr : "transparent"}`,
                    color: active ? clr : TV.muted,
                    fontSize: 11, padding: "5px 8px",
                    cursor: "pointer",
                    display: "flex", alignItems: "center", gap: 7,
                    textAlign: "left",
                  }}
                >
                  <span style={{ fontSize: 13, width: 14, textAlign: "center", flexShrink: 0 }}>
                    {t.icon}
                  </span>
                  <span>{t.label}</span>
                  {active && t.clicks > 0 && pendingClicks > 0 && (
                    <span style={{ marginLeft: "auto", fontSize: 9, color: TV.warn }}>
                      {pendingClicks}/{t.clicks}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Active drawings list */}
          {drawings.length > 0 && (
            <>
              <div style={{
                borderTop: `1px solid ${TV.border}`,
                padding: "4px 8px 2px",
                fontSize: 9, color: TV.muted,
                textTransform: "uppercase", letterSpacing: 0.5,
                flexShrink: 0,
              }}>
                Active ({drawings.length})
              </div>
              <div style={{ flex: 1, overflowY: "auto" }}>
                {drawings.map((d) => (
                  <div key={d.id} style={{
                    display: "flex", alignItems: "center",
                    padding: "2px 8px", gap: 4,
                    borderBottom: `1px solid ${TV.border}22`,
                  }}>
                    <span style={{
                      flex: 1, fontSize: 10, color: TV.text,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                      {drawingLabel(d)}
                    </span>
                    <button
                      onClick={() => onRemoveDrawing(d.id)}
                      style={{
                        background: "transparent", border: "none",
                        color: TV.down, cursor: "pointer",
                        fontSize: 11, padding: "0 2px", lineHeight: 1, flexShrink: 0,
                      }}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
              <div style={{ borderTop: `1px solid ${TV.border}`, padding: 6, flexShrink: 0 }}>
                <button
                  onClick={onClearAll}
                  style={{
                    width: "100%", background: "transparent",
                    border: `1px solid ${TV.border}`,
                    borderRadius: 3, color: TV.down,
                    fontSize: 10, padding: "3px 0",
                    cursor: "pointer",
                  }}
                >
                  Clear All
                </button>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
