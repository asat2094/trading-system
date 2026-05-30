/**
 * FnoLive page — live NIFTY FnO analysis.
 *
 * Layout:
 *   [Header: symbol + expiry + fetched_at + Refresh button]
 *   [PcrCards]
 *   [OptionsChainTable]
 */
import { useState, useCallback } from "react";
import { apiClient } from "../api/client";
import PcrCards from "../components/Fno/PcrCards";
import OptionsChainTable from "../components/Fno/OptionsChainTable";
import type { FnoSnapshot } from "../components/Fno/types";

const TV = {
  bg: "#0d0d1a", panel: "#131722", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86", accent: "#2962ff",
  warn: "#f59e0b",
} as const;

const btnStyle = (disabled: boolean): React.CSSProperties => ({
  background: disabled ? "#1e222d" : TV.accent,
  border: `1px solid ${disabled ? TV.border : TV.accent}`,
  borderRadius: 4, color: disabled ? TV.muted : "#fff",
  padding: "6px 18px", cursor: disabled ? "default" : "pointer",
  fontSize: 13, fontWeight: 600,
});

export default function FnoLive() {
  const [snapshot, setSnapshot] = useState<FnoSnapshot | null>(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string>("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { data } = await apiClient.get<FnoSnapshot>("/fno/snapshot", {
        params: { symbol: "NIFTY", strikes: 10 },
      });
      setSnapshot(data);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } }; message?: string })
        ?.response?.data?.detail ?? (e as Error)?.message ?? "Fetch failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div style={{ height: "100%", overflowY: "auto", background: TV.bg, padding: 16 }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 14,
        marginBottom: 16, flexWrap: "wrap",
      }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: TV.text }}>
          NIFTY FnO Live
        </span>

        {snapshot && (
          <span style={{ fontSize: 12, color: TV.muted }}>
            Expiry: {snapshot.expiry}
            &nbsp;·&nbsp;
            Fetched: {new Date(snapshot.fetched_at).toLocaleTimeString("en-IN")}
          </span>
        )}

        <button onClick={refresh} disabled={loading} style={btnStyle(loading)}>
          {loading ? "⏳ Fetching…" : "↻ Refresh"}
        </button>

        {error && (
          <span style={{ color: "#ef5350", fontSize: 12 }}>{error}</span>
        )}
      </div>

      {/* Empty state */}
      {!snapshot && !loading && (
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center",
          justifyContent: "center", minHeight: 300, gap: 12,
          color: TV.muted,
        }}>
          <div style={{ fontSize: 40 }}>📊</div>
          <div style={{ fontSize: 14 }}>Press Refresh to load NIFTY option chain</div>
          <div style={{ fontSize: 11 }}>Requires active Kite MCP session</div>
        </div>
      )}

      {/* Data */}
      {snapshot && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <PcrCards snapshot={snapshot} />
          <OptionsChainTable snapshot={snapshot} />
        </div>
      )}
    </div>
  );
}
