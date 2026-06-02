/**
 * Shared broker connect/status buttons (Upstox, Kite).
 * Used in Dashboard TopBar and FnO Live header.
 */
import { useEffect, useState } from "react";
import { useLiveQuotesStore } from "../../store/liveQuotes";
import { apiClient } from "../../api/client";

const TV = { border: "#2a2e39", muted: "#787b86" } as const;

function BrokerBtn({
  connected, label, onConnect, popupBlocked, children,
}: {
  connected: boolean; label: string; onConnect: () => void;
  popupBlocked?: boolean; children?: React.ReactNode;
}) {
  const color  = connected ? "#26a69a" : popupBlocked ? "#ef5350" : TV.muted;
  const bg     = connected ? "#26a69a22" : popupBlocked ? "#ef535022" : "transparent";
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

export default function BrokerConnectButtons() {
  const brokerStatus   = useLiveQuotesStore((s) => s.brokerStatus);
  const upstoxHasToken = useLiveQuotesStore((s) => s.upstoxHasToken);
  const kiteConnected  = useLiveQuotesStore((s) => s.kiteConnected);
  const kiteUser       = useLiveQuotesStore((s) => s.kiteUser);
  const isUpstoxConnected = brokerStatus["upstox"] === "connected";

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

  const connectKite = async () => {
    setKiteLoading(true);
    try {
      const { data } = await apiClient.get("/auth/kite/init");
      if (data.auth_url) {
        const popup = window.open(data.auth_url, "kite-login", "width=500,height=700,resizable=yes");
        if (popup) {
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

  // Check both broker statuses on mount
  useEffect(() => {
    apiClient.get("/auth/kite/status").then(({ data }) => {
      useLiveQuotesStore.getState().setKiteStatus(data.connected, data.user);
    }).catch(() => {});
    apiClient.get("/auth/upstox/status").then(({ data }) => {
      const store = useLiveQuotesStore.getState();
      store.setUpstoxHasToken(data.connected);
      if (data.connected) {
        store.setBrokerStatus({ ...store.brokerStatus, upstox: "connected" });
      }
    }).catch(() => {});
  }, []);

  // Listen for Upstox OAuth callback
  useEffect(() => {
    const ALLOWED = new Set(["http://localhost:8000", "http://127.0.0.1:8000"]);
    const handler = async (evt: MessageEvent) => {
      if (!ALLOWED.has(evt.origin)) return;
      if (evt.data?.type === "upstox-auth-complete") {
        try {
          // Trigger backend WS reconnect with new token, then check status
          await apiClient.post("/auth/upstox/reconnect").catch(() => {});
          // Poll status briefly — WS reconnect is async, give it 2s
          await new Promise(r => setTimeout(r, 2000));
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
    <>
      <BrokerBtn
        connected={isUpstoxConnected} label="Upstox"
        onConnect={upstoxHasToken ? reconnectUpstox : openUpstoxLogin}
        popupBlocked={upstoxPopupBlocked}
      >
        {isUpstoxConnected ? "Upstox" : upstoxHasToken ? "Reconnect Upstox" : undefined}
      </BrokerBtn>

      <BrokerBtn
        connected={kiteConnected} label="Kite"
        onConnect={connectKite}
      >
        {kiteConnected ? (kiteUser ? `Kite · ${kiteUser}` : "Kite") : kiteLoading ? "Connecting…" : undefined}
      </BrokerBtn>
    </>
  );
}
