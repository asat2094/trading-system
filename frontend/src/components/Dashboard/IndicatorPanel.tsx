/**
 * IndicatorPanel — two-layer slide-in panel.
 * Layer 1: searchable indicator list
 * Layer 2: per-indicator settings (Inputs / Style / Visibility)
 */
import { useState } from "react";
import { useDashboardStore, IndicatorConfig, IndicatorType } from "../../store/dashboard";

const TV = {
  bg: "#1e222d", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86",
  accent: "#2962ff", up: "#26a69a", down: "#ef5350",
} as const;

const OVERLAY_TYPES: IndicatorType[]    = ["EMA", "SMA", "BB", "VWAP", "Pivot", "VolumeProfile", "FVG"];
const OSCILLATOR_TYPES: IndicatorType[] = ["RSI", "MACD", "Stoch"];

const INDICATOR_LABELS: Record<IndicatorType, string> = {
  EMA: "EMA", SMA: "SMA", BB: "Bollinger Bands", VWAP: "VWAP",
  RSI: "RSI", MACD: "MACD", Stoch: "Stochastic",
  VolumeProfile: "Volume Profile", FVG: "Fair Value Gap",
  Pivot: "Pivot Points",
};

const INDICATOR_DESCRIPTIONS: Record<IndicatorType, string> = {
  EMA: "Exponential Moving Average — configurable source", SMA: "Simple Moving Average — configurable source",
  BB: "Bollinger Bands (20, 2σ)", VWAP: "VWAP with optional SD bands",
  RSI: "Relative Strength Index", MACD: "MACD (12, 26, 9)",
  Stoch: "Stochastic Oscillator",
  VolumeProfile: "Price × Volume histogram",
  FVG: "Fair Value Gap zones",
  Pivot: "Standard / Fibonacci / Woodie / Camarilla",
};

// Fields that render as dropdowns instead of text/number inputs
const SELECT_OPTIONS: Record<string, { value: string; label: string }[]> = {
  source: [
    { value: "close",  label: "Close" },
    { value: "open",   label: "Open" },
    { value: "high",   label: "High" },
    { value: "low",    label: "Low" },
    { value: "hl2",    label: "HL/2  (High+Low)/2" },
    { value: "hlc3",   label: "HLC/3 (High+Low+Close)/3" },
    { value: "ohlc4",  label: "OHLC/4 (O+H+L+C)/4" },
    { value: "hlcc4",  label: "HLCC/4 (H+L+C+C)/4" },
  ],
  pivotType: [
    { value: "standard",  label: "Standard (Classic)" },
    { value: "fibonacci", label: "Fibonacci" },
    { value: "woodie",    label: "Woodie" },
    { value: "camarilla", label: "Camarilla" },
  ],
  pivotPeriod: [
    { value: "daily",   label: "Daily" },
    { value: "weekly",  label: "Weekly" },
    { value: "monthly", label: "Monthly" },
  ],
};

export type IndicatorPanelMode = "global" | "individual";

export interface LocalIndicatorHandlers {
  onAdd:    (type: IndicatorType) => void;
  onRemove: (id: string) => void;
  onUpdate: (ind: IndicatorConfig) => void;
}

interface Props {
  paneId: string;
  indicators: IndicatorConfig[];
  onClose: () => void;
  mode?: IndicatorPanelMode;
  local?: LocalIndicatorHandlers;  // when set: bypasses store entirely
}

type SettingsTab = "Inputs" | "Style" | "Visibility";

interface SettingsLayerProps {
  paneId: string;
  indicator: IndicatorConfig;
  onBack: () => void;
  mode: IndicatorPanelMode;
  local?: LocalIndicatorHandlers;
}

function SettingsLayer({ paneId, indicator, onBack, mode, local }: SettingsLayerProps) {
  const { updateIndicator, updateIndicatorByLinkId } = useDashboardStore();
  const [tab, setTab] = useState<SettingsTab>("Inputs");
  const [draft, setDraft] = useState<IndicatorConfig>({ ...indicator, inputs: { ...indicator.inputs }, style: { ...indicator.style } });

  const handleApply = () => {
    if (local) {
      local.onUpdate(draft);
    } else if (mode === "global" && draft.linkId) {
      updateIndicatorByLinkId(draft.linkId, { inputs: draft.inputs, style: draft.style, visible: draft.visible });
    } else {
      updateIndicator(paneId, draft);
    }
    onBack();
  };

  const tabBtn = (t: SettingsTab): React.CSSProperties => ({
    background: tab === t ? TV.accent : "transparent",
    border: "none",
    borderRadius: 3,
    color: tab === t ? "#fff" : TV.muted,
    fontSize: 11,
    padding: "3px 10px",
    cursor: "pointer",
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, height: "100%", minHeight: 0 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 12px", borderBottom: `1px solid ${TV.border}`, flexShrink: 0 }}>
        <button
          onClick={onBack}
          style={{ background: "transparent", border: "none", color: TV.muted, cursor: "pointer", fontSize: 14, padding: "0 4px" }}
        >
          ←
        </button>
        <span style={{ color: TV.text, fontSize: 12, fontWeight: 600 }}>
          {INDICATOR_LABELS[indicator.type]}
        </span>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 4, padding: "8px 12px", borderBottom: `1px solid ${TV.border}`, flexShrink: 0 }}>
        {(["Inputs", "Style", "Visibility"] as SettingsTab[]).map((t) => (
          <button key={t} style={tabBtn(t)} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      {/* Tab Content */}
      <div style={{ flex: 1, overflowY: "auto", padding: "12px" }}>
        {tab === "Inputs" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {Object.entries(draft.inputs).map(([key, value]) => (
              <div key={key} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <label style={{ fontSize: 11, color: TV.muted, textTransform: "capitalize", flexShrink: 0 }}>
                  {key === "pivotType" ? "Type" : key === "pivotPeriod" ? "Period" : key === "showBands" ? "Show Bands" : key}
                </label>
                {SELECT_OPTIONS[key] ? (
                  <select
                    value={String(value)}
                    onChange={(e) => setDraft((d) => ({ ...d, inputs: { ...d.inputs, [key]: e.target.value } }))}
                    style={{
                      background: "#131722", border: `1px solid ${TV.border}`, borderRadius: 3,
                      color: TV.text, padding: "2px 6px", fontSize: 11, outline: "none", cursor: "pointer",
                    }}
                  >
                    {SELECT_OPTIONS[key].map(({ value: v, label: l }) => (
                      <option key={v} value={v}>{l}</option>
                    ))}
                  </select>
                ) : typeof value === "boolean" ? (
                  <input
                    type="checkbox"
                    checked={value}
                    onChange={(e) => setDraft((d) => ({ ...d, inputs: { ...d.inputs, [key]: e.target.checked } }))}
                    style={{ cursor: "pointer" }}
                  />
                ) : typeof value === "number" ? (
                  <input
                    type="number"
                    value={value}
                    onChange={(e) => setDraft((d) => ({ ...d, inputs: { ...d.inputs, [key]: parseFloat(e.target.value) || 0 } }))}
                    style={{
                      background: "#131722", border: `1px solid ${TV.border}`, borderRadius: 3,
                      color: TV.text, padding: "2px 6px", fontSize: 11, width: 80, outline: "none",
                    }}
                  />
                ) : (
                  <input
                    type="text"
                    value={String(value)}
                    onChange={(e) => setDraft((d) => ({ ...d, inputs: { ...d.inputs, [key]: e.target.value } }))}
                    style={{
                      background: "#131722", border: `1px solid ${TV.border}`, borderRadius: 3,
                      color: TV.text, padding: "2px 6px", fontSize: 11, width: 80, outline: "none",
                    }}
                  />
                )}
              </div>
            ))}
            {Object.keys(draft.inputs).length === 0 && (
              <p style={{ color: TV.muted, fontSize: 11 }}>No inputs for this indicator.</p>
            )}
          </div>
        )}

        {tab === "Style" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {Object.entries(draft.style).map(([key, value]) => (
              <div key={key} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <label style={{ fontSize: 11, color: TV.muted, textTransform: "capitalize", flexShrink: 0 }}>{key}</label>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <input
                    type="color"
                    value={value.length === 7 ? value : "#888888"}
                    onChange={(e) => setDraft((d) => ({ ...d, style: { ...d.style, [key]: e.target.value } }))}
                    style={{ width: 28, height: 22, border: "none", borderRadius: 3, cursor: "pointer", padding: 0, background: "transparent" }}
                  />
                  <input
                    type="text"
                    value={value}
                    onChange={(e) => setDraft((d) => ({ ...d, style: { ...d.style, [key]: e.target.value } }))}
                    style={{
                      background: "#131722", border: `1px solid ${TV.border}`, borderRadius: 3,
                      color: TV.text, padding: "2px 6px", fontSize: 10, width: 70, outline: "none",
                      fontFamily: "monospace",
                    }}
                  />
                </div>
              </div>
            ))}
            {Object.keys(draft.style).length === 0 && (
              <p style={{ color: TV.muted, fontSize: 11 }}>No style options for this indicator.</p>
            )}
          </div>
        )}

        {tab === "Visibility" && (
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <input
              type="checkbox"
              id="vis-checkbox"
              checked={draft.visible}
              onChange={(e) => setDraft((d) => ({ ...d, visible: e.target.checked }))}
              style={{ cursor: "pointer" }}
            />
            <label htmlFor="vis-checkbox" style={{ fontSize: 12, color: TV.text, cursor: "pointer" }}>
              Visible on chart
            </label>
          </div>
        )}
      </div>

      {/* Footer buttons */}
      <div style={{ display: "flex", gap: 8, padding: "10px 12px", borderTop: `1px solid ${TV.border}`, flexShrink: 0 }}>
        <button
          onClick={onBack}
          style={{
            flex: 1, background: "transparent", border: `1px solid ${TV.border}`,
            borderRadius: 3, color: TV.muted, fontSize: 11, padding: "5px 0", cursor: "pointer",
          }}
        >
          Cancel
        </button>
        <button
          onClick={handleApply}
          style={{
            flex: 1, background: TV.accent, border: "none",
            borderRadius: 3, color: "#fff", fontSize: 11, padding: "5px 0", cursor: "pointer",
          }}
        >
          Apply
        </button>
      </div>
    </div>
  );
}

export default function IndicatorPanel({ paneId, indicators, onClose, mode = "individual", local }: Props) {
  const { addIndicator, addIndicatorToAll, removeIndicator, removeIndicatorByLinkId } = useDashboardStore();
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<IndicatorConfig | null>(null);

  const countByType = indicators.reduce<Record<string, number>>((acc, i) => {
    acc[i.type] = (acc[i.type] ?? 0) + 1;
    return acc;
  }, {});
  const q = search.trim().toLowerCase();

  const filterType = (type: IndicatorType) =>
    !q ||
    INDICATOR_LABELS[type].toLowerCase().includes(q) ||
    INDICATOR_DESCRIPTIONS[type].toLowerCase().includes(q);

  const filteredOverlays    = OVERLAY_TYPES.filter(filterType);
  const filteredOscillators = OSCILLATOR_TYPES.filter(filterType);

  const btnStyle: React.CSSProperties = {
    background: "transparent", border: `1px solid ${TV.border}`,
    borderRadius: 3, color: TV.muted, fontSize: 11,
    padding: "2px 7px", cursor: "pointer",
  };

  return (
    <div style={{
      width: "100%", flex: 1, height: "100%", minHeight: 0, background: TV.bg,
      borderLeft: `1px solid ${TV.border}`,
      display: "flex", flexDirection: "column",
    }}>
      {editing ? (
        <SettingsLayer
          paneId={paneId}
          indicator={editing}
          onBack={() => setEditing(null)}
          mode={mode}
          local={local}
        />
      ) : (
        <>
          {/* Header */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 12px", borderBottom: `1px solid ${TV.border}` }}>
            <div>
              <span style={{ color: TV.text, fontSize: 12, fontWeight: 600 }}>Indicators</span>
              {mode === "global" ? (
                <span style={{ color: TV.up, fontSize: 9, marginLeft: 8, border: `1px solid ${TV.up}`, borderRadius: 3, padding: "1px 5px" }}>ALL CHARTS</span>
              ) : (
                <span style={{ color: TV.muted, fontSize: 9, marginLeft: 8, border: `1px solid ${TV.border}`, borderRadius: 3, padding: "1px 5px" }}>THIS CHART</span>
              )}
            </div>
            <button
              onClick={onClose}
              style={{ background: "transparent", border: "none", color: TV.muted, cursor: "pointer", fontSize: 16, lineHeight: 1 }}
            >
              ×
            </button>
          </div>

          {/* Search */}
          <div style={{ padding: "8px 12px", borderBottom: `1px solid ${TV.border}`, flexShrink: 0 }}>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search indicators…"
              style={{
                width: "100%", boxSizing: "border-box",
                background: "#131722", border: `1px solid ${TV.border}`,
                borderRadius: 4, color: TV.text, padding: "5px 8px",
                fontSize: 11, outline: "none",
              }}
            />
          </div>

          {/* List */}
          <div style={{ flex: 1, overflowY: "auto" }}>
            {/* Overlays section */}
            {filteredOverlays.length > 0 && (
              <div>
                <div style={{ padding: "6px 12px", fontSize: 10, color: TV.muted, textTransform: "uppercase", letterSpacing: "0.8px", background: "#181c28" }}>
                  Overlays
                </div>
                {filteredOverlays.map((type) => {
                  const count = countByType[type] ?? 0;
                  return (
                    <div key={type} style={{
                      display: "flex", alignItems: "center", justifyContent: "space-between",
                      padding: "7px 12px", borderBottom: `1px solid ${TV.border}22`,
                      cursor: "default",
                    }}>
                      <div>
                        <div style={{ fontSize: 11, color: count > 0 ? TV.accent : TV.text }}>
                          {INDICATOR_LABELS[type]}
                          {count > 0 && <span style={{ fontSize: 9, marginLeft: 4, opacity: 0.7 }}>×{count}</span>}
                        </div>
                        <div style={{ fontSize: 10, color: TV.muted }}>{INDICATOR_DESCRIPTIONS[type]}</div>
                      </div>
                      <div style={{ display: "flex", gap: 4 }}>
                        {mode === "global" ? (
                          <>
                            <button onClick={() => addIndicatorToAll(type)} style={btnStyle} title="Add to all charts">+</button>
                            <button onClick={() => addIndicator(paneId, type)} style={{ ...btnStyle, fontSize: 9, opacity: 0.6 }} title="Add to focused chart only">+1</button>
                          </>
                        ) : (
                          <button onClick={() => local ? local.onAdd(type) : addIndicator(paneId, type)} style={btnStyle} title="Add to this chart">+</button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Oscillators section */}
            {filteredOscillators.length > 0 && (
              <div>
                <div style={{ padding: "6px 12px", fontSize: 10, color: TV.muted, textTransform: "uppercase", letterSpacing: "0.8px", background: "#181c28" }}>
                  Oscillators
                </div>
                {filteredOscillators.map((type) => {
                  const count = countByType[type] ?? 0;
                  return (
                    <div key={type} style={{
                      display: "flex", alignItems: "center", justifyContent: "space-between",
                      padding: "7px 12px", borderBottom: `1px solid ${TV.border}22`,
                      cursor: "default",
                    }}>
                      <div>
                        <div style={{ fontSize: 11, color: count > 0 ? TV.accent : TV.text }}>
                          {INDICATOR_LABELS[type]}
                          {count > 0 && <span style={{ fontSize: 9, marginLeft: 4, opacity: 0.7 }}>×{count}</span>}
                        </div>
                        <div style={{ fontSize: 10, color: TV.muted }}>{INDICATOR_DESCRIPTIONS[type]}</div>
                      </div>
                      <div style={{ display: "flex", gap: 4 }}>
                        {mode === "global" ? (
                          <>
                            <button onClick={() => addIndicatorToAll(type)} style={btnStyle} title="Add to all charts">+</button>
                            <button onClick={() => addIndicator(paneId, type)} style={{ ...btnStyle, fontSize: 9, opacity: 0.6 }} title="Add to focused chart only">+1</button>
                          </>
                        ) : (
                          <button onClick={() => local ? local.onAdd(type) : addIndicator(paneId, type)} style={btnStyle} title="Add to this chart">+</button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {filteredOverlays.length === 0 && filteredOscillators.length === 0 && (
              <div style={{ padding: "20px 12px", color: TV.muted, fontSize: 11, textAlign: "center" }}>
                No indicators match "{search}"
              </div>
            )}
          </div>

          {/* Active indicators footer */}
          {indicators.length > 0 && (
            <div style={{ borderTop: `1px solid ${TV.border}`, padding: "8px 12px", flexShrink: 0 }}>
              <div style={{ fontSize: 10, color: TV.muted, textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: 6 }}>
                {mode === "global" ? "All charts — ⚙ edits all · ✕ removes all" : "This chart — ⚙ edits this · ✕ removes this"}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, maxHeight: 120, overflowY: "auto" }}>
                {indicators.map((ind) => (
                  <div
                    key={ind.id}
                    style={{
                      display: "flex", alignItems: "center", gap: 3,
                      background: "#131722", border: `1px solid ${TV.border}`,
                      borderRadius: 3, padding: "2px 6px", fontSize: 10,
                    }}
                  >
                    <span style={{ color: ind.visible ? TV.accent : TV.muted }}>
                      {INDICATOR_LABELS[ind.type]}
                    </span>
                    <button
                      onClick={() => setEditing(ind)}
                      title={mode === "global" ? "Edit settings on all charts" : "Edit settings on this chart"}
                      style={{ background: "transparent", border: "none", color: TV.muted, cursor: "pointer", fontSize: 10, padding: "0 1px", lineHeight: 1 }}
                    >
                      ⚙
                    </button>
                    <button
                      onClick={() => {
                        if (local) {
                          local.onRemove(ind.id);
                        } else if (mode === "global" && ind.linkId) {
                          removeIndicatorByLinkId(ind.linkId);
                        } else {
                          removeIndicator(paneId, ind.id);
                        }
                      }}
                      title={mode === "global" ? "Remove from all charts" : "Remove from this chart"}
                      style={{ background: "transparent", border: "none", color: TV.down, cursor: "pointer", fontSize: 11, padding: "0 1px", lineHeight: 1 }}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
