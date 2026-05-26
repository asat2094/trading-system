// frontend/src/pages/Screener.tsx
import { useFiltersStore } from "../store/filters";
import { useRunScan } from "../api/scanner";
import ConditionBuilder from "../components/Screener/ConditionBuilder";
import ResultsTable from "../components/Screener/ResultsTable";

export default function Screener() {
  const { source, defaultTimeframe, signals, customConditions, matchMode, maxSymbols } = useFiltersStore();
  const { mutate: runScan, data, isPending } = useRunScan();

  function handleRun() {
    runScan({
      universe: source,
      maxSymbols,
      defaultTimeframe,
      signals,
      customConditions,
      matchMode,
    });
  }

  const results = data?.results ?? [];
  const stats = data ? `${data.matched} / ${data.total_scanned} • ${data.duration_ms}ms` : null;

  return (
    <div style={{ display: "flex", height: "100vh", background: "#0d0d1a" }}>
      {/* Left panel — ConditionBuilder + Run button */}
      <div style={{
        width: 320, background: "#131722",
        borderRight: "1px solid #2a2e39",
        display: "flex", flexDirection: "column", overflowY: "auto", flexShrink: 0,
      }}>
        <div style={{ padding: "14px 16px", borderBottom: "1px solid #2a2e39" }}>
          <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: "#d1d4dc" }}>Scanner</h2>
        </div>
        <ConditionBuilder />
        <div style={{ padding: 16, borderTop: "1px solid #2a2e39" }}>
          <button
            onClick={handleRun}
            disabled={isPending}
            style={{
              width: "100%", padding: "10px 0",
              background: isPending ? "#1e4bd0" : "#2962ff",
              border: "none", borderRadius: 4,
              color: "#fff", fontSize: 14, fontWeight: 600,
              cursor: isPending ? "not-allowed" : "pointer",
            }}
          >
            {isPending ? "⟳ Scanning..." : "▶  Run Scan"}
          </button>
        </div>
      </div>

      {/* Right panel — Results */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflowY: "auto" }}>
        <div style={{
          padding: "14px 20px", borderBottom: "1px solid #2a2e39",
          background: "#131722", display: "flex", alignItems: "center", gap: 10,
        }}>
          <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: "#d1d4dc" }}>Results</h2>
          {results.length > 0 && (
            <span style={{
              background: "#26a69a", color: "#fff",
              borderRadius: 10, padding: "1px 8px", fontSize: 11,
            }}>
              {results.length}
            </span>
          )}
          {stats && (
            <span style={{ marginLeft: "auto", fontSize: 11, color: "#787b86" }}>{stats}</span>
          )}
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: results.length === 0 ? 0 : 16 }}>
          {results.length === 0 ? (
            <div style={{
              display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center",
              height: 300, color: "#363c4e",
            }}>
              <div style={{ fontSize: 48, marginBottom: 16 }}>⊞</div>
              <div style={{ fontSize: 14, color: "#787b86", marginBottom: 8 }}>No results yet</div>
              <div style={{ fontSize: 12, color: "#363c4e" }}>
                Select signals or add conditions, then run scan
              </div>
            </div>
          ) : (
            <ResultsTable data={results} />
          )}
        </div>
      </div>
    </div>
  );
}
