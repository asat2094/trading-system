/**
 * PaneControls — symbol search + timeframe dropdown per pane.
 *
 * Fix 1: removed static symbol label (TickerBar below already shows it).
 * Fix 2: dropdown uses position:fixed + getBoundingClientRect to escape
 *         overflow:hidden on PaneGrid ancestor.
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

interface DropdownPos { top: number; left: number; width: number; }

interface Props {
  paneId: string;
  symbol: string;
  timeframe: string;
}

export default function PaneControls({ paneId, symbol, timeframe }: Props) {
  const { setPaneSymbol, setPaneTimeframe } = useDashboardStore();
  const [query, setQuery]       = useState("");
  const [results, setResults]   = useState<string[]>([]);
  const [open, setOpen]         = useState(false);
  const [dropPos, setDropPos]   = useState<DropdownPos | null>(null);
  const debRef   = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapRef  = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  // Search — debounced
  useEffect(() => {
    if (debRef.current) clearTimeout(debRef.current);
    const q = query.trim().toUpperCase();
    if (q.length < 1) { setResults([]); setOpen(false); return; }
    const ctrl = new AbortController();
    debRef.current = setTimeout(async () => {
      try {
        const crypto = CRYPTO_SYMBOLS.filter((s) => s.toUpperCase().includes(q));
        const { data } = await apiClient.get("/technical/symbols", {
          params: { q, limit: 15 }, signal: ctrl.signal,
        });
        // Symbols already containing ":" are fully canonical (e.g. BSE:SENSEX)
        const nse: string[] = (data.symbols ?? []).map((s: string) =>
          s.includes(":") ? s : `NSE:${s}`
        );
        const all = [...crypto, ...nse].slice(0, 20);
        setResults(all);
        if (all.length > 0 && inputRef.current) {
          const rect = inputRef.current.getBoundingClientRect();
          setDropPos({ top: rect.bottom + 4, left: rect.left, width: Math.max(rect.width, 200) });
          setOpen(true);
        }
      } catch { /* aborted or error */ }
    }, 200);
    return () => { ctrl.abort(); if (debRef.current) clearTimeout(debRef.current); };
  }, [query]);

  const pick = (sym: string) => {
    setPaneSymbol(paneId, sym);
    setQuery(""); setOpen(false);
  };

  const inp: React.CSSProperties = {
    background: "#1e222d", border: `1px solid ${TV.border}`, borderRadius: 3,
    color: TV.text, padding: "3px 8px", fontSize: 11, outline: "none", width: 130,
  };
  const sel: React.CSSProperties = {
    background: TV.bg, border: `1px solid ${TV.border}`, borderRadius: 3,
    color: TV.text, padding: "2px 5px", fontSize: 11, cursor: "pointer",
  };

  return (
    <div style={{ display: "flex", gap: 6, alignItems: "center" }} ref={wrapRef}>
      {/* Symbol search — NO static label; TickerBar shows current symbol */}
      <input
        ref={inputRef}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && results[0]) pick(results[0]);
          if (e.key === "Escape") { setOpen(false); setQuery(""); }
        }}
        placeholder={symbol.split(":")[1] ?? symbol}
        style={inp}
        autoComplete="off"
        spellCheck={false}
      />

      {/* Dropdown — fixed position to escape overflow:hidden ancestors */}
      {open && results.length > 0 && dropPos && (
        <div style={{
          position: "fixed",
          top: dropPos.top,
          left: dropPos.left,
          width: dropPos.width,
          zIndex: 99999,
          background: "#1e222d",
          border: `1px solid ${TV.border}`,
          borderRadius: 4,
          maxHeight: 260,
          overflowY: "auto",
          boxShadow: "0 8px 32px rgba(0,0,0,0.7)",
        }}>
          {results.map((s) => (
            <div
              key={s}
              onMouseDown={() => pick(s)}
              style={{
                padding: "6px 10px", cursor: "pointer", fontSize: 11,
                fontFamily: "monospace", color: TV.text,
                borderBottom: `1px solid ${TV.border}33`,
                display: "flex", gap: 8, alignItems: "center",
              }}
            >
              <span style={{
                fontSize: 9, color: s.startsWith("CRYPTO") ? "#f59e0b" : "#2962ff",
                background: s.startsWith("CRYPTO") ? "#f59e0b22" : "#2962ff22",
                padding: "1px 4px", borderRadius: 2,
              }}>
                {s.split(":")[0]}
              </span>
              <span>{s.split(":")[1]}</span>
            </div>
          ))}
        </div>
      )}

      {/* Timeframe */}
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
