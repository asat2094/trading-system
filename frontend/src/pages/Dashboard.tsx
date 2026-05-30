import { useEffect } from "react";
import { useDashboardStore } from "../store/dashboard";
import { useLiveQuotesStore } from "../store/liveQuotes";
import MarketStatusBar from "../components/Dashboard/MarketStatusBar";
import PaneGrid from "../components/Dashboard/PaneGrid";
import * as marketWs from "../lib/marketWs";

const TV = { bg: "#0d0d1a", border: "#2a2e39", text: "#d1d4dc", muted: "#787b86", accent: "#2962ff" } as const;
const PANE_COUNTS = [1, 2, 4, 6, 8] as const;

function TopBar() {
  const { paneCount, setPaneCount } = useDashboardStore();
  const brokerStatus = useLiveQuotesStore((s) => s.brokerStatus);
  const isUpstoxConnected = brokerStatus["upstox"] === "connected";

  const openUpstoxLogin = () => {
    window.open(
      "http://localhost:8000/auth/upstox/login",
      "upstox-login",
      "width=500,height=700,resizable=yes"
    );
  };

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: "6px 12px", background: TV.bg,
      borderBottom: `1px solid ${TV.border}`,
      flexShrink: 0,
    }}>
      <span style={{ fontSize: 14, fontWeight: 700, color: TV.accent }}>
        📊 Dashboard
      </span>

      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 11, color: TV.muted }}>Panes:</span>
        <select
          value={paneCount}
          onChange={(e) => setPaneCount(Number(e.target.value) as typeof PANE_COUNTS[number])}
          style={{
            background: "#1e222d", border: `1px solid ${TV.border}`,
            borderRadius: 3, color: TV.text, padding: "2px 6px",
            fontSize: 11, cursor: "pointer", outline: "none",
          }}
        >
          {PANE_COUNTS.map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
      </div>

      <div style={{ flex: 1 }} />

      {/* Hyperliquid status */}
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <span
          style={{
            width: 7, height: 7, borderRadius: "50%",
            background: brokerStatus["hyperliquid"] === "connected" ? "#26a69a" : "#787b86",
            display: "inline-block",
          }}
        />
        <span style={{ fontSize: 11, color: TV.muted }}>Hyperliquid</span>
      </div>

      {/* Connect Upstox */}
      <button
        onClick={openUpstoxLogin}
        style={{
          background: isUpstoxConnected ? "#26a69a22" : "transparent",
          border: `1px solid ${isUpstoxConnected ? "#26a69a" : TV.border}`,
          borderRadius: 4, color: isUpstoxConnected ? "#26a69a" : TV.muted,
          fontSize: 11, padding: "4px 10px", cursor: "pointer",
          display: "flex", alignItems: "center", gap: 5,
        }}
      >
        {isUpstoxConnected ? (
          <>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#26a69a", display: "inline-block" }} />
            Upstox
          </>
        ) : (
          "Connect Upstox"
        )}
      </button>
    </div>
  );
}

export default function Dashboard() {
  useEffect(() => {
    const token = localStorage.getItem("access_token") ?? "";
    marketWs.connect(token);
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: TV.bg, overflow: "hidden" }}>
      <TopBar />
      <MarketStatusBar />
      <PaneGrid />
    </div>
  );
}
