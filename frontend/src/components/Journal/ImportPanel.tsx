import { useRef, useState } from "react";
import { useJournalStore } from "../../store/journal";

const TV = { bg: "#131722", border: "#2a2e39", text: "#d1d4dc", muted: "#787b86", accent: "#2962ff", green: "#26a69a", red: "#ef5350" };

export default function ImportPanel({ onDone }: { onDone?: () => void }) {
  const { importPdf, loading } = useJournalStore();
  const [dragging, setDragging] = useState(false);
  const [broker, setBroker] = useState("auto");
  const [password, setPassword] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    setResult(null); setError(null);
    try {
      const res = await importPdf(file, broker, password || undefined);
      setResult(`Imported ${res.imported} trades (${res.inserted} new) from ${file.name}`);
      onDone?.();
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || "Import failed");
    }
  };

  return (
    <div style={{ padding: 16, background: TV.bg, border: `1px solid ${TV.border}`, borderRadius: 6 }}>
      <div style={{ fontSize: 13, color: TV.text, fontWeight: 600, marginBottom: 12 }}>Import Contract Note</div>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <select value={broker} onChange={e => setBroker(e.target.value)}
          style={{ background: "#1e222d", border: `1px solid ${TV.border}`, color: TV.text, padding: "5px 8px", borderRadius: 4, fontSize: 12 }}>
          {["auto","zerodha","mstock","lemonn"].map(b => <option key={b} value={b}>{b}</option>)}
        </select>
        <input placeholder="PAN password (if encrypted)" value={password}
          onChange={e => setPassword(e.target.value)}
          style={{ background: "#1e222d", border: `1px solid ${TV.border}`, color: TV.text, padding: "5px 8px", borderRadius: 4, fontSize: 12, flex: 1, minWidth: 180 }} />
      </div>
      <div
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if (f) handleFile(f); }}
        onClick={() => inputRef.current?.click()}
        style={{
          border: `2px dashed ${dragging ? TV.accent : TV.border}`,
          borderRadius: 6, padding: "24px 16px",
          textAlign: "center", cursor: "pointer",
          color: TV.muted, fontSize: 13,
          background: dragging ? "#1a2040" : "transparent",
          transition: "all 0.1s",
        }}>
        {loading ? "Importing..." : "Drop PDF here or click to choose"}
        <input ref={inputRef} type="file" accept=".pdf" style={{ display: "none" }}
          onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); e.target.value = ""; }} />
      </div>
      {result && <div style={{ marginTop: 8, fontSize: 12, color: TV.green }}>{result}</div>}
      {error  && <div style={{ marginTop: 8, fontSize: 12, color: TV.red }}>{error}</div>}
    </div>
  );
}
