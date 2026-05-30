import { NavLink, useNavigate } from "react-router-dom";
import { useSignalsStore } from "../../store/signals";
import SignalItem from "../SignalFeed/SignalItem";
import { logout } from "../../api/client";

const NAV_ITEMS = [
  { path: "/screener", icon: "⊞", label: "Screener" },
  { path: "/chart/RELIANCE", icon: "📈", label: "Charts" },
  { path: "/signals", icon: "🔔", label: "Signals" },
  { path: "/chat", icon: "💬", label: "AI Chat" },
  { path: "/fno", icon: "📈", label: "FnO Live" },
];

export default function Sidebar() {
  const { wsStatus, signals } = useSignalsStore();
  const navigate = useNavigate();
  const statusColor = wsStatus === "connected" ? "#26a69a" : wsStatus === "connecting" ? "#f59e0b" : "#ef5350";

  const navStyle = (isActive: boolean): React.CSSProperties => ({
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "9px 16px",
    color: isActive ? "#d1d4dc" : "#787b86",
    background: isActive ? "#1e222d" : "transparent",
    borderLeft: `3px solid ${isActive ? "#2962ff" : "transparent"}`,
    textDecoration: "none",
    fontSize: 13,
    fontWeight: isActive ? 600 : 400,
    cursor: "pointer",
    transition: "all 0.1s",
  });

  return (
    <div style={{ width: 220, background: "#131722", borderRight: "1px solid #2a2e39", display: "flex", flexDirection: "column", flexShrink: 0 }}>
      {/* Logo */}
      <div style={{ padding: "16px 16px 12px", borderBottom: "1px solid #2a2e39" }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: "#2962ff" }}>⚡ TradingOS</div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 6 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: statusColor, display: "inline-block" }} />
          <span style={{ fontSize: 11, color: "#787b86", textTransform: "uppercase", letterSpacing: "0.5px" }}>{wsStatus}</span>
        </div>
      </div>

      {/* Navigation */}
      <nav style={{ padding: "8px 0" }}>
        {NAV_ITEMS.map(({ path, icon, label }) => (
          <NavLink key={path} to={path} style={({ isActive }) => navStyle(isActive)}>
            <span style={{ fontSize: 14 }}>{icon}</span>
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Recent Signals */}
      <div style={{ flex: 1, overflow: "hidden", borderTop: "1px solid #2a2e39", display: "flex", flexDirection: "column" }}>
        <div style={{ padding: "8px 16px", fontSize: 11, color: "#787b86", textTransform: "uppercase", letterSpacing: "0.8px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>Recent Signals</span>
          {signals.length > 0 && (
            <span style={{ background: "#2962ff", color: "#fff", borderRadius: 10, padding: "1px 6px", fontSize: 10 }}>{signals.length}</span>
          )}
        </div>
        <div style={{ flex: 1, overflowY: "auto" }}>
          {signals.slice(0, 8).map((sig) => <SignalItem key={sig.event_id} signal={sig} compact />)}
          {signals.length === 0 && (
            <div style={{ padding: "12px 16px", color: "#363c4e", fontSize: 12 }}>No signals yet</div>
          )}
        </div>
      </div>

      {/* Logout */}
      <div style={{ padding: "12px 16px", borderTop: "1px solid #2a2e39" }}>
        <button
          onClick={() => { logout(); navigate("/login"); }}
          style={{ width: "100%", padding: "7px 0", background: "transparent", border: "1px solid #2a2e39", borderRadius: 4, color: "#787b86", fontSize: 12, cursor: "pointer" }}
        >
          Sign Out
        </button>
      </div>
    </div>
  );
}
