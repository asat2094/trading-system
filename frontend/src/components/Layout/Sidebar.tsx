import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useSignalsStore } from "../../store/signals";
import SignalItem from "../SignalFeed/SignalItem";
import { logout } from "../../api/client";

const NAV_ITEMS = [
  { path: "/screener", icon: "⊞", label: "Screener" },
  { path: "/chart",    icon: "📊", label: "Dashboard" },
  { path: "/signals",  icon: "🔔", label: "Signals" },
  { path: "/chat",     icon: "💬", label: "AI Chat" },
  { path: "/fno",      icon: "📈", label: "FnO Live" },
];

const TV = {
  bg: "#131722", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86",
  accent: "#2962ff",
} as const;

export default function Sidebar() {
  const { wsStatus, signals } = useSignalsStore();
  const navigate = useNavigate();

  const [open, setOpen] = useState(() => localStorage.getItem("sidebar-collapsed") !== "true");

  const toggle = () => {
    const next = !open;
    setOpen(next);
    localStorage.setItem("sidebar-collapsed", String(!next));
  };

  const statusColor = wsStatus === "connected" ? "#26a69a" : wsStatus === "connecting" ? "#f59e0b" : "#ef5350";

  const navStyle = (isActive: boolean): React.CSSProperties => ({
    display: "flex",
    alignItems: "center",
    gap: open ? 10 : 0,
    padding: open ? "9px 16px" : "10px 0",
    justifyContent: open ? "flex-start" : "center",
    color: isActive ? TV.text : TV.muted,
    background: isActive ? "#1e222d" : "transparent",
    borderLeft: `3px solid ${isActive ? TV.accent : "transparent"}`,
    textDecoration: "none",
    fontSize: 13,
    fontWeight: isActive ? 600 : 400,
    cursor: "pointer",
    transition: "all 0.1s",
    whiteSpace: "nowrap",
    overflow: "hidden",
  });

  return (
    <div style={{
      width: open ? 220 : 44,
      transition: "width 0.15s ease",
      background: TV.bg,
      borderRight: `1px solid ${TV.border}`,
      display: "flex", flexDirection: "column",
      flexShrink: 0, overflow: "hidden",
    }}>
      {/* Logo + collapse toggle */}
      <div style={{
        padding: open ? "12px 16px" : "12px 0",
        borderBottom: `1px solid ${TV.border}`,
        display: "flex", alignItems: "center",
        justifyContent: open ? "space-between" : "center",
        flexShrink: 0,
      }}>
        {open && (
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: TV.accent, whiteSpace: "nowrap" }}>⚡ TradingOS</div>
            <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 4 }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: statusColor, display: "inline-block" }} />
              <span style={{ fontSize: 10, color: TV.muted, textTransform: "uppercase", letterSpacing: "0.5px" }}>{wsStatus}</span>
            </div>
          </div>
        )}
        {!open && (
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: statusColor, display: "inline-block" }} />
        )}
        <button
          onClick={toggle}
          title={open ? "Collapse sidebar" : "Expand sidebar"}
          style={{
            background: "transparent", border: "none",
            color: TV.muted, cursor: "pointer",
            fontSize: 14, padding: "2px 4px",
            lineHeight: 1, flexShrink: 0,
            marginLeft: open ? 8 : 0,
          }}
        >
          {open ? "‹" : "›"}
        </button>
      </div>

      {/* Navigation */}
      <nav style={{ padding: "8px 0", flexShrink: 0 }}>
        {NAV_ITEMS.map(({ path, icon, label }) => (
          <NavLink
            key={path}
            to={path}
            style={({ isActive }) => navStyle(isActive)}
            title={!open ? label : undefined}
          >
            <span style={{ fontSize: 15, flexShrink: 0, lineHeight: 1 }}>{icon}</span>
            {open && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Recent Signals — expanded only */}
      {open && (
        <div style={{ flex: 1, overflow: "hidden", borderTop: `1px solid ${TV.border}`, display: "flex", flexDirection: "column" }}>
          <div style={{
            padding: "8px 16px", fontSize: 11, color: TV.muted,
            textTransform: "uppercase", letterSpacing: "0.8px",
            display: "flex", justifyContent: "space-between", alignItems: "center",
            flexShrink: 0,
          }}>
            <span>Recent Signals</span>
            {signals.length > 0 && (
              <span style={{ background: TV.accent, color: "#fff", borderRadius: 10, padding: "1px 6px", fontSize: 10 }}>
                {signals.length}
              </span>
            )}
          </div>
          <div style={{ flex: 1, overflowY: "auto" }}>
            {signals.slice(0, 8).map((sig) => <SignalItem key={sig.event_id} signal={sig} compact />)}
            {signals.length === 0 && (
              <div style={{ padding: "12px 16px", color: "#363c4e", fontSize: 12 }}>No signals yet</div>
            )}
          </div>
        </div>
      )}

      {/* Signals badge when collapsed */}
      {!open && signals.length > 0 && (
        <div style={{ display: "flex", justifyContent: "center", padding: "4px 0", flexShrink: 0 }}>
          <span style={{ background: TV.accent, color: "#fff", borderRadius: 10, padding: "1px 5px", fontSize: 9 }}>
            {signals.length}
          </span>
        </div>
      )}

      {/* Logout */}
      <div style={{
        padding: open ? "12px 16px" : "10px 0",
        borderTop: `1px solid ${TV.border}`,
        display: "flex", justifyContent: "center",
        flexShrink: 0,
      }}>
        {open ? (
          <button
            onClick={() => { logout(); navigate("/login"); }}
            style={{
              width: "100%", padding: "7px 0",
              background: "transparent", border: `1px solid ${TV.border}`,
              borderRadius: 4, color: TV.muted, fontSize: 12, cursor: "pointer",
            }}
          >
            Sign Out
          </button>
        ) : (
          <button
            onClick={() => { logout(); navigate("/login"); }}
            title="Sign Out"
            style={{ background: "transparent", border: "none", color: TV.muted, cursor: "pointer", fontSize: 15, padding: 2 }}
          >
            ⏻
          </button>
        )}
      </div>
    </div>
  );
}
