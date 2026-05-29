/**
 * BacktestPanel — shown below chart header in BACKTEST mode.
 *
 * Tabs:
 *   "conditions" — ConditionBuilder (reads from useFiltersStore, same as Screener)
 *   "config"     — date range, SL/target params, broker
 *
 * Bottom bar:
 *   Run button → POST to backtest-engine → poll status → call onRunComplete(runId)
 *   History dropdown → load a prior run's markers
 */
import { useState, useRef } from "react";
import ConditionBuilder from "../Screener/ConditionBuilder";
import { useFiltersStore } from "../../store/filters";

const BACKTEST_URL = import.meta.env.VITE_BACKTEST_ENGINE_URL ?? "http://localhost:8085";

const TV = {
  bg: "#0d0d1a", panel: "#131722", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86", accent: "#2962ff",
  up: "#26a69a", down: "#ef5350", warn: "#f59e0b",
} as const;

const inputStyle: React.CSSProperties = {
  background: "#1e222d", border: `1px solid ${TV.border}`, borderRadius: 3,
  color: TV.text, padding: "4px 8px", fontSize: 12, outline: "none",
  width: "100%", boxSizing: "border-box",
};

const selectStyle: React.CSSProperties = { ...inputStyle };

interface HistoryRun {
  run_id: string;
  run_name: string;
  status: string;
  symbols_json: string;
}

interface Props {
  symbol: string;
  timeframe: string;
  onRunComplete: (runId: string) => void;
}

export default function BacktestPanel({ symbol, timeframe, onRunComplete }: Props) {
  const [tab, setTab] = useState<"conditions" | "config">("conditions");

  // Config state
  const [dateFrom, setDateFrom] = useState("2022-01-01");
  const [dateTo, setDateTo] = useState(new Date().toISOString().slice(0, 10));
  const [slType, setSlType] = useState("fixed_pct");
  const [slValue, setSlValue] = useState(2);
  const [tgtType, setTgtType] = useState("rr_ratio");
  const [tgtValue, setTgtValue] = useState(3);
  const [broker, setBroker] = useState("zerodha");

  // Run state
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [history, setHistory] = useState<HistoryRun[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const customConditions = useFiltersStore(s => s.customConditions);

  async function loadHistory() {
    if (historyLoaded) return;
    try {
      const res = await fetch(`${BACKTEST_URL}/runs/history`);
      if (res.ok) {
        const data = await res.json();
        setHistory(data.slice(0, 20));
        setHistoryLoaded(true);
      }
    } catch {}
  }

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }

  async function pollStatus(runId: string) {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${BACKTEST_URL}/runs/${runId}`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.status === "complete") {
          stopPolling();
          setStatus("complete");
          setRunning(false);
          onRunComplete(runId);
        } else if (data.status === "failed") {
          stopPolling();
          setStatus("failed");
          setError(data.error || "Run failed");
          setRunning(false);
        } else {
          setStatus(data.status);
        }
      } catch {}
    }, 1500);
  }

  async function handleRun() {
    if (!customConditions) {
      setError("Add at least one condition in the Conditions tab first.");
      return;
    }
    setError("");
    setRunning(true);
    setStatus("submitting…");

    const body = {
      condition_node: customConditions,
      sl_target: { sl_type: slType, sl_value: slValue, target_type: tgtType, target_value: tgtValue },
      params: {
        symbols: symbol,
        timeframe,
        date_from: dateFrom,
        date_to: dateTo,
        engine: "local",
        broker,
      },
    };

    try {
      const res = await fetch(`${BACKTEST_URL}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setStatus("running");
      pollStatus(data.run_id);
    } catch (e: unknown) {
      setError((e as Error).message || "Failed to start backtest");
      setRunning(false);
      setStatus("");
    }
  }

  const tabBtn = (t: "conditions" | "config", label: string) => (
    <button
      onClick={() => setTab(t)}
      style={{
        background: tab === t ? TV.accent : "transparent",
        border: "none", borderBottom: tab === t ? "none" : `1px solid ${TV.border}`,
        color: tab === t ? "#fff" : TV.muted,
        padding: "6px 14px", cursor: "pointer", fontSize: 12, fontWeight: 600,
      }}
    >
      {label}
    </button>
  );

  return (
    <div style={{ background: TV.panel, borderBottom: `1px solid ${TV.border}`, fontSize: 12 }}>
      {/* Tabs */}
      <div style={{ display: "flex", borderBottom: `1px solid ${TV.border}` }}>
        {tabBtn("conditions", "⚡ Conditions")}
        {tabBtn("config", "⚙ Config")}
      </div>

      {/* Tab content */}
      <div style={{ padding: 10, maxHeight: 260, overflowY: "auto" }}>
        {tab === "conditions" && (
          <div>
            <div style={{ color: TV.muted, fontSize: 11, marginBottom: 6 }}>
              Build entry conditions below (shared with Screener)
            </div>
            <ConditionBuilder />
          </div>
        )}

        {tab === "config" && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <label style={{ color: TV.muted }}>
              From
              <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} style={inputStyle} />
            </label>
            <label style={{ color: TV.muted }}>
              To
              <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} style={inputStyle} />
            </label>
            <label style={{ color: TV.muted }}>
              SL type
              <select value={slType} onChange={e => setSlType(e.target.value)} style={selectStyle}>
                <option value="fixed_pct">Fixed %</option>
                <option value="atr_multiple">ATR ×</option>
                <option value="trailing_pct">Trailing %</option>
                <option value="trailing_atr">Trailing ATR</option>
              </select>
            </label>
            <label style={{ color: TV.muted }}>
              SL value
              <input type="number" value={slValue} min={0.1} step={0.5}
                onChange={e => setSlValue(Number(e.target.value))} style={inputStyle} />
            </label>
            <label style={{ color: TV.muted }}>
              Target type
              <select value={tgtType} onChange={e => setTgtType(e.target.value)} style={selectStyle}>
                <option value="rr_ratio">R:R ratio</option>
                <option value="fixed_pct">Fixed %</option>
                <option value="atr_multiple">ATR ×</option>
              </select>
            </label>
            <label style={{ color: TV.muted }}>
              Target value
              <input type="number" value={tgtValue} min={0.1} step={0.5}
                onChange={e => setTgtValue(Number(e.target.value))} style={inputStyle} />
            </label>
            <label style={{ color: TV.muted }}>
              Broker
              <select value={broker} onChange={e => setBroker(e.target.value)} style={selectStyle}>
                <option value="zerodha">Zerodha</option>
                <option value="upstox">Upstox</option>
                <option value="angel">Angel</option>
              </select>
            </label>
          </div>
        )}
      </div>

      {/* Bottom bar: run + history */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10, padding: "8px 10px",
        borderTop: `1px solid ${TV.border}`,
      }}>
        <button
          onClick={handleRun}
          disabled={running}
          style={{
            background: running ? "#1e222d" : TV.accent,
            border: "none", borderRadius: 3, color: running ? TV.muted : "#fff",
            padding: "5px 16px", cursor: running ? "default" : "pointer",
            fontSize: 12, fontWeight: 600,
          }}
        >
          {running ? `⏳ ${status}` : "▶ Run Backtest"}
        </button>

        {error && <span style={{ color: TV.down, fontSize: 11 }}>{error}</span>}

        {status === "complete" && !running && (
          <span style={{ color: TV.up, fontSize: 11 }}>✓ Done — markers loaded</span>
        )}

        {/* Prior run selector */}
        <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
          <span style={{ color: TV.muted }}>Load run:</span>
          <select
            onClick={loadHistory}
            onChange={e => { if (e.target.value) onRunComplete(e.target.value); }}
            style={{ ...selectStyle, width: 180 }}
            defaultValue=""
          >
            <option value="">— select prior run —</option>
            {history.map(r => (
              <option key={r.run_id} value={r.run_id}>
                {r.run_name || r.run_id.slice(0, 8)} · {r.status}
              </option>
            ))}
          </select>
        </div>

        <a
          href={`http://localhost:8086`}
          target="_blank"
          rel="noreferrer"
          style={{ color: TV.muted, fontSize: 11 }}
        >
          Full UI ↗
        </a>
      </div>
    </div>
  );
}
