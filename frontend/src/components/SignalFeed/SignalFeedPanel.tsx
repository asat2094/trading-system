import { useEffect } from "react";
import { useSignalsStore } from "../../store/signals";
import SignalItem from "./SignalItem";

const WS_URL = import.meta.env.VITE_WS_BASE ?? "ws://localhost:8000";

export default function SignalFeedPanel() {
  const { signals, lastEventId, addSignal, setLastEventId, setWsStatus } = useSignalsStore();

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) return;
    let ws: WebSocket;
    function connect() {
      setWsStatus("connecting");
      ws = new WebSocket(`${WS_URL}/ws/signals?token=${token}&last_event_id=${lastEventId}`);
      ws.onopen = () => setWsStatus("connected");
      ws.onclose = () => { setWsStatus("disconnected"); setTimeout(connect, 3000); };
      ws.onerror = () => ws.close();
      ws.onmessage = (evt) => {
        const data = JSON.parse(evt.data);
        addSignal(data);
        setLastEventId(data.event_id);
      };
    }
    connect();
    return () => ws?.close();
  }, []);

  return (
    <div style={{ padding: 24, height: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>Live Signals</h2>
        {signals.length > 0 && (
          <span style={{ background: "#2962ff", color: "#fff", borderRadius: 12, padding: "2px 10px", fontSize: 12 }}>{signals.length}</span>
        )}
      </div>
      {signals.length === 0 ? (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: 300, color: "#363c4e" }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>🔔</div>
          <div style={{ fontSize: 14, color: "#787b86", marginBottom: 8 }}>Waiting for signals...</div>
          <div style={{ fontSize: 12, color: "#363c4e" }}>Signals will appear here when the scanner detects opportunities</div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {signals.map((sig) => <SignalItem key={sig.event_id} signal={sig} />)}
        </div>
      )}
    </div>
  );
}
