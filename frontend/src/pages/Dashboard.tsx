import { useEffect, useState } from "react";
import { useDashboardStore } from "../store/dashboard";
import { useLiveQuotesStore } from "../store/liveQuotes";
import MarketStatusBar from "../components/Dashboard/MarketStatusBar";
import PaneGrid from "../components/Dashboard/PaneGrid";
import IndicatorPanel from "../components/Dashboard/IndicatorPanel";
import * as marketWs from "../lib/marketWs";
import { apiClient, isAuthenticated } from "../api/client";

const TV = { bg: "#0d0d1a", border: "#2a2e39", text: "#d1d4dc", muted: "#787b86", accent: "#2962ff" } as const;
const PANE_COUNTS = [1, 2, 4, 6, 8] as const;

function BrokerBtn({
  connected, label, onConnect, popupBlocked, children,
}: {
  connected: boolean; label: string; onConnect: () => void;
  popupBlocked?: boolean; children?: React.ReactNode;
}) {
  const color = connected ? "#26a69a" : popupBlocked ? "#ef5350" : TV.muted;
  const bg    = connected ? "#26a69a22" : popupBlocked ? "#ef535022" : "transparent";
  const border = connected ? "#26a69a" : popupBlocked ? "#ef5350" : TV.border;
  return (
    <button
      onClick={connected ? undefined : onConnect}
      title={popupBlocked ? "Popup blocked — allow popups for localhost and try again" : undefined}
      style={{
        background: bg, border: `1px solid ${border}`, borderRadius: 4,
        color, fontSize: 11, padding: "4px 10px",
        cursor: connected ? "default" : "pointer",
        display: "flex", alignItems: "center", gap: 5,
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: color, display: "inline-block" }} />
      {children ?? (connected ? label : popupBlocked ? "Allow popups & retry" : `Connect ${label}`)}
    </button>
  );
}

function TopBar() {
  const { paneCount, setPaneCount } = useDashboardStore();
  const brokerStatus   = useLiveQuotesStore((s) => s.brokerStatus);
  const upstoxHasToken = useLiveQuotesStore((s) => s.upstoxHasToken);
  const kiteConnected  = useLiveQuotesStore((s) => s.kiteConnected);
  const kiteUser       = useLiveQuotesStore((s) => s.kiteUser);
  const isUpstoxConnected = brokerStatus["upstox"] === "connected";
  const isHlConnected     = brokerStatus["hyperliquid"] === "connected";

  const [upstoxPopupBlocked, setUpstoxPopupBlocked] = useState(false);
  const [kiteLoading, setKiteLoading] = useState(false);

  const openUpstoxLogin = () => {
    const popup = window.open("http://localhost:8000/auth/upstox/login", "upstox-login", "width=500,height=700,resizable=yes");
    if (!popup) setUpstoxPopupBlocked(true);
    else setUpstoxPopupBlocked(false);
  };

  const reconnectUpstox = async () => {
    try { await apiClient.post("/auth/upstox/reconnect"); } catch { /* ignore */ }
  };

  const reconnectHyperliquid = async () => {
    try { await apiClient.post("/auth/hyperliquid/reconnect"); } catch { /* ignore */ }
  };

  const connectKite = async () => {
    setKiteLoading(true);
    try {
      const { data } = await apiClient.get("/auth/kite/init");
      if (data.auth_url) {
        const popup = window.open(data.auth_url, "kite-login", "width=500,height=700,resizable=yes");
        if (popup) {
          // Poll status until authenticated (max 3 min)
          const poll = setInterval(async () => {
            try {
              const { data: s } = await apiClient.get("/auth/kite/status");
              if (s.connected) {
                useLiveQuotesStore.getState().setKiteStatus(true, s.user);
                clearInterval(poll);
                setKiteLoading(false);
                popup.close();
              }
            } catch { /* ignore */ }
          }, 3000);
          setTimeout(() => { clearInterval(poll); setKiteLoading(false); }, 180_000);
        }
      }
    } catch {
      setKiteLoading(false);
    }
  };

  // Check Kite status on mount
  useEffect(() => {
    apiClient.get("/auth/kite/status").then(({ data }) => {
      useLiveQuotesStore.getState().setKiteStatus(data.connected, data.user);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    const ALLOWED = new Set(["http://localhost:8000", "http://127.0.0.1:8000"]);
    const handler = async (evt: MessageEvent) => {
      if (!ALLOWED.has(evt.origin)) return;
      if (evt.data?.type === "upstox-auth-complete") {
        try {
          const { data } = await apiClient.get("/auth/upstox/status");
          const store = useLiveQuotesStore.getState();
          store.setUpstoxHasToken(data.connected);
          store.setBrokerStatus({ ...store.brokerStatus, upstox: data.connected ? "connected" : "disconnected" });
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
          {PANE_COUNTS.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </div>

      <div style={{ flex: 1 }} />

      {/* Hyperliquid */}
      <BrokerBtn connected={isHlConnected} label="Hyperliquid" onConnect={reconnectHyperliquid}>
        {isHlConnected ? "Hyperliquid" : "Reconnect HL"}
      </BrokerBtn>

      {/* Upstox */}
      <BrokerBtn
        connected={isUpstoxConnected} label="Upstox"
        onConnect={upstoxHasToken ? reconnectUpstox : openUpstoxLogin}
        popupBlocked={upstoxPopupBlocked}
      >
        {isUpstoxConnected ? "Upstox" : upstoxHasToken ? "Reconnect Upstox" : undefined}
      </BrokerBtn>

      {/* Kite */}
      <BrokerBtn
        connected={kiteConnected} label="Kite"
        onConnect={connectKite}
      >
        {kiteConnected ? (kiteUser ? `Kite · ${kiteUser}` : "Kite") : kiteLoading ? "Connecting…" : undefined}
      </BrokerBtn>
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
