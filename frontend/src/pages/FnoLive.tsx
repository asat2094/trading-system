import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { apiClient } from "../api/client";
import { useLiveQuotesStore } from "../store/liveQuotes";
import * as marketWs from "../lib/marketWs";
import PcrCards from "../components/Fno/PcrCards";
import OptionsChainTable from "../components/Fno/OptionsChainTable";
import FnoChartModal from "../components/Fno/FnoChartModal";
import BrokerConnectButtons from "../components/shared/BrokerConnectButtons";
import type { FnoSnapshot } from "../components/Fno/types";

const TV = {
  bg: "#0d0d1a", panel: "#131722", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86", accent: "#2962ff",
  warn: "#f59e0b", up: "#26a69a",
} as const;

const INDICES = [
  { label: "NIFTY 50",     value: "NIFTY",      wsSymbol: "NSE:NIFTY 50",            expiryType: "weekly_tue"  },
  { label: "BANK NIFTY",   value: "BANKNIFTY",  wsSymbol: "NSE:NIFTY BANK",          expiryType: "monthly_tue" },
  { label: "MIDCAP NIFTY", value: "MIDCPNIFTY", wsSymbol: "NSE:NIFTY MID SELECT",    expiryType: "monthly_tue" },
  { label: "SENSEX",       value: "SENSEX",     wsSymbol: "BSE:SENSEX",              expiryType: "weekly_thu"  },
] as const;

type IndexValue = typeof INDICES[number]["value"];
type ExpiryType = "weekly_thu" | "weekly_tue" | "monthly_tue";
interface ChartTarget { symbol: string; label: string }

const AUTO_REFRESH_SEC = 30;

// ── Fallback expiry computation (used while API is loading / unavailable) ──
function lastWeekdayOfMonth(year: number, month: number, targetDow: number): Date {
  const last = new Date(year, month, 0);
  const dow = last.getDay();
  last.setDate(last.getDate() - ((dow - targetDow + 7) % 7));
  return last;
}

function fmtDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function computeFallbackExpiries(expiryType: ExpiryType, count = 5): string[] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const results: string[] = [];
  if (expiryType === "weekly_thu" || expiryType === "weekly_tue") {
    const targetDow = expiryType === "weekly_thu" ? 4 : 2;
    const d = new Date(today);
    let daysAhead = (targetDow - d.getDay() + 7) % 7 || 7;
    d.setDate(d.getDate() + daysAhead);
    for (let i = 0; i < count; i++) {
      results.push(fmtDate(new Date(d)));
      d.setDate(d.getDate() + 7);
    }
  } else {
    const targetDow = 2; // Tuesday for monthly_tue
    let y = today.getFullYear(), m = today.getMonth() + 1;
    while (results.length < count) {
      const exp = lastWeekdayOfMonth(y, m, targetDow);
      if (exp >= today) results.push(fmtDate(exp));
      m++; if (m > 12) { m = 1; y++; }
    }
  }
  return results;
}

const btnStyle = (disabled: boolean): React.CSSProperties => ({
  background: disabled ? "#1e222d" : TV.accent,
  border: `1px solid ${disabled ? TV.border : TV.accent}`,
  borderRadius: 4, color: disabled ? TV.muted : "#fff",
  padding: "6px 18px", cursor: disabled ? "default" : "pointer",
  fontSize: 13, fontWeight: 600,
});

export default function FnoLive() {
  const [index, setIndex]               = useState<IndexValue>("NIFTY");
  const [expiry, setExpiry]             = useState<string>("");
  const [expiryOptions, setExpiryOptions] = useState<string[]>([]);
  const [expirySource, setExpirySource] = useState<"api" | "computed">("computed");
  const [snapshot, setSnapshot]         = useState<FnoSnapshot | null>(null);
  const [liveSpot, setLiveSpot]         = useState<number | null>(null);
  const [loading, setLoading]           = useState(false);
  const [error, setError]               = useState<string>("");
  const [countdown, setCountdown]       = useState(AUTO_REFRESH_SEC);
  const [autoOn, setAutoOn]             = useState(false);
  const [chartTarget, setChartTarget]   = useState<ChartTarget | null>(null);

  const indexRef     = useRef<IndexValue>("NIFTY");
  const expiryRef    = useRef<string>("");
  const countdownRef = useRef(AUTO_REFRESH_SEC);
  const autoOnRef    = useRef(autoOn);
  // Keep refs in sync. Also update synchronously in handlers (below) so
  // refresh() always reads the latest values even if called before re-render effects fire.
  useEffect(() => { indexRef.current = index; },   [index]);
  useEffect(() => { expiryRef.current = expiry; }, [expiry]);
  useEffect(() => { autoOnRef.current = autoOn; }, [autoOn]);

  const selectedIndex = INDICES.find(i => i.value === index)!;

  // Fallback expiries shown immediately while API fetch is in progress
  const fallbackExpiries = useMemo(
    () => computeFallbackExpiries(selectedIndex.expiryType),
    [selectedIndex.expiryType]
  );
  const expiries = expiryOptions.length > 0 ? expiryOptions : fallbackExpiries;

  const refresh = useCallback(async () => {
    const sym = indexRef.current;
    const exp = expiryRef.current || undefined;
    setLoading(true);
    setError("");
    countdownRef.current = AUTO_REFRESH_SEC;
    setCountdown(AUTO_REFRESH_SEC);
    try {
      const { data } = await apiClient.get<FnoSnapshot>("/fno/snapshot", {
        params: { symbol: sym, strikes: 15, ...(exp ? { expiry: exp } : {}) },
      });
      setSnapshot(data);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } }; message?: string })
        ?.response?.data?.detail ?? (e as Error)?.message ?? "Fetch failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const id = setInterval(() => {
      if (!autoOnRef.current) return;
      countdownRef.current -= 1;
      setCountdown(countdownRef.current);
      if (countdownRef.current <= 0) {
        countdownRef.current = AUTO_REFRESH_SEC;
        setCountdown(AUTO_REFRESH_SEC);
        void refresh();
      }
    }, 1000);
    return () => clearInterval(id);
  }, [refresh]);

  // Fetch real expiries from backend whenever index changes
  useEffect(() => {
    setExpiryOptions([]);
    setExpirySource("computed");
    apiClient.get<{ expiries: string[]; source: string }>("/fno/expiries", {
      params: { symbol: index },
    }).then(({ data }) => {
      if (data.expiries?.length) {
        setExpiryOptions(data.expiries);
        setExpirySource(data.source === "kitemcp" ? "api" : "computed");
      }
    }).catch(() => { /* silently fall back to computed */ });
  }, [index]);

  useEffect(() => {
    const { wsSymbol } = selectedIndex;
    setLiveSpot(null);
    marketWs.subscribe([wsSymbol]);
    const unsub = useLiveQuotesStore.subscribe((state) => {
      const q = state.quotes[wsSymbol];
      if (q) setLiveSpot(q.ltp);
    });
    return () => { marketWs.unsubscribe([wsSymbol]); unsub(); };
  }, [selectedIndex]);

  const handleIndexChange = (v: IndexValue) => {
    // Update refs synchronously BEFORE calling refresh, so it reads the new values
    indexRef.current = v;
    expiryRef.current = "";
    setIndex(v);
    setExpiry("");
    setSnapshot(null);
    setLiveSpot(null);
    setError("");
    countdownRef.current = AUTO_REFRESH_SEC;
    setCountdown(AUTO_REFRESH_SEC);
    void refresh(); // auto-fetch on index switch
  };

  const handleExpiryChange = (v: string) => {
    expiryRef.current = v; // sync update before potential immediate refresh
    setExpiry(v);
  };

  const displaySnapshot: FnoSnapshot | null = snapshot && liveSpot != null
    ? { ...snapshot, spot: liveSpot }
    : snapshot;

  return (
    <div style={{ height: "100%", overflowY: "auto", background: TV.bg, padding: 16 }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        marginBottom: 16, flexWrap: "wrap",
      }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: TV.text }}>FnO Live</span>
        <div style={{ flex: 1 }} />

        {/* Index selector */}
        <select
          value={index}
          onChange={(e) => handleIndexChange(e.target.value as IndexValue)}
          style={{
            background: "#1e222d", border: `1px solid ${TV.border}`,
            borderRadius: 4, color: TV.text,
            padding: "5px 10px", fontSize: 13,
            cursor: "pointer", outline: "none", fontWeight: 600,
          }}
        >
          {INDICES.map((idx) => (
            <option key={idx.value} value={idx.value} style={{ background: "#1e222d" }}>
              {idx.label}
            </option>
          ))}
        </select>

        {/* Expiry selector */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 11, color: TV.muted }}>
            Expiry {expirySource === "api"
              ? <span style={{ color: TV.up, fontSize: 9 }}>●</span>
              : <span style={{ color: TV.warn, fontSize: 9 }} title="Computed — Kite MCP unavailable">~</span>
            }:
          </span>
          <select
            value={expiry}
            onChange={(e) => handleExpiryChange(e.target.value)}
            style={{
              background: "#1e222d", border: `1px solid ${TV.border}`,
              borderRadius: 4, color: TV.text,
              padding: "4px 8px", fontSize: 12,
              cursor: "pointer", outline: "none",
            }}
          >
            <option value="" style={{ background: "#1e222d" }}>Auto (next)</option>
            {expiries.map(exp => (
              <option key={exp} value={exp} style={{ background: "#1e222d" }}>{exp}</option>
            ))}
            {/* Also show snapshot's expiry if not in computed list */}
            {snapshot && !expiries.includes(snapshot.expiry) && (
              <option value={snapshot.expiry} style={{ background: "#1e222d" }}>
                {snapshot.expiry}
              </option>
            )}
          </select>
        </div>

        {/* Index chart */}
        <button
          onClick={() => setChartTarget({ symbol: selectedIndex.wsSymbol, label: selectedIndex.label })}
          title={`Open ${selectedIndex.label} chart`}
          style={{
            background: "transparent", border: `1px solid ${TV.border}`,
            borderRadius: 4, color: TV.muted,
            fontSize: 13, padding: "4px 10px",
            cursor: "pointer", display: "flex", alignItems: "center", gap: 5,
          }}
        >
          📈 Chart
        </button>

        {liveSpot != null && (
          <span style={{
            fontFamily: "monospace", fontSize: 14, fontWeight: 700,
            color: TV.up, background: "#26a69a14",
            border: `1px solid #26a69a44`,
            borderRadius: 4, padding: "3px 10px",
          }}>
            ● {liveSpot.toFixed(2)}
          </span>
        )}

        {snapshot && (
          <span style={{ fontSize: 11, color: TV.muted }}>
            {new Date(snapshot.fetched_at).toLocaleTimeString("en-IN")}
            {snapshot.stale && (
              <span style={{ color: TV.warn, marginLeft: 6, fontWeight: 600 }}>⚠ Cached</span>
            )}
          </span>
        )}

        <button onClick={refresh} disabled={loading} style={btnStyle(loading)}>
          {loading ? "⏳ Fetching…" : "↻ Refresh"}
        </button>

        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: TV.muted }}>
          <button
            onClick={() => setAutoOn(v => !v)}
            style={{
              background: autoOn ? "#26a69a22" : "transparent",
              border: `1px solid ${autoOn ? TV.up : TV.border}`,
              borderRadius: 4, color: autoOn ? TV.up : TV.muted,
              fontSize: 10, padding: "3px 8px", cursor: "pointer",
            }}
          >
            Auto {autoOn ? "ON" : "OFF"}
          </button>
          {autoOn && !loading && <span>↻ {countdown}s</span>}
        </div>

        {error && <span style={{ color: "#ef5350", fontSize: 12 }}>{error}</span>}

        <BrokerConnectButtons />
      </div>

      {!snapshot && !loading && (
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center",
          justifyContent: "center", minHeight: 300, gap: 12, color: TV.muted,
        }}>
          <div style={{ fontSize: 40 }}>📊</div>
          <div style={{ fontSize: 14 }}>Press Refresh to load {selectedIndex.label} option chain</div>
          <div style={{ fontSize: 11 }}>Requires active Kite MCP session</div>
        </div>
      )}

      {displaySnapshot && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <PcrCards snapshot={displaySnapshot} />
          <OptionsChainTable
            snapshot={displaySnapshot}
            indexName={index}
            wsSymbol={selectedIndex.wsSymbol}
            indexLabel={selectedIndex.label}
            onOpenChart={(symbol, label) => setChartTarget({ symbol, label })}
          />
        </div>
      )}

      {chartTarget && (
        <FnoChartModal
          symbol={chartTarget.symbol}
          label={chartTarget.label}
          onClose={() => setChartTarget(null)}
        />
      )}
    </div>
  );
}
