import type { FnoSnapshot, OptionSide } from "./types";

const TV = {
  bg: "#0d0d1a", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86",
  up: "#26a69a", down: "#ef5350", warn: "#f59e0b",
  accent: "#2962ff", atm: "#1a1e2e",
} as const;

function fmt2(n: number | undefined): string {
  if (n == null) return "—";
  return n.toFixed(2);
}

function fmtOi(n: number | undefined): string {
  if (n == null) return "—";
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
  return String(Math.round(n));
}

function fmtDelta(n: number | undefined): string {
  if (n == null) return "—";
  return (n > 0 ? "+" : "") + fmtOi(n);
}

function OhBadge({ side }: { side: OptionSide | null }) {
  if (!side) return null;
  if (side.is_oh_hit) {
    return (
      <span style={{
        color: TV.up, fontSize: 9, fontWeight: 700,
        border: `1px solid ${TV.up}`, borderRadius: 3,
        padding: "1px 4px", animation: "pulse 1s infinite",
      }}>HIT</span>
    );
  }
  if (side.is_oh) {
    return (
      <span style={{
        color: TV.warn, fontSize: 9, fontWeight: 700,
        border: `1px solid ${TV.warn}`, borderRadius: 3,
        padding: "1px 4px",
      }}>OH</span>
    );
  }
  return null;
}

function ChartBtn({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      title={`Chart ${label}`}
      onClick={onClick}
      style={{
        background: "transparent", border: "none",
        color: TV.muted, cursor: "pointer",
        fontSize: 11, padding: "1px 3px", lineHeight: 1,
        opacity: 0.7,
      }}
      onMouseEnter={e => (e.currentTarget.style.opacity = "1")}
      onMouseLeave={e => (e.currentTarget.style.opacity = "0.7")}
    >
      📈
    </button>
  );
}

const cell: React.CSSProperties = {
  padding: "5px 8px", textAlign: "right", fontSize: 12,
  fontFamily: "monospace", borderBottom: `1px solid ${TV.border}`,
  whiteSpace: "nowrap",
};
const centreCell: React.CSSProperties = { ...cell, textAlign: "center" };
const headerCell: React.CSSProperties = {
  ...cell, color: TV.muted, fontSize: 10, fontWeight: 600,
  textTransform: "uppercase", letterSpacing: 0.5,
  position: "sticky", top: 0, background: TV.bg, zIndex: 1,
};

interface Props {
  snapshot: FnoSnapshot;
  indexName: string;
  wsSymbol: string;
  indexLabel: string;
  onOpenChart: (symbol: string, label: string) => void;
}

export default function OptionsChainTable({ snapshot, indexName: _indexName, wsSymbol, indexLabel, onOpenChart }: Props) {
  void _indexName;
  return (
    <div style={{ overflowX: "auto", overflowY: "auto", maxHeight: "70vh" }}>
      <style>{`
        @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
      `}</style>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
        <thead>
          <tr>
            <th style={{ ...headerCell, textAlign: "center", width: 24 }} />
            <th style={{ ...headerCell, textAlign: "right" }}>CE LTP</th>
            <th style={{ ...headerCell, textAlign: "right" }}>CE ΔOI</th>
            <th style={{ ...headerCell, textAlign: "right" }}>CE OI</th>
            <th style={{ ...headerCell, textAlign: "center" }}>OH</th>
            <th style={{ ...headerCell, textAlign: "center", color: TV.accent }}>STRIKE</th>
            <th style={{ ...headerCell, textAlign: "center" }}>OH</th>
            <th style={{ ...headerCell, textAlign: "left" }}>PE OI</th>
            <th style={{ ...headerCell, textAlign: "left" }}>PE ΔOI</th>
            <th style={{ ...headerCell, textAlign: "left" }}>PE LTP</th>
            <th style={{ ...headerCell, textAlign: "center", width: 24 }} />
          </tr>
        </thead>
        <tbody>
          {snapshot.strikes.map(row => {
            const isAtm = row.strike === snapshot.atm_strike;

            return (
              <tr key={row.strike} style={{ background: isAtm ? TV.atm : "transparent" }}>
                {/* CE chart icon → opens option contract chart */}
                <td style={{ ...centreCell, padding: "5px 4px" }}>
                  <ChartBtn
                    label={`${row.strike} CE`}
                    onClick={() => onOpenChart(row.ce_symbol, `${indexLabel} · ${row.strike} CE`)}
                  />
                </td>

                {/* CE side */}
                <td style={{ ...cell, color: row.ce?.ltp ? TV.down : TV.muted }}>
                  {fmt2(row.ce?.ltp)}
                </td>
                <td style={{ ...cell, color: (row.ce?.delta_oi ?? 0) > 0 ? TV.down : TV.up }}>
                  {fmtDelta(row.ce?.delta_oi)}
                </td>
                <td style={{ ...cell, color: TV.text }}>{fmtOi(row.ce?.oi)}</td>
                <td style={centreCell}><OhBadge side={row.ce} /></td>

                {/* Strike */}
                <td style={{
                  ...centreCell,
                  fontWeight: isAtm ? 700 : 400,
                  color: isAtm ? TV.accent : TV.text,
                  fontSize: isAtm ? 13 : 12,
                }}>
                  {row.strike}
                </td>

                {/* PE side */}
                <td style={centreCell}><OhBadge side={row.pe} /></td>
                <td style={{ ...cell, textAlign: "left", color: TV.text }}>{fmtOi(row.pe?.oi)}</td>
                <td style={{ ...cell, textAlign: "left", color: (row.pe?.delta_oi ?? 0) > 0 ? TV.up : TV.down }}>
                  {fmtDelta(row.pe?.delta_oi)}
                </td>
                <td style={{ ...cell, textAlign: "left", color: row.pe?.ltp ? TV.up : TV.muted }}>
                  {fmt2(row.pe?.ltp)}
                </td>

                {/* PE chart icon → opens option contract chart */}
                <td style={{ ...centreCell, padding: "5px 4px" }}>
                  <ChartBtn
                    label={`${row.strike} PE`}
                    onClick={() => onOpenChart(row.pe_symbol, `${indexLabel} · ${row.strike} PE`)}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
