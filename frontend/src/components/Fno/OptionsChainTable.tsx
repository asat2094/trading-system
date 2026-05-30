/**
 * OptionsChainTable — options chain grid.
 *
 * Columns (left=CE, right=PE):
 *   CE LTP | CE ΔOI | CE OI | CE OH | STRIKE | PE OH | PE OI | PE ΔOI | PE LTP
 *
 * Colour rules:
 *   - ATM row: slightly brighter background
 *   - CE columns: dim red on hover (writer perspective)
 *   - PE columns: dim green on hover (writer perspective)
 *   - OH cell: amber text "OH" badge
 *   - OH Hit cell: green pulsing "HIT" badge
 */
import type { FnoSnapshot, OptionSide } from "./types";

const TV = {
  bg: "#0d0d1a", panel: "#131722", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86",
  up: "#26a69a", down: "#ef5350", warn: "#f59e0b",
  accent: "#2962ff",
  atm: "#1a1e2e",
} as const;

function fmt2(n: number | undefined): string {
  if (n === undefined || n === null) return "—";
  return n.toFixed(2);
}

function fmtOi(n: number | undefined): string {
  if (n === undefined || n === null) return "—";
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(Math.round(n));
}

function fmtDelta(n: number | undefined): string {
  if (n === undefined || n === null) return "—";
  const prefix = n > 0 ? "+" : "";
  return prefix + fmtOi(n);
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
}

export default function OptionsChainTable({ snapshot }: Props) {
  return (
    <div style={{ overflowX: "auto", overflowY: "auto", maxHeight: "70vh" }}>
      <style>{`
        @keyframes pulse {
          0%,100% { opacity: 1; }
          50%      { opacity: 0.4; }
        }
      `}</style>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
        <thead>
          <tr>
            {/* CE headers */}
            <th style={{ ...headerCell, textAlign: "right" }}>CE LTP</th>
            <th style={{ ...headerCell, textAlign: "right" }}>CE ΔOI</th>
            <th style={{ ...headerCell, textAlign: "right" }}>CE OI</th>
            <th style={{ ...headerCell, textAlign: "center" }}>OH</th>
            {/* Strike */}
            <th style={{ ...headerCell, textAlign: "center", color: TV.accent }}>STRIKE</th>
            {/* PE headers */}
            <th style={{ ...headerCell, textAlign: "center" }}>OH</th>
            <th style={{ ...headerCell, textAlign: "left" }}>PE OI</th>
            <th style={{ ...headerCell, textAlign: "left" }}>PE ΔOI</th>
            <th style={{ ...headerCell, textAlign: "left" }}>PE LTP</th>
          </tr>
        </thead>
        <tbody>
          {snapshot.strikes.map(row => {
            const isAtm = row.strike === snapshot.atm_strike;
            const rowBg = isAtm ? TV.atm : "transparent";
            const ceLtp  = row.ce?.ltp;
            const peOi   = row.pe?.oi;
            const ceOi   = row.ce?.oi;

            return (
              <tr
                key={row.strike}
                style={{ background: rowBg }}
              >
                {/* CE side (right-aligned, strike decreases left-to-right) */}
                <td style={{ ...cell, color: ceLtp ? TV.down : TV.muted }}>
                  {fmt2(ceLtp)}
                </td>
                <td style={{ ...cell, color: (row.ce?.delta_oi ?? 0) > 0 ? TV.down : TV.up }}>
                  {fmtDelta(row.ce?.delta_oi)}
                </td>
                <td style={{ ...cell, color: TV.text }}>
                  {fmtOi(ceOi)}
                </td>
                <td style={centreCell}>
                  <OhBadge side={row.ce} />
                </td>

                {/* Strike */}
                <td style={{
                  ...centreCell,
                  fontWeight: isAtm ? 700 : 400,
                  color: isAtm ? TV.accent : TV.text,
                  fontSize: isAtm ? 13 : 12,
                }}>
                  {row.strike}
                </td>

                {/* PE side (left-aligned) */}
                <td style={centreCell}>
                  <OhBadge side={row.pe} />
                </td>
                <td style={{ ...cell, textAlign: "left", color: TV.text }}>
                  {fmtOi(peOi)}
                </td>
                <td style={{ ...cell, textAlign: "left", color: (row.pe?.delta_oi ?? 0) > 0 ? TV.up : TV.down }}>
                  {fmtDelta(row.pe?.delta_oi)}
                </td>
                <td style={{ ...cell, textAlign: "left", color: row.pe?.ltp ? TV.up : TV.muted }}>
                  {fmt2(row.pe?.ltp)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
