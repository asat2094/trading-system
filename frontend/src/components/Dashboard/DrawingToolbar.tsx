export type DrawMode = "cursor" | "hline" | "trendline" | "fibonacci";

interface Props {
  mode: DrawMode;
  onMode: (m: DrawMode) => void;
  hasDrawings: boolean;
  onClearAll: () => void;
}

const TOOLS: { mode: DrawMode; label: string; title: string }[] = [
  { mode: "cursor",    label: "↖",  title: "Select / Pan" },
  { mode: "hline",     label: "—",  title: "Horizontal Line" },
  { mode: "trendline", label: "╱",  title: "Trend Line (2 clicks)" },
  { mode: "fibonacci", label: "∿",  title: "Fibonacci Retracement (2 clicks)" },
];

const TV = { border: "#2a2e39", muted: "#787b86", accent: "#2962ff", bg: "#1a1e2e" } as const;

export default function DrawingToolbar({ mode, onMode, hasDrawings, onClearAll }: Props) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 2, flexShrink: 0 }}>
      {TOOLS.map((t) => (
        <button
          key={t.mode}
          title={t.title}
          onClick={() => onMode(t.mode)}
          style={{
            background: mode === t.mode ? TV.accent : "transparent",
            border: `1px solid ${mode === t.mode ? TV.accent : TV.border}`,
            borderRadius: 3,
            color: mode === t.mode ? "#fff" : TV.muted,
            fontSize: 12,
            width: 22,
            height: 20,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 0,
          }}
        >
          {t.label}
        </button>
      ))}
      {hasDrawings && (
        <button
          title="Clear all drawings"
          onClick={onClearAll}
          style={{
            background: "transparent", border: `1px solid ${TV.border}`,
            borderRadius: 3, color: "#ef5350",
            fontSize: 9, padding: "1px 4px",
            cursor: "pointer", marginLeft: 2,
          }}
        >
          ✕
        </button>
      )}
    </div>
  );
}
