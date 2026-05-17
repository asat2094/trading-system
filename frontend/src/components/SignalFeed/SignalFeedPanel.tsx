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
      ws = new WebSocket(
        `${WS_URL}/ws/signals?token=${token}&last_event_id=${lastEventId}`
      );

      ws.onopen = () => setWsStatus("connected");
      ws.onclose = () => {
        setWsStatus("disconnected");
        setTimeout(connect, 3000);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (evt) => {
        const data = JSON.parse(evt.data);
        addSignal(data);
        setLastEventId(data.event_id);
      };
    }

    connect();
    return () => ws?.close();
  }, []); // connect once; reconnect loop handles resume

  return (
    <div style={{ height: "100%", overflowY: "auto" }}>
      <h4 style={{ padding: "8px 12px", margin: 0 }}>Live Signals</h4>
      {signals.map((sig) => <SignalItem key={sig.event_id} signal={sig} />)}
      {signals.length === 0 && (
        <div style={{ padding: 12, color: "#666" }}>Waiting for signals...</div>
      )}
    </div>
  );
}
