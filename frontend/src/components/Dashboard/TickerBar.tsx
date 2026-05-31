/**
 * TickerBar — live LTP with green/red flash on tick direction.
 * Shows: Symbol · TF · LTP · Change% · O · H · L · C · Vol
 */
import { useEffect, useRef, useState } from "react";
import { useLiveQuotesStore } from "../../store/liveQuotes";

const TV = {
  bg: "#1a1e2e", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86",
  up: "#26a69a", down: "#ef5350",
} as const;

function fmtVol(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000)     return `${(v / 1_000).toFixed(1)}K`;
  return String(Math.round(v));
}

interface Props {
  symbol: string;
  timeframe: string;
  onOpenIndicators?: () => void;
  lastBar?: { open: number; high: number; low: number; close: number; volume: number } | null;
}

export default function TickerBar({ symbol, timeframe, onOpenIndicators, lastBar }: Props) {
  const quote   = useLiveQuotesStore((s) => s.quotes[symbol]);
  const [flash, setFlash] = useState<"up" | "down" | null>(null);
  const prevLtpRef = useRef<number | null>(null);

  // ltp: live trade price from quote stream
  // OHLCV: from lastBar (the live-updated current candle) — NOT from quote
  //   because each quote only carries trade-level O/H/L/C (single trade),
  //   while lastBar tracks the candle aggregate across all ticks.
  const ltp    = quote?.ltp    ?? lastBar?.close ?? null;
  const open   = lastBar?.open  ?? null;
  const high   = lastBar?.high  ?? null;
  const low    = lastBar?.low   ?? null;
  const close  = ltp ?? lastBar?.close ?? null;
  const volume = lastBar?.volume ?? 0;

  useEffect(() => {
    if (ltp == null) return;
    const prev = prevLtpRef.current;
    if (prev !== null && ltp !== prev) {
      setFlash(ltp > prev ? "up" : "down");
      const t = setTimeout(() => setFlash(null), 600);
      prevLtpRef.current = ltp;
      return () => clearTimeout(t);
    }
    prevLtpRef.current = ltp;
  }, [ltp]);

  const change = ltp != null && open != null && open !== 0
    ? ((ltp - open) / open) * 100 : null;
  const isUp       = change != null && change >= 0;
  const priceColor = ltp == null ? TV.muted : isUp ? TV.up : TV.down;
  const flashBg    = flash === "up" ? "#26a69a33" : flash === "down" ? "#ef535033" : "transparent";

  return (
    <div style={{
      background: flashBg, transition: "background 0.3s",
      borderBottom: `1px solid ${TV.border}`,
      padding: "3px 8px", display: "flex", gap: 8, alignItems: "center",
      fontSize: 11, flexWrap: "nowrap", overflow: "hidden",
    }}>
      <span style={{ fontWeight: 700, color: TV.text, fontFamily: "monospace", flexShrink: 0 }}>
        {symbol.split(":")[1] ?? symbol}
      </span>
      <span style={{ color: TV.muted, fontSize: 10 }}>{timeframe}</span>
      <span style={{ fontFamily: "monospace", fontWeight: 700, color: priceColor, flexShrink: 0 }}>
        {ltp != null ? ltp.toFixed(2) : "—"}
      </span>
      {change != null && (
        <span style={{
          fontSize: 10, padding: "1px 4px", borderRadius: 3,
          background: isUp ? "#26a69a22" : "#ef535022",
          color: isUp ? TV.up : TV.down, flexShrink: 0,
        }}>
          {isUp ? "+" : ""}{change.toFixed(2)}%
        </span>
      )}
      {ltp != null && (
        <span style={{ color: TV.muted, fontSize: 10, display: "flex", gap: 5 }}>
          <span>O <b style={{ color: TV.text }}>{(open ?? 0).toFixed(2)}</b></span>
          <span>H <b style={{ color: TV.up   }}>{(high ?? 0).toFixed(2)}</b></span>
          <span>L <b style={{ color: TV.down }}>{(low ?? 0).toFixed(2)}</b></span>
          <span>C <b style={{ color: TV.text }}>{(close ?? 0).toFixed(2)}</b></span>
          <span>V <b style={{ color: TV.muted }}>{fmtVol(volume)}</b></span>
        </span>
      )}
      <div style={{ flex: 1 }} />
      {onOpenIndicators && (
        <button
          onClick={onOpenIndicators}
          style={{
            background: "transparent", border: `1px solid ${TV.border}`,
            borderRadius: 3, color: TV.muted, fontSize: 10,
            padding: "1px 6px", cursor: "pointer", flexShrink: 0,
          }}
        >
          ⊕ Indicators
        </button>
      )}
    </div>
  );
}
