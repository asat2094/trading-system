import { JrnPair } from "../../api/journal";

const TV = { bg: "#131722", border: "#2a2e39", text: "#d1d4dc", muted: "#787b86", green: "#26a69a", red: "#ef5350", accent: "#2962ff" };

function fmtSec(s: number | null) {
  if (s == null) return "—";
  if (s < 60) return `${s}s`;
  return `${Math.floor(s/60)}m ${s%60}s`;
}

export default function PairsTable({ pairs }: { pairs: JrnPair[] }) {
  if (!pairs.length) return <div style={{ color: "#363c4e", fontSize: 13, padding: 16 }}>No pairs</div>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, color: TV.text }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${TV.border}`, color: TV.muted }}>
            {["Symbol","Side","Lots","Entry","Exit","Hold","Gross","Charges","Net",""].map(h => (
              <th key={h} style={{ padding: "6px 10px", textAlign: "left", fontWeight: 500 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {pairs.map(p => {
            const net = p.net_pnl ?? 0;
            const isOpen = p.close_date == null;
            return (
              <tr key={p.id} style={{ borderBottom: `1px solid #1e222d` }}>
                <td style={{ padding: "6px 10px", color: TV.accent }}>{p.symbol}</td>
                <td style={{ padding: "6px 10px", color: p.side === "LONG" ? TV.green : TV.red }}>{p.side}</td>
                <td style={{ padding: "6px 10px" }}>{p.lots ?? p.quantity}</td>
                <td style={{ padding: "6px 10px" }}>₹{p.entry_price.toFixed(2)}</td>
                <td style={{ padding: "6px 10px" }}>{p.exit_price ? `₹${p.exit_price.toFixed(2)}` : "—"}</td>
                <td style={{ padding: "6px 10px" }}>{fmtSec(p.hold_seconds)}</td>
                <td style={{ padding: "6px 10px", color: (p.gross_pnl ?? 0) >= 0 ? TV.green : TV.red }}>
                  {p.gross_pnl != null ? `₹${p.gross_pnl.toFixed(0)}` : "—"}
                </td>
                <td style={{ padding: "6px 10px", color: TV.red }}>
                  {p.charges ? `₹${Object.values(p.charges).reduce((a, v) => a + parseFloat(v), 0).toFixed(0)}` : "—"}
                </td>
                <td style={{ padding: "6px 10px", fontWeight: 600, color: net >= 0 ? TV.green : TV.red }}>
                  {isOpen ? "OPEN" : `₹${net.toFixed(0)}`}
                </td>
                <td style={{ padding: "6px 10px" }}>{p.force_squared && <span title="Force squared" style={{ color: TV.red }}>⚠</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
