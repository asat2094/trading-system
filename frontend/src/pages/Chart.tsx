import { useParams, useNavigate } from "react-router-dom";
import { useState, useCallback, useRef, useEffect } from "react";
import CandlestickChart from "../components/Chart/CandlestickChart";
import StudyPanel from "../components/Chart/StudyPanel";
import { apiClient } from "../api/client";
import type { StudyConfig } from "../components/Chart/types";
import { STUDY_DEFAULTS } from "../components/Chart/types";
import BacktestPanel from "../components/Chart/BacktestPanel";
import BacktestOverlay from "../components/Chart/BacktestOverlay";
import type { ChartHandle } from "../components/Chart/CandlestickChart";

// ---------------------------------------------------------------------------
// Symbol search with autocomplete
// ---------------------------------------------------------------------------
function SymbolSearch({ onSelect }: { onSelect: (sym: string) => void }) {
  const [query, setQuery]       = useState("");
  const [results, setResults]   = useState<string[]>([]);
  const [open, setOpen]         = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const debounceRef             = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapRef                 = useRef<HTMLDivElement>(null);

  // Fetch results — AbortController cancels stale in-flight requests on every keystroke
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (query.trim().length < 3) { setResults([]); setOpen(false); setActiveIdx(-1); return; }

    const controller = new AbortController();

    debounceRef.current = setTimeout(async () => {
      try {
        const { data } = await apiClient.get("/technical/symbols", {
          params: { q: query, limit: 20 },
          signal: controller.signal,
        });
        const syms: string[] = data.symbols ?? [];
        setResults(syms);
        setOpen(syms.length > 0);
        setActiveIdx(-1);
      } catch (err: unknown) {
        // Ignore cancellation; clear on real errors
        if ((err as { name?: string })?.name !== "CanceledError") setResults([]);
      }
    }, 200);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      controller.abort();
    };
  }, [query]);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const pick = (sym: string) => {
    onSelect(sym);
    setQuery("");
    setResults([]);
    setOpen(false);
    setActiveIdx(-1);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx(i => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx(i => Math.max(i - 1, -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const sym = activeIdx >= 0 ? results[activeIdx] : results[0];
      if (sym) pick(sym);
    } else if (e.key === "Escape") {
      setOpen(false);
      setQuery("");
    }
  };

  return (
    <div ref={wrapRef} style={{ position: "relative" }}>
      <input
        value={query}
        onChange={e => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Search symbol…"
        autoComplete="off"
        spellCheck={false}
        style={{
          background: "#1e222d", border: "1px solid #2a2e39", borderRadius: 4,
          color: "#d1d4dc", padding: "4px 10px", fontSize: 13, outline: "none",
          width: 180,
        }}
      />
      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 4px)", left: 0, zIndex: 9999,
          background: "#1e222d", border: "1px solid #2a2e39", borderRadius: 4,
          minWidth: 220, maxHeight: 300, overflowY: "auto",
          boxShadow: "0 8px 24px rgba(0,0,0,0.6)",
        }}>
          {results.map((sym, i) => (
            <div
              key={sym}
              onMouseDown={() => pick(sym)}
              onMouseEnter={() => setActiveIdx(i)}
              style={{
                padding: "7px 12px",
                cursor: "pointer",
                fontSize: 13,
                fontFamily: "monospace",
                color: i === activeIdx ? "#fff" : "#d1d4dc",
                background: i === activeIdx ? "#2962ff" : "transparent",
              }}
            >
              {sym}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Types & constants
// ---------------------------------------------------------------------------
interface Bar {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

const TF_OPTIONS = [
  { label: "1m",  tf: "1min"  },
  { label: "3m",  tf: "3min"  },
  { label: "5m",  tf: "5min"  },
  { label: "15m", tf: "15min" },
  { label: "30m", tf: "30min" },
  { label: "1h",  tf: "1h"   },
  { label: "1d",  tf: "1d"   },
  { label: "1w",  tf: "1w"   },
  { label: "1M",  tf: "1M"   },
];

// 375 = NSE trading minutes per day (9:15–15:30)
const TRADING_MINS_PER_BAR: Record<string, number> = {
  "1min":  1,
  "3min":  3,
  "5min":  5,
  "15min": 15,
  "30min": 30,
  "1h":    60,
  "1d":    375,
  "1w":    375 * 5,   // 5 trading days
  "1M":    375 * 22,  // ~22 trading days
};
const TRADING_MINS_PER_DAY          = 375;
const CALENDAR_DAYS_PER_TRADING_DAY = 1.4;
const TARGET_BARS                   = 300;
const LOAD_MORE_BARS                = 200;

function barsToCalendarDays(tf: string, bars: number): number {
  const minsPerBar  = TRADING_MINS_PER_BAR[tf] ?? TRADING_MINS_PER_BAR["1d"];
  const tradingDays = (bars * minsPerBar) / TRADING_MINS_PER_DAY;
  return Math.ceil(tradingDays * CALENDAR_DAYS_PER_TRADING_DAY) + 14;
}

function toISO(d: Date, end = false) {
  const s = d.toISOString().split("T")[0];
  return end ? s + "T23:59:59" : s + "T00:00:00";
}

const DEFAULT_STUDIES: StudyConfig[] = [
  { id: "default-ema9",  ...STUDY_DEFAULTS.EMA, period: 9                     } as StudyConfig,
  { id: "default-ema21", ...STUDY_DEFAULTS.EMA, period: 21, color: "#2196f3"  } as StudyConfig,
  { id: "default-rsi14", ...STUDY_DEFAULTS.RSI, period: 14                    } as StudyConfig,
];

// ---------------------------------------------------------------------------
// Chart page
// ---------------------------------------------------------------------------
export default function Chart() {
  const { symbol } = useParams<{ symbol: string }>();
  const navigate   = useNavigate();

  const [tfIdx, setTfIdx]         = useState(0);
  const [bars, setBars]           = useState<Bar[]>([]);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState(false);
  const [studies, setStudies]     = useState<StudyConfig[]>(DEFAULT_STUDIES);
  const [panelOpen, setPanelOpen] = useState(false);
  const [mode, setMode]               = useState<"live" | "backtest">("live");
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const chartHandleRef                = useRef<ChartHandle | null>(null);

  const oldestRef      = useRef<Date | null>(null);
  const loadingMoreRef = useRef(false);
  const tfRef          = useRef(TF_OPTIONS[0].tf);

  const fetchBars = useCallback(async (tf: string, fromDt: Date, toDt: Date): Promise<Bar[]> => {
    const { data } = await apiClient.get(`/technical/ohlcv/${symbol}`, {
      params: { tf, from_dt: toISO(fromDt), to_dt: toISO(toDt, true) },
    });
    return data.rows as Bar[];
  }, [symbol]);

  const loadInitial = useCallback(async (idx: number) => {
    const opt = TF_OPTIONS[idx];
    tfRef.current = opt.tf;
    setLoading(true);
    setError(false);
    setBars([]);
    oldestRef.current = null;
    try {
      const now    = new Date();
      const days   = barsToCalendarDays(opt.tf, TARGET_BARS);
      const fromDt = new Date(now.getTime() - days * 86400_000);
      const rows   = await fetchBars(opt.tf, fromDt, now);
      setBars(rows);
      oldestRef.current = fromDt;
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [fetchBars]);

  // Reload when symbol changes (navigate from search) or on mount
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setTfIdx(0); loadInitial(0); }, [symbol]);

  const handleTfChange = (idx: number) => {
    setTfIdx(idx);
    loadInitial(idx);
  };

  const handleNeedMoreData = useCallback(async () => {
    if (loadingMoreRef.current || !oldestRef.current) return;
    loadingMoreRef.current = true;
    const tf       = tfRef.current;
    const moreDays = barsToCalendarDays(tf, LOAD_MORE_BARS);
    const toDt     = new Date(oldestRef.current.getTime() - 1000);
    const fromDt   = new Date(toDt.getTime() - moreDays * 86400_000);
    try {
      const olderBars = await fetchBars(tf, fromDt, toDt);
      if (olderBars.length > 0) {
        setBars(prev => [...olderBars, ...prev]);
        oldestRef.current = fromDt;
      }
    } finally {
      loadingMoreRef.current = false;
    }
  }, [fetchBars]);

  const addStudy    = (s: StudyConfig) => setStudies(prev => [...prev, s]);
  const updateStudy = (s: StudyConfig) => setStudies(prev => prev.map(x => x.id === s.id ? s : x));
  const removeStudy = (id: string)     => setStudies(prev => prev.filter(x => x.id !== id));

  const opt = TF_OPTIONS[tfIdx];

  return (
    <div
      style={{ height: "100vh", display: "flex", flexDirection: "column", background: "#0d0d1a" }}
      onClick={() => panelOpen && setPanelOpen(false)}
    >
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12, flexWrap: "nowrap",
        padding: "10px 16px", borderBottom: "1px solid #2a2e39", flexShrink: 0,
      }}>
        <button onClick={() => navigate(-1)} style={btnStyle("#1e222d")}>← Back</button>

        <SymbolSearch onSelect={sym => navigate(`/chart/${sym}`)} />

        <span style={{ fontSize: 17, fontWeight: 700, fontFamily: "monospace", color: "#d1d4dc", whiteSpace: "nowrap" }}>
          {symbol}
          <span style={{ marginLeft: 8, fontSize: 11, fontFamily: "sans-serif", color: "#787b86", fontWeight: 400 }}>
            NSE · {opt.label}
          </span>
        </span>

        {/* Timeframe buttons */}
        <div style={{ display: "flex", gap: 3 }}>
          {TF_OPTIONS.map((o, i) => (
            <button
              key={o.label}
              onClick={() => handleTfChange(i)}
              style={btnStyle(
                i === tfIdx ? "#2962ff" : "#1e222d",
                i === tfIdx ? "#fff"    : "#787b86",
                i === tfIdx ? "#2962ff" : "#2a2e39",
              )}
            >
              {o.label}
            </button>
          ))}
        </div>

        {/* Mode toggle */}
        <div style={{ display: "flex", gap: 0 }}>
          <button
            onClick={() => setMode("live")}
            style={btnStyle(
              mode === "live" ? "#26a69a" : "#1e222d",
              mode === "live" ? "#fff" : "#787b86",
              mode === "live" ? "#26a69a" : "#2a2e39",
            )}
          >
            ● LIVE
          </button>
          <button
            onClick={() => setMode("backtest")}
            style={btnStyle(
              mode === "backtest" ? "#f59e0b" : "#1e222d",
              mode === "backtest" ? "#0d0d1a" : "#787b86",
              mode === "backtest" ? "#f59e0b" : "#2a2e39",
            )}
          >
            📊 BACKTEST
          </button>
        </div>

        {/* Indicators button */}
        <button
          onClick={e => { e.stopPropagation(); setPanelOpen(v => !v); }}
          style={btnStyle(
            panelOpen ? "#2962ff" : "#1e222d",
            panelOpen ? "#fff"    : "#787b86",
            panelOpen ? "#2962ff" : "#2a2e39",
          )}
        >
          ⊕ Indicators{studies.length > 0 ? ` (${studies.length})` : ""}
        </button>
      </div>

      {/* Backtest panel — visible only in backtest mode */}
      {mode === "backtest" && symbol && (
        <BacktestPanel
          symbol={symbol}
          timeframe={TF_OPTIONS[tfIdx].tf}
          onRunComplete={(runId) => setActiveRunId(runId)}
        />
      )}

      {/* Chart area */}
      <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
        {loading && <div style={centeredStyle}>Loading…</div>}
        {!loading && (error || bars.length === 0) && (
          <div style={{ ...centeredStyle, flexDirection: "column", gap: 8 }}>
            <div style={{ fontSize: 40 }}>📊</div>
            <div style={{ color: "#787b86", fontSize: 14 }}>No data for {symbol} · {opt.label}</div>
            <div style={{ color: "#363c4e", fontSize: 12 }}>Run 1-min backfill to load data for this range</div>
          </div>
        )}
        {!loading && bars.length > 0 && (
          <CandlestickChart
            ref={chartHandleRef}
            bars={bars}
            studies={studies}
            onNeedMoreData={handleNeedMoreData}
          />
        )}
        {mode === "backtest" && activeRunId && symbol && (
          <BacktestOverlay
            runId={activeRunId}
            symbol={symbol}
            chartHandle={chartHandleRef.current}
          />
        )}

        {panelOpen && (
          <StudyPanel
            studies={studies}
            onAdd={addStudy}
            onUpdate={updateStudy}
            onRemove={removeStudy}
            onClose={() => setPanelOpen(false)}
          />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
const btnStyle = (bg: string, color = "#787b86", border = "#2a2e39") => ({
  background: bg,
  border: `1px solid ${border}`,
  borderRadius: 4,
  color,
  padding: "4px 10px",
  cursor: "pointer",
  fontSize: 12,
  fontWeight: 600 as const,
  whiteSpace: "nowrap" as const,
});

const centeredStyle: React.CSSProperties = {
  height: "100%", display: "flex", alignItems: "center", justifyContent: "center",
  color: "#787b86", background: "#131722",
};
