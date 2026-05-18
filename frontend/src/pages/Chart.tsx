import { useParams, useNavigate } from "react-router-dom";
import CandlestickChart from "../components/Chart/CandlestickChart";
import { useOHLCV } from "../api/technical";

export default function Chart() {
  const { symbol } = useParams<{ symbol: string }>();
  const navigate = useNavigate();
  const today = new Date().toISOString().split("T")[0];
  const yearAgo = new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString().split("T")[0];
  const { data: rows, isLoading, isError } = useOHLCV(symbol!, "1d", yearAgo, today);

  return (
    <div style={{ padding: 24, height: "100vh", display: "flex", flexDirection: "column", background: "#0d0d1a" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
        <button
          onClick={() => navigate(-1)}
          style={{ background: "#1e222d", border: "1px solid #2a2e39", borderRadius: 4, color: "#787b86", padding: "6px 12px", cursor: "pointer", fontSize: 13 }}
        >
          ← Back
        </button>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, fontFamily: "monospace", color: "#d1d4dc" }}>
          {symbol}
          <span style={{ marginLeft: 8, fontSize: 12, fontFamily: "sans-serif", color: "#787b86", fontWeight: 400 }}>NSE</span>
        </h2>
      </div>
      <div style={{ flex: 1, background: "#131722", borderRadius: 6, border: "1px solid #2a2e39", overflow: "hidden" }}>
        {isLoading ? (
          <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#787b86" }}>
            <div>Loading chart data...</div>
          </div>
        ) : isError || !rows || rows.length === 0 ? (
          <div style={{ height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "#363c4e" }}>
            <div style={{ fontSize: 48, marginBottom: 16 }}>📊</div>
            <div style={{ fontSize: 14, color: "#787b86", marginBottom: 8 }}>No chart data available</div>
            <div style={{ fontSize: 12, color: "#363c4e" }}>Run a backfill to load historical data</div>
          </div>
        ) : (
          <CandlestickChart bars={rows} />
        )}
      </div>
    </div>
  );
}
