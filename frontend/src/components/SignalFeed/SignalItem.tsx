import { useNavigate } from "react-router-dom";

interface Signal {
  symbol: string;
  signal_name: string;
  direction: string;
  strength_score: number;
  timestamp: string;
  event_id: string;
}

export default function SignalItem({ signal, compact = false }: { signal: Signal; compact?: boolean }) {
  const navigate = useNavigate();
  const isBull = signal.direction === "bullish";
  const color = isBull ? "#26a69a" : "#ef5350";

  if (compact) {
    return (
      <div
        onClick={() => navigate(`/chart/${signal.symbol}`)}
        style={{ padding: "6px 16px", borderBottom: "1px solid #1e222d", cursor: "pointer", borderLeft: `2px solid ${color}` }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ color, fontSize: 12, fontWeight: 600 }}>{signal.symbol}</span>
          <span style={{ fontSize: 10, color: "#363c4e" }}>{new Date(signal.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
        </div>
        <div style={{ fontSize: 11, color: "#787b86", marginTop: 1 }}>{signal.signal_name}</div>
      </div>
    );
  }

  return (
    <div
      onClick={() => navigate(`/chart/${signal.symbol}`)}
      style={{ padding: "12px 16px", borderBottom: "1px solid #1e222d", cursor: "pointer", background: "#131722", borderLeft: `3px solid ${color}`, marginBottom: 4 }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
        <div>
          <span style={{ color, fontSize: 14, fontWeight: 700, fontFamily: "monospace" }}>{signal.symbol}</span>
          <span style={{ marginLeft: 8, fontSize: 11, padding: "2px 6px", borderRadius: 3, background: isBull ? "rgba(38,166,154,0.15)" : "rgba(239,83,80,0.15)", color }}>{signal.direction}</span>
        </div>
        <span style={{ fontSize: 11, color: "#787b86" }}>{new Date(signal.timestamp).toLocaleTimeString()}</span>
      </div>
      <div style={{ fontSize: 12, color: "#d1d4dc", marginBottom: 6 }}>{signal.signal_name}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} style={{ width: 16, height: 4, borderRadius: 2, background: i < signal.strength_score ? color : "#2a2e39" }} />
        ))}
        <span style={{ fontSize: 11, color: "#787b86", marginLeft: 4 }}>strength {signal.strength_score}/5</span>
      </div>
    </div>
  );
}
