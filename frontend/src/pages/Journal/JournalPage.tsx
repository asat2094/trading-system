import { useEffect, useState } from "react";
import { useJournalStore } from "../../store/journal";
import { JrnSummary } from "../../api/journal";
import ImportPanel from "../../components/Journal/ImportPanel";
import DaySummaryCard from "../../components/Journal/DaySummaryCard";
import PairsTable from "../../components/Journal/PairsTable";
import TradeTable from "../../components/Journal/TradeTable";
import TimelineBuckets from "../../components/Journal/TimelineBuckets";

const TV = { bg: "#131722", border: "#2a2e39", text: "#d1d4dc", muted: "#787b86", accent: "#2962ff" };

const TAB_STYLE = (active: boolean): React.CSSProperties => ({
  padding: "6px 16px", cursor: "pointer", fontSize: 13,
  color: active ? TV.text : TV.muted, fontWeight: active ? 600 : 400,
  background: "transparent", border: "none",
  borderBottom: `2px solid ${active ? TV.accent : "transparent"}`,
});

function listItems(summaries: JrnSummary[]): JrnSummary[] {
  // Show per-broker rows (broker != null); fall back to combined if none
  const perBroker = summaries.filter(s => s.broker !== null);
  return perBroker.length > 0 ? perBroker : summaries;
}

export default function JournalPage() {
  const { summaries, pairs, trades, fetchSummaries, fetchPairs, fetchTrades, reset } = useJournalStore();
  const [tab, setTab] = useState<"summary" | "pairs" | "trades" | "import">("summary");
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [selectedBroker, setSelectedBroker] = useState<string | null>(null);

  // Reset stale pairs/trades on every mount — prevents crash-on-navigate-back
  useEffect(() => {
    reset();
    fetchSummaries();
  }, []);

  const items = listItems(summaries);

  const selected = selectedDate
    ? summaries.find(s => s.trade_date === selectedDate && s.broker === selectedBroker)
    : null;

  const handleSelectDay = (date: string, broker: string | null) => {
    setSelectedDate(date);
    setSelectedBroker(broker);
    setTab("summary");
    reset();
  };

  const handleTabChange = (t: typeof tab) => {
    setTab(t);
    if (!selectedDate) return;
    const params: Record<string, string> = {
      from_date: selectedDate,
      to_date: selectedDate,
      ...(selectedBroker ? { broker: selectedBroker } : {}),
    };
    if (t === "pairs") fetchPairs(params);
    if (t === "trades") fetchTrades(params);
  };

  return (
    <div style={{ display: "flex", height: "100%", background: TV.bg, color: TV.text, overflow: "hidden" }}>
      {/* Left: per-broker day list */}
      <div style={{ width: 210, borderRight: `1px solid ${TV.border}`, overflowY: "auto", flexShrink: 0 }}>
        <div style={{ padding: "12px 16px", fontSize: 11, color: TV.muted, borderBottom: `1px solid ${TV.border}`, textTransform: "uppercase", letterSpacing: "0.8px" }}>
          Trade Days
        </div>
        {items.map(s => {
          const isActive = selectedDate === s.trade_date && selectedBroker === s.broker;
          return (
            <div
              key={`${s.trade_date}:${s.broker ?? ""}`}
              onClick={() => handleSelectDay(s.trade_date, s.broker)}
              style={{
                padding: "10px 16px", cursor: "pointer", fontSize: 12,
                background: isActive ? "#1e222d" : "transparent",
                borderLeft: `3px solid ${isActive ? TV.accent : "transparent"}`,
                borderBottom: `1px solid ${TV.border}`,
              }}
            >
              <div style={{ fontWeight: 600 }}>{s.trade_date}</div>
              {s.broker && <div style={{ fontSize: 10, color: TV.muted, marginTop: 1 }}>{s.broker}</div>}
              <div style={{ color: s.net_pnl >= 0 ? "#26a69a" : "#ef5350", marginTop: 2 }}>
                {s.net_pnl >= 0 ? "+" : "-"}₹{Math.abs(s.net_pnl).toFixed(0)}
              </div>
            </div>
          );
        })}
        {!items.length && (
          <div style={{ padding: 16, color: "#363c4e", fontSize: 12 }}>No data. Import a contract note.</div>
        )}
      </div>

      {/* Right: detail pane */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Tab bar with selected context */}
        <div style={{ display: "flex", borderBottom: `1px solid ${TV.border}`, flexShrink: 0, alignItems: "center" }}>
          {(["summary", "pairs", "trades", "import"] as const).map(t => (
            <button key={t} style={TAB_STYLE(tab === t)} onClick={() => handleTabChange(t)}>
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
          {selectedDate && (
            <div style={{ marginLeft: "auto", padding: "0 16px", fontSize: 11, color: TV.muted, display: "flex", alignItems: "center", gap: 6 }}>
              {selectedDate}{selectedBroker ? ` · ${selectedBroker}` : ""}
              <button
                onClick={() => { setSelectedDate(null); setSelectedBroker(null); reset(); }}
                style={{ background: "transparent", border: "none", color: TV.muted, cursor: "pointer", fontSize: 13, lineHeight: 1 }}
                title="Clear filter"
              >✕</button>
            </div>
          )}
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
          {tab === "import" && (
            <ImportPanel onDone={() => {
              reset();
              fetchSummaries();
              setTab("summary");
              setSelectedDate(null);
              setSelectedBroker(null);
            }} />
          )}

          {tab === "summary" && (
            selected ? (
              <div>
                <DaySummaryCard s={selected} />
                <TimelineBuckets buckets={selected.time_bucket_pnl} />
              </div>
            ) : (
              <div>
                {items.length > 0 && !selectedDate && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                    {items.slice(0, 20).map(s => <DaySummaryCard key={s.id} s={s} />)}
                  </div>
                )}
                {selectedDate && !selected && (
                  <div style={{ color: TV.muted, fontSize: 13 }}>
                    No summary for {selectedDate}{selectedBroker ? ` (${selectedBroker})` : ""}.
                  </div>
                )}
                {!items.length && (
                  <div style={{ color: TV.muted, fontSize: 13 }}>
                    No data. Go to Import to upload a contract note.
                  </div>
                )}
              </div>
            )
          )}

          {tab === "pairs" && (
            selectedDate
              ? <PairsTable pairs={pairs} />
              : <div style={{ color: TV.muted, fontSize: 13 }}>Select a day from the left to view pairs.</div>
          )}

          {tab === "trades" && (
            selectedDate
              ? <TradeTable trades={trades} />
              : <div style={{ color: TV.muted, fontSize: 13 }}>Select a day from the left to view trades.</div>
          )}
        </div>
      </div>
    </div>
  );
}
