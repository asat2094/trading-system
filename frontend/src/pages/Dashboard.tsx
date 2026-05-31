import { useEffect, useState } from "react";
import { useDashboardStore } from "../store/dashboard";
import { useLiveQuotesStore } from "../store/liveQuotes";
import MarketStatusBar from "../components/Dashboard/MarketStatusBar";
import PaneGrid from "../components/Dashboard/PaneGrid";
import * as marketWs from "../lib/marketWs";
import { apiClient, isAuthenticated } from "../api/client";

const TV = { bg: "#0d0d1a", border: "#2a2e39", text: "#d1d4dc", muted: "#787b86", accent: "#2962ff" } as const;
const PANE_COUNTS = [1, 2, 4, 6, 8] as const;

function TopBar() {
  const { paneCount, setPaneCount } = useDashboardStore();
  const brokerStatus    = useLiveQuotesStore((s) => s.brokerStatus);
  const upstoxHasToken  = useLiveQuotesStore((s) => s.upstoxHasToken);
  const isUpstoxConnected = brokerStatus["upstox"] === "connected";
  const isHlConnected     = brokerStatus["hyperliquid"] === "connected";

  const [popupBlocked, setPopupBlocked] = useState(false);

  const openUpstoxLogin = () => {
    const popup = window.open(
      "http://localhost:8000/auth/upstox/login",
      "upstox-login",
      "width=500,height=700,resizable=yes"
    );
    if (!popup) {
      setPopupBlocked(true);
    } else {
      setPopupBlocked(false);
    }
  };

  const reconnectUpstox = async () => {
    try {
      await apiClient.post("/auth/upstox/reconnect");
    } catch { /* ignore — adapter will retry */ }
  };

  const reconnectHyperliquid = async () => {
    try {
      await apiClient.post("/auth/hyperliquid/reconnect");
    } catch { /* ignore */ }
  };

  // Listen for postMessage from Upstox OAuth popup.
  // The callback page origin is http://127.0.0.1:8000 (matches _UPSTOX_REDIRECT),
  // not http://localhost:8000 — must accept both.
  useEffect(() => {
    const ALLOWED = new Set(["http://localhost:8000", "http://127.0.0.1:8000"]);
    const handler = async (evt: MessageEvent) => {
      if (!ALLOWED.has(evt.origin)) return;
      if (evt.data?.type === "upstox-auth-complete") {
        try {
          const { data } = await apiClient.get("/auth/upstox/status");
          const store = useLiveQuotesStore.getState();
          store.setUpstoxHasToken(data.connected);
          store.setBrokerStatus({
            ...store.brokerStatus,
            upstox: data.connected ? "connected" : "disconnected",
          });
        } catch { /* ignore */ }
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

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
          {PANE_COUNTS.map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
      </div>

      <div style={{ flex: 1 }} />

      {/* Hyperliquid status / reconnect */}
      <button
        onClick={isHlConnected ? undefined : reconnectHyperliquid}
        style={{
          background: isHlConnected ? "#26a69a22" : "transparent",
          border: `1px solid ${isHlConnected ? "#26a69a" : TV.border}`,
          borderRadius: 4,
          color: isHlConnected ? "#26a69a" : TV.muted,
          fontSize: 11, padding: "4px 10px",
          cursor: isHlConnected ? "default" : "pointer",
          display: "flex", alignItems: "center", gap: 5,
        }}
      >
        <span style={{
          width: 6, height: 6, borderRadius: "50%",
          background: isHlConnected ? "#26a69a" : "#787b86",
          display: "inline-block",
        }} />
        {isHlConnected ? "Hyperliquid" : "Reconnect HL"}
      </button>

      {/* Connect / Reconnect Upstox */}
      <button
        onClick={isUpstoxConnected ? undefined : upstoxHasToken ? reconnectUpstox : openUpstoxLogin}
        title={popupBlocked ? "Popup blocked — allow popups for localhost and try again" : undefined}
        style={{
          background: isUpstoxConnected ? "#26a69a22" : popupBlocked ? "#ef535022" : "transparent",
          border: `1px solid ${isUpstoxConnected ? "#26a69a" : popupBlocked ? "#ef5350" : TV.border}`,
          borderRadius: 4,
          color: isUpstoxConnected ? "#26a69a" : popupBlocked ? "#ef5350" : TV.muted,
          fontSize: 11, padding: "4px 10px",
          cursor: isUpstoxConnected ? "default" : "pointer",
          display: "flex", alignItems: "center", gap: 5,
        }}
      >
        {isUpstoxConnected ? (
          <>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#26a69a", display: "inline-block" }} />
            Upstox
          </>
        ) : popupBlocked ? (
          "Allow popups & retry"
        ) : upstoxHasToken ? (
          "Reconnect Upstox"
        ) : (
          "Connect Upstox"
        )}
      </button>
    </div>
  );
}

export default function Dashboard() {
  useEffect(() => {
    if (!isAuthenticated()) {
      window.location.href = "/login";
      return;
    }
    const token = localStorage.getItem("access_token") ?? "";
    marketWs.connect(token);
  }, []);

  // Poll Upstox token status on mount + every 30s.
  // Populates upstoxHasToken so the button shows "Reconnect" after page refresh
  // when Redis still holds a token.
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const { data } = await apiClient.get("/auth/upstox/status");
        const store = useLiveQuotesStore.getState();
        store.setUpstoxHasToken(data.connected);
        if (!data.connected) {
          // Token gone — reflect in broker status too
          store.setBrokerStatus({ ...store.brokerStatus, upstox: "disconnected" });
        }
      } catch { /* ignore */ }
    };
    checkStatus();
    const interval = setInterval(checkStatus, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: TV.bg, overflow: "hidden" }}>
      <TopBar />
      <MarketStatusBar />
      <PaneGrid />
    </div>
  );
}
