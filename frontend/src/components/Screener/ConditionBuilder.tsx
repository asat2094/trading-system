import { useState } from "react";
import { useFiltersStore } from "../../store/filters";

const SOURCES = [
  { value: "nse_universe", label: "NSE Universe" },
  { value: "premarket_gainers", label: "Pre-Market Gainers" },
  { value: "custom_list", label: "Custom List" },
];
const INDICATORS = [
  { value: "rsi", label: "RSI" },
  { value: "macd", label: "MACD" },
  { value: "ema", label: "EMA" },
  { value: "vwap", label: "VWAP" },
  { value: "bollinger_bands", label: "Bollinger Bands" },
  { value: "atr", label: "ATR" },
];
const OPERATORS = [
  { value: "eq", label: "=" },
  { value: "gt", label: ">" },
  { value: "lt", label: "<" },
  { value: "gte", label: "≥" },
  { value: "lte", label: "≤" },
];

const sectionLabel: React.CSSProperties = {
  fontSize: 11, color: "#787b86", textTransform: "uppercase", letterSpacing: "0.8px",
  marginBottom: 10, marginTop: 4, fontWeight: 600,
};
const darkInput: React.CSSProperties = {
  background: "#1e222d", border: "1px solid #2a2e39", borderRadius: 4,
  color: "#d1d4dc", padding: "6px 10px", fontSize: 13, outline: "none",
};

export default function ConditionBuilder() {
  const { source, filters, indicators, setSource, addFilter, removeFilter, setIndicators } = useFiltersStore();

  return (
    <div style={{ padding: "16px" }}>
      <p style={sectionLabel}>Source</p>
      <select value={source} onChange={(e) => setSource(e.target.value)} style={{ ...darkInput, width: "100%" }}>
        {SOURCES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
      </select>

      <p style={{ ...sectionLabel, marginTop: 20 }}>Filters</p>
      {filters.map((f, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6, background: "#1e222d", borderRadius: 4, padding: "6px 10px" }}>
          <span style={{ flex: 1, fontSize: 12, color: "#d1d4dc", fontFamily: "monospace" }}>{f.field} {OPERATORS.find(o => o.value === f.operator)?.label ?? f.operator} {String(f.value)}</span>
          <button onClick={() => removeFilter(i)} style={{ background: "none", border: "none", color: "#787b86", cursor: "pointer", fontSize: 14, padding: 0, lineHeight: 1 }}>×</button>
        </div>
      ))}
      <AddFilterRow onAdd={addFilter} operators={OPERATORS} inputStyle={darkInput} />

      <p style={{ ...sectionLabel, marginTop: 20 }}>Indicators</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {INDICATORS.map((ind) => {
          const active = indicators.includes(ind.value);
          return (
            <button
              key={ind.value}
              onClick={() => active ? setIndicators(indicators.filter(i => i !== ind.value)) : setIndicators([...indicators, ind.value])}
              style={{
                padding: "4px 10px", borderRadius: 12, fontSize: 12, cursor: "pointer", border: "1px solid",
                background: active ? "rgba(41,98,255,0.2)" : "transparent",
                borderColor: active ? "#2962ff" : "#2a2e39",
                color: active ? "#7ba7ff" : "#787b86",
              }}
            >
              {ind.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function AddFilterRow({ onAdd, operators, inputStyle }: {
  onAdd: (f: { field: string; operator: string; value: string }) => void;
  operators: { value: string; label: string }[];
  inputStyle: React.CSSProperties;
}) {
  const [field, setField] = useState("exchange");
  const [operator, setOperator] = useState("eq");
  const [value, setValue] = useState("NSE");

  return (
    <div style={{ display: "flex", gap: 6, marginTop: 8, alignItems: "center" }}>
      <input value={field} onChange={(e) => setField(e.target.value)} placeholder="field" style={{ ...inputStyle, flex: 2 }} />
      <select value={operator} onChange={(e) => setOperator(e.target.value)} style={{ ...inputStyle, flex: 1 }}>
        {operators.map((op) => <option key={op.value} value={op.value}>{op.label}</option>)}
      </select>
      <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="value" style={{ ...inputStyle, flex: 2 }} />
      <button
        onClick={() => onAdd({ field, operator, value })}
        style={{ padding: "6px 12px", background: "#2962ff", border: "none", borderRadius: 4, color: "#fff", fontSize: 12, cursor: "pointer", whiteSpace: "nowrap" }}
      >
        + Add
      </button>
    </div>
  );
}
