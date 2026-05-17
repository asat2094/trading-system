import SignalFeedPanel from "../SignalFeed/SignalFeedPanel";
import { useSignalsStore } from "../../store/signals";

export default function Sidebar() {
  const { wsStatus } = useSignalsStore();
  const statusColor = wsStatus === "connected" ? "#089981" : wsStatus === "connecting" ? "#f5a623" : "#f23645";

  return (
    <div style={{ width: 280, borderRight: "1px solid #222", display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "8px 12px", borderBottom: "1px solid #222", display: "flex", justifyContent: "space-between" }}>
        <strong>Trading System</strong>
        <span style={{ color: statusColor, fontSize: 11 }}>● {wsStatus}</span>
      </div>
      <div style={{ flex: 1, overflow: "hidden" }}>
        <SignalFeedPanel />
      </div>
    </div>
  );
}
