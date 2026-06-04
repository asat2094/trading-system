import { JrnTrade } from "../../api/journal";

const TV = { bg: "#131722", border: "#2a2e39", text: "#d1d4dc", muted: "#787b86", green: "#26a69a", red: "#ef5350" };

export default function TradeTable({ trades }: { trades: JrnTrade[] }) {
  if (!trades.length) return <div style={{ color: "#363c4e", fontSize: 13, padding: 16 }}>No trades</div>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11, color: TV.text }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${TV.border}`, color: TV.muted }}>
            {["Date","Time","Broker","Symbol","B/S","Qty","Price","Brok","Status","Source"].map(h => (
              <th key={h} style={{ padding: "5px 8px", textAlign: "left", fontWeight: 500 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trades.map(t => (
            <tr key={t.id} style={{ borderBottom: `1px solid #1a1e2a`, opacity: t.status === "rejected" ? 0.5 : 1 }}>
              <td style={{ padding: "5px 8px" }}>{t.trade_date}</td>
              <td style={{ padding: "5px 8px", color: TV.muted }}>{t.trade_time ?? "—"}</td>
              <td style={{ padding: "5px 8px", color: TV.muted }}>{t.broker}</td>
              <td style={{ padding: "5px 8px" }}>{t.symbol}</td>
              <td style={{ padding: "5px 8px", color: t.trade_type === "BUY" ? TV.green : TV.red }}>{t.trade_type}</td>
              <td style={{ padding: "5px 8px" }}>{t.quantity}</td>
              <td style={{ padding: "5px 8px" }}>₹{t.price}</td>
              <td style={{ padding: "5px 8px", color: TV.muted }}>₹{t.brokerage}</td>
              <td style={{ padding: "5px 8px", color: t.status === "rejected" ? TV.red : TV.muted }}>{t.status}</td>
              <td style={{ padding: "5px 8px", color: TV.muted }}>{t.fill_grain}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
