import { useNavigate } from "react-router-dom";

interface Signal {
  symbol: string;
  signal_name: string;
  direction: string;
  strength_score: number;
  timestamp: string;
}

export default function SignalItem({ signal }: { signal: Signal }) {
  const navigate = useNavigate();
  const color = signal.direction === "bullish" ? "#089981" : "#f23645";

  return (
    <div
      onClick={() => navigate(`/chart/${signal.symbol}`)}
      style={{
        padding: "8px 12px",
        borderBottom: "1px solid #222",
        cursor: "pointer",
        borderLeft: `3px solid ${color}`,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <strong style={{ color }}>{signal.symbol}</strong>
        <span style={{ fontSize: 11, color: "#666" }}>
          {new Date(signal.timestamp).toLocaleTimeString()}
        </span>
      </div>
      <div style={{ fontSize: 12, color: "#aaa" }}>{signal.signal_name}</div>
    </div>
  );
}
