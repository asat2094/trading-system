import { JrnSummary } from "../../api/journal";

const TV = { bg: "#1e222d", border: "#2a2e39", text: "#d1d4dc", muted: "#787b86", green: "#26a69a", red: "#ef5350" };

function fmt(n: number) { return n >= 0 ? `+₹${n.toFixed(0)}` : `-₹${Math.abs(n).toFixed(0)}`; }
function fmtSec(s: number | null) {
  if (s == null) return "—";
  if (s < 60) return `${s}s`;
  return `${Math.floor(s/60)}m ${s%60}s`;
}

export default function DaySummaryCard({ s }: { s: JrnSummary }) {
  const pnlColor = s.net_pnl >= 0 ? TV.green : TV.red;
  return (
    <div style={{ background: TV.bg, border: `1px solid ${TV.border}`, borderRadius: 6, padding: 16, minWidth: 260 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
        <span style={{ fontWeight: 700, color: TV.text, fontSize: 14 }}>{s.trade_date}</span>
        {s.broker && <span style={{ fontSize: 11, color: TV.muted }}>{s.broker}</span>}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: pnlColor, marginBottom: 8 }}>{fmt(s.net_pnl)}</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, fontSize: 12, color: TV.muted }}>
        <span>Fills: <b style={{ color: TV.text }}>{s.total_fills}</b></span>
        <span>Lots: <b style={{ color: TV.text }}>{s.total_lots}</b></span>
        <span>W/L: <b style={{ color: TV.green }}>{s.win_pairs}</b>/<b style={{ color: TV.red }}>{s.loss_pairs}</b></span>
        <span>Charges: <b style={{ color: TV.red }}>₹{s.total_charges.toFixed(0)}</b></span>
        {s.avg_hold_seconds != null && <span>Avg hold: <b style={{ color: TV.text }}>{fmtSec(s.avg_hold_seconds)}</b></span>}
        {s.force_squared_count > 0 && <span style={{ color: TV.red }}>⚠ Force-sq: {s.force_squared_count}</span>}
      </div>
    </div>
  );
}
