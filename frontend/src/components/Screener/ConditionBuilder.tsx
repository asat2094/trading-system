import { useState } from "react";
import { useFiltersStore } from "../../store/filters";

const SOURCES = ["nse_universe", "premarket_gainers", "custom_list"];
const INDICATORS = ["rsi", "macd", "ema", "vwap", "bollinger_bands", "atr"];
const OPERATORS = ["eq", "gt", "lt", "gte", "lte"];

export default function ConditionBuilder() {
  const { source, filters, indicators, setSource, addFilter, removeFilter, setIndicators } =
    useFiltersStore();

  return (
    <div style={{ padding: 16 }}>
      <h3>Source</h3>
      <select value={source} onChange={(e) => setSource(e.target.value)}>
        {SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>

      <h3>Filters</h3>
      {filters.map((f, i) => (
        <div key={i} style={{ display: "flex", gap: 8, marginBottom: 4 }}>
          <span>{f.field} {f.operator} {String(f.value)}</span>
          <button onClick={() => removeFilter(i)}>✕</button>
        </div>
      ))}
      <AddFilterRow onAdd={addFilter} />

      <h3>Indicators</h3>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {INDICATORS.map((ind) => (
          <label key={ind}>
            <input
              type="checkbox"
              checked={indicators.includes(ind)}
              onChange={(e) => {
                if (e.target.checked) setIndicators([...indicators, ind]);
                else setIndicators(indicators.filter((i) => i !== ind));
              }}
            />
            {ind}
          </label>
        ))}
      </div>
    </div>
  );
}

function AddFilterRow({ onAdd }: { onAdd: (f: { field: string; operator: string; value: string }) => void }) {
  const [field, setField] = useState("exchange");
  const [operator, setOperator] = useState("eq");
  const [value, setValue] = useState("NSE");

  return (
    <div style={{ display: "flex", gap: 4, marginTop: 8 }}>
      <input value={field} onChange={(e) => setField(e.target.value)} placeholder="field" style={{ width: 100 }} />
      <select value={operator} onChange={(e) => setOperator(e.target.value)}>
        {OPERATORS.map((op) => <option key={op}>{op}</option>)}
      </select>
      <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="value" style={{ width: 80 }} />
      <button onClick={() => onAdd({ field, operator, value })}>+ Add</button>
    </div>
  );
}
