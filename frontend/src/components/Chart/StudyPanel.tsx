import { useState } from "react";
import type { StudyConfig, StudyType } from "./types";
import { OVERLAY_TYPES, OSCILLATOR_TYPES, STUDY_DEFAULTS, studyLabel } from "./types";

interface Props {
  studies: StudyConfig[];
  onAdd:    (s: StudyConfig) => void;
  onUpdate: (s: StudyConfig) => void;
  onRemove: (id: string) => void;
  onClose:  () => void;
}

export default function StudyPanel({ studies, onAdd, onUpdate, onRemove, onClose }: Props) {
  const [editId, setEditId] = useState<string | null>(null);

  function addStudy(type: StudyType) {
    const defaults = STUDY_DEFAULTS[type];
    onAdd({ ...defaults, id: crypto.randomUUID() } as StudyConfig);
  }

  return (
    <div style={panelStyle} onClick={e => e.stopPropagation()}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <span style={{ color: "#d1d4dc", fontWeight: 700, fontSize: 13 }}>Indicators</span>
        <button onClick={onClose} style={closeBtnStyle}>✕</button>
      </div>

      {/* Available indicators */}
      <div style={{ marginBottom: 14 }}>
        <div style={sectionLabelStyle}>OVERLAYS</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {OVERLAY_TYPES.map(t => (
            <button key={t} onClick={() => addStudy(t)} style={addBtnStyle}>{t} +</button>
          ))}
        </div>
      </div>
      <div style={{ marginBottom: 14 }}>
        <div style={sectionLabelStyle}>OSCILLATORS</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {OSCILLATOR_TYPES.map(t => (
            <button key={t} onClick={() => addStudy(t)} style={addBtnStyle}>{t} +</button>
          ))}
        </div>
      </div>

      {/* Active studies */}
      {studies.length > 0 && (
        <div>
          <div style={sectionLabelStyle}>ACTIVE</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {studies.map(s => (
              <div key={s.id}>
                <div style={studyRowStyle}>
                  <span style={{ color: "#d1d4dc", fontSize: 12, flex: 1 }}>{studyLabel(s)}</span>
                  <button
                    onClick={() => setEditId(editId === s.id ? null : s.id)}
                    style={{ ...iconBtnStyle, color: editId === s.id ? "#2962ff" : "#787b86" }}
                    title="Settings"
                  >⚙</button>
                  <button
                    onClick={() => { onRemove(s.id); if (editId === s.id) setEditId(null); }}
                    style={{ ...iconBtnStyle, color: "#ef5350" }}
                    title="Remove"
                  >✕</button>
                </div>
                {editId === s.id && (
                  <StudyEditor study={s} onChange={onUpdate} />
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Inline param editor ───────────────────────────────────────────────────────
function StudyEditor({ study, onChange }: { study: StudyConfig; onChange: (s: StudyConfig) => void }) {
  function num(field: string, label: string, value: number) {
    return (
      <label style={fieldStyle}>
        <span style={fieldLabelStyle}>{label}</span>
        <input
          type="number" min={1} value={value}
          onChange={e => onChange({ ...study, [field]: Number(e.target.value) } as StudyConfig)}
          style={inputStyle}
        />
      </label>
    );
  }

  function color(field: string, label: string, value: string) {
    return (
      <label style={fieldStyle}>
        <span style={fieldLabelStyle}>{label}</span>
        <input
          type="color" value={value}
          onChange={e => onChange({ ...study, [field]: e.target.value } as StudyConfig)}
          style={{ ...inputStyle, width: 32, padding: 0, cursor: "pointer" }}
        />
      </label>
    );
  }

  return (
    <div style={editorStyle}>
      {study.type === "EMA"  && <>{num("period","Period",study.period)}{color("color","Color",study.color)}</>}
      {study.type === "SMA"  && <>{num("period","Period",study.period)}{color("color","Color",study.color)}</>}
      {study.type === "BB"   && <>
        {num("period","Period",study.period)}
        {num("std","Std Dev",study.std)}
        {color("upperColor","Upper",study.upperColor)}
        {color("midColor","Mid",study.midColor)}
        {color("lowerColor","Lower",study.lowerColor)}
      </>}
      {study.type === "VWAP" && <>{color("color","Color",study.color)}</>}
      {study.type === "RSI"  && <>{num("period","Period",study.period)}{color("color","Color",study.color)}</>}
      {study.type === "MACD" && <>
        {num("fast","Fast",study.fast)}
        {num("slow","Slow",study.slow)}
        {num("signal","Signal",study.signal)}
        {color("macdColor","MACD",study.macdColor)}
        {color("signalColor","Signal",study.signalColor)}
      </>}
      {study.type === "Stoch" && <>
        {num("k","%K Period",study.k)}
        {num("d","%D Period",study.d)}
        {num("smooth","Smooth",study.smooth)}
        {color("kColor","%K",study.kColor)}
        {color("dColor","%D",study.dColor)}
      </>}
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────
const panelStyle: React.CSSProperties = {
  position: "absolute",
  top: 0, right: 0,
  width: 260,
  height: "100%",
  background: "#1e222d",
  borderLeft: "1px solid #2a2e39",
  padding: "14px 12px",
  overflowY: "auto",
  zIndex: 100,
  boxSizing: "border-box",
};

const sectionLabelStyle: React.CSSProperties = {
  fontSize: 10, color: "#4a4f5e", fontWeight: 700,
  letterSpacing: 1, marginBottom: 6,
};

const addBtnStyle: React.CSSProperties = {
  background: "#131722", border: "1px solid #2a2e39",
  borderRadius: 3, color: "#787b86",
  padding: "3px 8px", cursor: "pointer", fontSize: 11, fontWeight: 600,
};

const studyRowStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 4,
  background: "#131722", borderRadius: 3, padding: "4px 8px",
};

const iconBtnStyle: React.CSSProperties = {
  background: "none", border: "none",
  cursor: "pointer", fontSize: 12, padding: "0 2px",
};

const closeBtnStyle: React.CSSProperties = {
  background: "none", border: "none",
  color: "#787b86", cursor: "pointer", fontSize: 14,
};

const editorStyle: React.CSSProperties = {
  background: "#131722", borderRadius: 3,
  padding: "6px 8px", marginTop: 2,
  display: "flex", flexWrap: "wrap", gap: 6,
};

const fieldStyle: React.CSSProperties = {
  display: "flex", flexDirection: "column", gap: 2,
};

const fieldLabelStyle: React.CSSProperties = {
  fontSize: 9, color: "#4a4f5e", fontWeight: 700, letterSpacing: 0.5,
};

const inputStyle: React.CSSProperties = {
  background: "#2a2e39", border: "1px solid #363c4e",
  borderRadius: 3, color: "#d1d4dc",
  padding: "3px 5px", fontSize: 11, width: 52,
};
