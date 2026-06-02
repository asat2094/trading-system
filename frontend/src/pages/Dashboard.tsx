import { useEffect, useState } from "react";
import { useDashboardStore } from "../store/dashboard";
import { useLiveQuotesStore } from "../store/liveQuotes";
import MarketStatusBar from "../components/Dashboard/MarketStatusBar";
import PaneGrid from "../components/Dashboard/PaneGrid";
import IndicatorPanel from "../components/Dashboard/IndicatorPanel";
import BrokerConnectButtons from "../components/shared/BrokerConnectButtons";
import * as marketWs from "../lib/marketWs";
import { apiClient, isAuthenticated } from "../api/client";

const TV = { bg: "#0d0d1a", border: "#2a2e39", text: "#d1d4dc", muted: "#787b86", accent: "#2962ff" } as const;
const PANE_COUNTS = [1, 2, 4, 6, 8] as const;

function TopBar() {
  const { paneCount, setPaneCount } = useDashboardStore();
  const brokerStatus  = useLiveQuotesStore((s) => s.brokerStatus);
  const isHlConnected = brokerStatus["hyperliquid"] === "connected";

  const reconnectHyperliquid = async () => {
    try { await apiClient.post("/auth/hyperliquid/reconnect"); } catch { /* ignore */ }
  };

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: "6px 12px", background: TV.bg,
      borderBottom: `1px solid ${TV.border}`,
      flexShrink: 0,
    }}>
      <span data-testid="dashboard-title" style={{ fontSize: 14, fontWeight: 700, color: TV.accent }}>
        📊 Dashboard
      </span>

      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 11, color: TV.muted }}>Panes:</span>
        <select
          data-testid="pane-count-select"
          value={paneCount}
          onChange={(e) => setPaneCount(Number(e.target.value) as typeof PANE_COUNTS[number])}
          style={{
            background: "#1e222d", border: `1px solid ${TV.border}`,
            borderRadius: 3, color: TV.text, padding: "2px 6px",
            fontSize: 11, cursor: "pointer", outline: "none",
          }}
        >
          {PANE_COUNTS.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </div>

      <div style={{ flex: 1 }} />

      {/* Hyperliquid */}
      <button
        onClick={isHlConnected ? undefined : reconnectHyperliquid}
        style={{
          background: isHlConnected ? "#26a69a22" : "transparent",
          border: `1px solid ${isHlConnected ? "#26a69a" : TV.border}`,
          borderRadius: 4, color: isHlConnected ? "#26a69a" : TV.muted,
          fontSize: 11, padding: "4px 10px", cursor: isHlConnected ? "default" : "pointer",
          display: "flex", alignItems: "center", gap: 5,
        }}
      >
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: isHlConnected ? "#26a69a" : TV.muted, display: "inline-block" }} />
        {isHlConnected ? "Hyperliquid" : "Reconnect HL"}
      </button>

      <BrokerConnectButtons />
    </div>
  );
}

export default function Dashboard() {
  const [indicatorOpen, setIndicatorOpen] = useState(false);
  const { panes, focusedPaneId } = useDashboardStore();
  const focusedPane = panes.find(p => p.id === focusedPaneId) ?? panes[0];

  useEffect(() => {
    if (!isAuthenticated()) { window.location.href = "/login"; return; }
    const token = localStorage.getItem("access_token") ?? "";
    marketWs.connect(token);
  }, []);

  useEffect(() => {
    const checkStatus = async () => {
      try {
        const { data } = await apiClient.get("/auth/upstox/status");
        const store = useLiveQuotesStore.getState();
        store.setUpstoxHasToken(data.connected);
        if (!data.connected) store.setBrokerStatus({ ...store.brokerStatus, upstox: "disconnected" });
      } catch { /* ignore */ }
    };
    checkStatus();
    const interval = setInterval(checkStatus, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: TV.bg, overflow: "hidden" }}>
      <TopBar />
      <MarketStatusBar
        onToggleIndicators={() => setIndicatorOpen(v => !v)}
        indicatorOpen={indicatorOpen}
      />

      {/* Main content: pane grid + optional global indicator side panel */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        <PaneGrid />

        {indicatorOpen && (
          <div style={{
            width: 280, flexShrink: 0,
            display: "flex", flexDirection: "column",
            overflow: "hidden",
          }}>
            <IndicatorPanel
              paneId={focusedPane?.id ?? panes[0]?.id ?? ""}
              indicators={focusedPane?.indicators ?? []}
              onClose={() => setIndicatorOpen(false)}
              mode="global"
            />
          </div>
        )}
      </div>
    </div>
  );
}
