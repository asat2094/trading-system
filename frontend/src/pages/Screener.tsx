import { useFiltersStore } from "../store/filters";
import { useRunScan } from "../api/scanner";
import ConditionBuilder from "../components/Screener/ConditionBuilder";
import ResultsTable from "../components/Screener/ResultsTable";

export default function Screener() {
  const { source, filters, indicators, maxSymbols } = useFiltersStore();
  const { mutate: runScan, data, isPending } = useRunScan();

  function handleRun() {
    runScan({
      source,
      filters: filters.map((f) => ({ field: f.field, operator: f.operator, value: f.value })),
      indicators,
      max_symbols: maxSymbols,
    });
  }

  const results = data?.symbols?.map((s) => ({ symbol: s })) ?? [];

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <div style={{ width: 320, borderRight: "1px solid #333", overflowY: "auto" }}>
        <ConditionBuilder />
        <div style={{ padding: 16 }}>
          <button onClick={handleRun} disabled={isPending} style={{ width: "100%", padding: 10 }}>
            {isPending ? "Running..." : "Run Scan"}
          </button>
        </div>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
        <h3>Results ({results.length})</h3>
        <ResultsTable data={results} />
      </div>
    </div>
  );
}
