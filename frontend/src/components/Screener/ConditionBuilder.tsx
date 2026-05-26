// frontend/src/components/Screener/ConditionBuilder.tsx
import React from "react";
import { useFiltersStore, ConditionLeaf, ConditionGroup } from "../../store/filters";
import { useListSignals, SignalConfig } from "../../api/scanner";

// ── constants ─────────────────────────────────────────────────────────────────

const INDICATORS = [
  { value: "rsi", label: "RSI" },
  { value: "macd", label: "MACD" },
  { value: "ema", label: "EMA" },
  { value: "sma", label: "SMA" },
  { value: "vwap", label: "VWAP" },
  { value: "bollinger_bands", label: "Bollinger Bands" },
  { value: "atr", label: "ATR" },
  { value: "stochastic", label: "Stochastic" },
  { value: "cci", label: "CCI" },
  { value: "williams_r", label: "Williams %R" },
  { value: "obv", label: "OBV" },
  { value: "supertrend", label: "Supertrend" },
  { value: "price_vs_resistance", label: "Price vs Resistance" },
];
const OPERATORS = [
  { value: "lt", label: "<" },
  { value: "lte", label: "≤" },
  { value: "gt", label: ">" },
  { value: "gte", label: "≥" },
  { value: "eq", label: "=" },
];
const TIMEFRAMES = ["1min", "5min", "15min", "1h", "1d", "1w"];
const CANDLESTICK_PATTERNS = [
  "bearish_engulfing", "bullish_engulfing", "hammer",
  "shooting_star", "doji", "morning_star", "evening_star",
];
const CHART_PATTERNS = ["double_bottom", "double_top", "head_shoulders", "triangle"];
const TREND_DIRS = ["up", "down", "sideways"];

// ── shared styles ─────────────────────────────────────────────────────────────

const s = {
  sectionLabel: {
    fontSize: 11, color: "#787b86", textTransform: "uppercase" as const,
    letterSpacing: "0.8px", marginBottom: 8, marginTop: 16, fontWeight: 600,
  },
  input: {
    background: "#1e222d", border: "1px solid #2a2e39", borderRadius: 4,
    color: "#d1d4dc", padding: "5px 8px", fontSize: 12, outline: "none",
  },
  select: {
    background: "#1e222d", border: "1px solid #2a2e39", borderRadius: 4,
    color: "#d1d4dc", padding: "5px 8px", fontSize: 12, outline: "none",
  },
  chipActive: {
    padding: "3px 10px", borderRadius: 12, fontSize: 12, cursor: "pointer",
    border: "1px solid #2962ff", background: "rgba(41,98,255,0.18)", color: "#7ba7ff",
  },
  chipInactive: {
    padding: "3px 10px", borderRadius: 12, fontSize: 12, cursor: "pointer",
    border: "1px solid #2a2e39", background: "transparent", color: "#787b86",
  },
  removeBtn: {
    background: "none", border: "none", color: "#787b86", cursor: "pointer",
    fontSize: 16, lineHeight: 1, padding: "0 4px", flexShrink: 0,
  } as React.CSSProperties,
  addBtn: {
    background: "none", border: "1px dashed #2a2e39", borderRadius: 4,
    color: "#787b86", cursor: "pointer", fontSize: 11, padding: "4px 8px",
    marginTop: 4,
  },
};

// ── SignalPresets ─────────────────────────────────────────────────────────────

function SignalPresets() {
  const { signals, toggleSignal, defaultTimeframe } = useFiltersStore();
  const { data: available = [] } = useListSignals();

  return (
    <div>
      <p style={s.sectionLabel}>Signal Presets</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {available.map((sig: SignalConfig) => {
          const active = signals.includes(sig.name);
          const tfMismatch = sig.timeframes.length > 0 && !sig.timeframes.includes(defaultTimeframe);
          return (
            <button
              key={sig.name}
              onClick={() => toggleSignal(sig.name)}
              title={tfMismatch ? `Designed for ${sig.timeframes.join(", ")}` : sig.name}
              style={active
                ? { ...s.chipActive, borderColor: sig.display.color, color: sig.display.color, background: `${sig.display.color}22` }
                : s.chipInactive
              }
            >
              {sig.display.icon} {sig.name.replace(/_/g, " ")}
              {tfMismatch && <span style={{ marginLeft: 4, opacity: 0.7 }}>&#9888;</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── LeafRow ───────────────────────────────────────────────────────────────────

function newLeaf(): ConditionLeaf {
  return {
    id: Math.random().toString(36).slice(2),
    type: "indicator", indicator: "rsi", operator: "lt", value: 30,
    params: { period: 14 },
  };
}

function LeafRow({ leaf, groupId }: { leaf: ConditionLeaf; groupId: string }) {
  const { updateCondition, removeCondition } = useFiltersStore();
  const upd = (patch: Partial<ConditionLeaf>) => updateCondition(groupId, { ...leaf, ...patch });

  return (
    <div style={{
      display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center",
      background: "#1e222d", borderRadius: 4, padding: "6px 8px", marginBottom: 4,
    }}>
      {/* Type selector */}
      <select value={leaf.type} onChange={(e) => upd({ type: e.target.value as ConditionLeaf["type"] })} style={s.select}>
        <option value="indicator">Indicator</option>
        <option value="crossover">Crossover</option>
        <option value="candlestick">Candlestick</option>
        <option value="chart_pattern">Chart Pattern</option>
        <option value="volume">Volume</option>
        <option value="trend">Trend</option>
      </select>

      {/* Indicator inputs */}
      {leaf.type === "indicator" && (
        <>
          <select value={leaf.indicator ?? "rsi"} onChange={(e) => upd({ indicator: e.target.value })} style={s.select}>
            {INDICATORS.map((i) => <option key={i.value} value={i.value}>{i.label}</option>)}
          </select>
          <select value={leaf.operator ?? "lt"} onChange={(e) => upd({ operator: e.target.value })} style={{ ...s.select, width: 44 }}>
            {OPERATORS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <input
            type="number"
            value={typeof leaf.value === "number" ? leaf.value : 30}
            onChange={(e) => upd({ value: parseFloat(e.target.value) })}
            style={{ ...s.input, width: 60 }}
          />
          <input
            placeholder="period=14"
            defaultValue={leaf.params ? Object.entries(leaf.params).map(([k, v]) => `${k}=${v}`).join(",") : ""}
            onBlur={(e) => {
              const params: Record<string, number> = {};
              e.target.value.split(",").forEach((p) => {
                const [k, v] = p.trim().split("=");
                if (k && v) params[k.trim()] = parseFloat(v);
              });
              upd({ params });
            }}
            style={{ ...s.input, width: 80 }}
            title="params e.g. period=14"
          />
        </>
      )}

      {/* Crossover inputs */}
      {leaf.type === "crossover" && (
        <>
          <select value={leaf.indicator_a ?? "ema"} onChange={(e) => upd({ indicator_a: e.target.value })} style={s.select}>
            {INDICATORS.map((i) => <option key={i.value} value={i.value}>{i.label}</option>)}
          </select>
          <input
            placeholder="period=20"
            defaultValue={leaf.params_a ? Object.entries(leaf.params_a).map(([k, v]) => `${k}=${v}`).join(",") : ""}
            onBlur={(e) => {
              const params: Record<string, number> = {};
              e.target.value.split(",").forEach((p) => { const [k, v] = p.trim().split("="); if (k && v) params[k.trim()] = parseFloat(v); });
              upd({ params_a: params });
            }}
            style={{ ...s.input, width: 72 }}
          />
          <select value={leaf.crossover ?? "above"} onChange={(e) => upd({ crossover: e.target.value as "above" | "below" })} style={{ ...s.select, width: 80 }}>
            <option value="above">crosses up</option>
            <option value="below">crosses down</option>
          </select>
          <select value={leaf.indicator_b ?? "ema"} onChange={(e) => upd({ indicator_b: e.target.value })} style={s.select}>
            {INDICATORS.map((i) => <option key={i.value} value={i.value}>{i.label}</option>)}
          </select>
          <input
            placeholder="period=50"
            defaultValue={leaf.params_b ? Object.entries(leaf.params_b).map(([k, v]) => `${k}=${v}`).join(",") : ""}
            onBlur={(e) => {
              const params: Record<string, number> = {};
              e.target.value.split(",").forEach((p) => { const [k, v] = p.trim().split("="); if (k && v) params[k.trim()] = parseFloat(v); });
              upd({ params_b: params });
            }}
            style={{ ...s.input, width: 72 }}
          />
        </>
      )}

      {/* Candlestick pattern */}
      {leaf.type === "candlestick" && (
        <select value={leaf.pattern ?? "hammer"} onChange={(e) => upd({ pattern: e.target.value })} style={s.select}>
          {CANDLESTICK_PATTERNS.map((p) => <option key={p} value={p}>{p.replace(/_/g, " ")}</option>)}
        </select>
      )}

      {/* Chart pattern */}
      {leaf.type === "chart_pattern" && (
        <>
          <select value={leaf.pattern ?? "double_bottom"} onChange={(e) => upd({ pattern: e.target.value })} style={s.select}>
            {CHART_PATTERNS.map((p) => <option key={p} value={p}>{p.replace(/_/g, " ")}</option>)}
          </select>
          <span style={{ fontSize: 11, color: "#787b86" }}>min conf:</span>
          <input
            type="number" min={0} max={1} step={0.1}
            value={leaf.min_confidence ?? 0.5}
            onChange={(e) => upd({ min_confidence: parseFloat(e.target.value) })}
            style={{ ...s.input, width: 48 }}
          />
        </>
      )}

      {/* Volume */}
      {leaf.type === "volume" && (
        <>
          <span style={{ fontSize: 11, color: "#787b86" }}>ratio &gt;=</span>
          <input
            type="number" step={0.1}
            value={leaf.volume_ratio ?? 1.5}
            onChange={(e) => upd({ volume_ratio: parseFloat(e.target.value) })}
            style={{ ...s.input, width: 56 }}
          />
          <span style={{ fontSize: 11, color: "#787b86" }}>period</span>
          <input
            type="number"
            value={leaf.volume_period ?? 20}
            onChange={(e) => upd({ volume_period: parseInt(e.target.value) })}
            style={{ ...s.input, width: 48 }}
          />
        </>
      )}

      {/* Trend */}
      {leaf.type === "trend" && (
        <select value={leaf.trend ?? "up"} onChange={(e) => upd({ trend: e.target.value })} style={s.select}>
          {TREND_DIRS.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      )}

      {/* TF override — always shown */}
      <select
        value={leaf.timeframe ?? ""}
        onChange={(e) => upd({ timeframe: e.target.value || undefined })}
        style={{ ...s.select, width: 64, color: leaf.timeframe ? "#d1d4dc" : "#787b86" }}
      >
        <option value="">default</option>
        {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
      </select>

      <button onClick={() => removeCondition(groupId, leaf.id)} style={s.removeBtn}>&times;</button>
    </div>
  );
}

// ── GroupNode ─────────────────────────────────────────────────────────────────

function GroupNode({ group }: { group: ConditionGroup }) {
  const { addCondition, addGroup, updateGroupLogic } = useFiltersStore();

  return (
    <div style={{ border: "1px solid #2a2e39", borderRadius: 4, padding: "8px 10px", marginBottom: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <select
          value={group.logic}
          onChange={(e) => updateGroupLogic(group.id, e.target.value as "AND" | "OR")}
          style={{ ...s.select, fontWeight: 600, width: 56 }}
        >
          <option value="AND">AND</option>
          <option value="OR">OR</option>
        </select>
        <span style={{ fontSize: 11, color: "#787b86" }}>match all/any of:</span>
      </div>

      {group.children.map((child) =>
        "logic" in child
          ? <GroupNode key={child.id} group={child as ConditionGroup} />
          : <LeafRow key={child.id} leaf={child as ConditionLeaf} groupId={group.id} />
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
        <button onClick={() => addCondition(group.id, newLeaf())} style={s.addBtn}>+ Condition</button>
        <button onClick={() => addGroup(group.id)} style={s.addBtn}>+ Group</button>
      </div>
    </div>
  );
}

// ── ScanConfig ────────────────────────────────────────────────────────────────

type MatchMode = "any_signal" | "all_signals" | "custom_only" | "signals_and_custom";

function ScanConfig() {
  const { defaultTimeframe, setDefaultTimeframe, matchMode, setMatchMode, maxSymbols, setMaxSymbols } = useFiltersStore();
  return (
    <div>
      <p style={s.sectionLabel}>Scan Config</p>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: "#787b86", width: 110 }}>Default TF</span>
          <select value={defaultTimeframe} onChange={(e) => setDefaultTimeframe(e.target.value)} style={{ ...s.select, flex: 1 }}>
            {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
          </select>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: "#787b86", width: 110 }}>Match mode</span>
          <select value={matchMode} onChange={(e) => setMatchMode(e.target.value as MatchMode)} style={{ ...s.select, flex: 1 }}>
            <option value="any_signal">Any signal</option>
            <option value="all_signals">All signals</option>
            <option value="custom_only">Custom only</option>
            <option value="signals_and_custom">Signal + custom</option>
          </select>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: "#787b86", width: 110 }}>Max symbols</span>
          <input
            type="number" min={1} max={1000}
            value={maxSymbols}
            onChange={(e) => setMaxSymbols(parseInt(e.target.value))}
            style={{ ...s.input, flex: 1 }}
          />
        </div>
      </div>
    </div>
  );
}

// ── ConditionBuilder (default export) ────────────────────────────────────────

export default function ConditionBuilder() {
  const { customConditions, initCustomConditions } = useFiltersStore();

  return (
    <div style={{ padding: "16px", flex: 1, overflowY: "auto" }}>
      <SignalPresets />

      <p style={s.sectionLabel}>Custom Conditions</p>
      {!customConditions ? (
        <button onClick={initCustomConditions} style={s.addBtn}>+ Add conditions</button>
      ) : (
        <GroupNode group={customConditions} />
      )}

      <ScanConfig />
    </div>
  );
}
