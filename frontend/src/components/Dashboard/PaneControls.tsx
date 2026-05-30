/**
 * PaneControls — symbol search dropdown + timeframe dropdown per pane.
 */
import { useState, useRef, useEffect } from "react";
import { apiClient } from "../../api/client";
import { useDashboardStore } from "../../store/dashboard";

const TV = { bg: "#131722", border: "#2a2e39", text: "#d1d4dc", muted: "#787b86" } as const;

const TF_OPTIONS = [
  { label: "1m",  value: "1min"  },
  { label: "5m",  value: "5min"  },
  { label: "15m", value: "15min" },
  { label: "30m", value: "30min" },
  { label: "1h",  value: "1h"    },
  { label: "4h",  value: "4h"    },
  { label: "1d",  value: "1d"    },
  { label: "1w",  value: "1w"    },
];

const CRYPTO_SYMBOLS = [
  "CRYPTO:BTC","CRYPTO:ETH","CRYPTO:SOL","CRYPTO:BNB",
  "CRYPTO:DOGE","CRYPTO:XRP","CRYPTO:AVAX","CRYPTO:MATIC",
  "CRYPTO:ARB","CRYPTO:OP","CRYPTO:SUI","CRYPTO:APT",
];

interface Props {
  paneId: string;
  symbol: string;
  timeframe: string;
}

export default function PaneControls({ paneId, symbol, timeframe }: Props) {
  const { setPaneSymbol, setPaneTimeframe } = useDashboardStore();
  const [query, setQuery]     = useState("");
  const [results, setResults] = useState<string[]>([]);
  const [open, setOpen]       = useState(false);
  const debRef  = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  useEffect(() => {
    if (debRef.current) clearTimeout(debRef.current);
    const q = query.trim().toUpperCase();
    if (q.length < 2) { setResults([]); setOpen(false); return; }
    const ctrl = new AbortController();
    debRef.current = setTimeout(async () => {
      try {
        const { data } = await apiClient.get("/technical/symbols", {
          params: { q, limit: 15 }, signal: ctrl.signal,
        });
        const nse: string[] = (data.symbols ?? []).map((s: string) => `NSE:${s}`);
        const crypto = CRYPTO_SYMBOLS.filter((s) => s.toUpperCase().includes(q));
        setResults([...crypto, ...nse].slice(0, 20));
        setOpen(true);
      } catch { /* aborted */ }
    }, 200);
    return () => { ctrl.abort(); if (debRef.current) clearTimeout(debRef.current); };
  }, [query]);

  const pick = (sym: string) => {
    setPaneSymbol(paneId, sym);
    setQuery(""); setOpen(false);
  };

  const inp: React.CSSProperties = {
    background: TV.bg, border: `1px solid ${TV.border}`, borderRadius: 3,
    color: TV.text, padding: "2px 7px", fontSize: 11, outline: "none", width: 120,
  };
  const sel: React.CSSProperties = {
    background: TV.bg, border: `1px solid ${TV.border}`, borderRadius: 3,
    color: TV.text, padding: "2px 5px", fontSize: 11, cursor: "pointer",
  };

  return (
    <div style={{ display: "flex", gap: 5, alignItems: "center" }} ref={wrapRef}>
      <span style={{ fontSize: 11, fontWeight: 700, color: TV.text, fontFamily: "monospace" }}>
        {symbol.split(":")[1] ?? symbol}
      </span>
      <div style={{ position: "relative" }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && results[0]) pick(results[0]);
            if (e.key === "Escape") { setOpen(false); setQuery(""); }
          }}
          placeholder="Change…"
          style={inp}
          autoComplete="off"
          spellCheck={false}
        />
        {open && results.length > 0 && (
          <div style={{
            position: "absolute", top: "calc(100% + 2px)", left: 0, zIndex: 9999,
            background: "#1e222d", border: `1px solid ${TV.border}`, borderRadius: 4,
            minWidth: 180, maxHeight: 240, overflowY: "auto",
            boxShadow: "0 8px 24px rgba(0,0,0,0.6)",
          }}>
            {results.map((s) => (
              <div
                key={s}
                onMouseDown={() => pick(s)}
                style={{
                  padding: "5px 10px", cursor: "pointer", fontSize: 11,
                  fontFamily: "monospace", color: TV.text,
                  borderBottom: `1px solid ${TV.border}22`,
                }}
              >
                <span style={{ color: TV.muted, fontSize: 9 }}>{s.split(":")[0]}</span>
                {" "}{s.split(":")[1]}
              </div>
            ))}
          </div>
        )}
      </div>
      <select
        value={timeframe}
        onChange={(e) => setPaneTimeframe(paneId, e.target.value)}
        style={sel}
      >
        {TF_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}
