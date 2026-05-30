/**
 * PcrCards — summary strip showing PCR, PCDR, PCD, Spot.
 * PCR > 1 = bullish (more PE OI = more hedging/puts) → green.
 * PCD > 0 = more PE OI added today → green.
 */
import type { FnoSnapshot } from "./types";

const TV = {
  panel: "#131722", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86",
  up: "#26a69a", down: "#ef5350",
} as const;

interface Props {
  snapshot: FnoSnapshot;
}

function fmt(n: number, decimals = 3): string {
  return n.toFixed(decimals);
}

function fmtOi(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
  return String(Math.round(n));
}

export default function PcrCards({ snapshot }: Props) {
  const cards = [
    {
      label: "PCR",
      value: fmt(snapshot.pcr),
      color: snapshot.pcr >= 1 ? TV.up : TV.down,
      sub: `${fmtOi(snapshot.total_pe_oi)} PE / ${fmtOi(snapshot.total_ce_oi)} CE`,
      title: "Put-Call Ratio: total PE OI ÷ total CE OI. >1 = bullish",
    },
    {
      label: "PCR Δ",
      value: fmt(snapshot.pcdr),
      color: snapshot.pcdr >= 1 ? TV.up : TV.down,
      sub: "ΔPE OI ÷ ΔCE OI",
      title: "Put-Call Delta Ratio: change in PE OI ÷ change in CE OI today",
    },
    {
      label: "PCD",
      value: fmtOi(snapshot.pcd),
      color: snapshot.pcd >= 0 ? TV.up : TV.down,
      sub: "ΔPE OI − ΔCE OI",
      title: "Put-Call Delta: net change in PE OI minus CE OI (today)",
    },
    {
      label: "SPOT",
      value: snapshot.spot.toFixed(2),
      color: TV.text,
      sub: `ATM ${snapshot.atm_strike}  ·  exp ${snapshot.expiry}`,
      title: "NIFTY 50 last traded price",
    },
  ];

  return (
    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
      {cards.map(c => (
        <div
          key={c.label}
          title={c.title}
          style={{
            background: TV.panel,
            border: `1px solid ${TV.border}`,
            borderRadius: 6,
            padding: "10px 18px",
            minWidth: 130,
            cursor: "default",
          }}
        >
          <div style={{ color: TV.muted, fontSize: 10, textTransform: "uppercase", letterSpacing: 1 }}>
            {c.label}
          </div>
          <div style={{ color: c.color, fontSize: 22, fontWeight: 700, fontFamily: "monospace", marginTop: 2 }}>
            {c.value}
          </div>
          <div style={{ color: TV.muted, fontSize: 10, marginTop: 3 }}>
            {c.sub}
          </div>
        </div>
      ))}
    </div>
  );
}
