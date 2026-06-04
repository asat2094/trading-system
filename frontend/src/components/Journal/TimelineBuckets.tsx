const TV = { bg: "#1e222d", border: "#2a2e39", text: "#d1d4dc", muted: "#787b86", green: "#26a69a", red: "#ef5350" };

export default function TimelineBuckets({ buckets }: { buckets: Record<string, number> | null }) {
  if (!buckets || !Object.keys(buckets).length) return null;
  const entries = Object.entries(buckets).sort(([a], [b]) => a.localeCompare(b));
  const maxAbs = Math.max(...entries.map(([, v]) => Math.abs(v)), 1);
  return (
    <div style={{ padding: "12px 0" }}>
      <div style={{ fontSize: 11, color: TV.muted, marginBottom: 8 }}>P&L by 30-min bucket</div>
      <div style={{ display: "flex", gap: 3, alignItems: "flex-end", height: 60 }}>
        {entries.map(([label, val]) => {
          const h = Math.max(4, Math.round((Math.abs(val) / maxAbs) * 56));
          return (
            <div key={label} title={`${label}: ₹${val.toFixed(0)}`}
              style={{ display: "flex", flexDirection: "column", alignItems: "center", flex: 1 }}>
              <div style={{
                width: "100%", height: h,
                background: val >= 0 ? TV.green : TV.red,
                borderRadius: "2px 2px 0 0", opacity: 0.85,
              }} />
              <div style={{ fontSize: 9, color: TV.muted, marginTop: 2, transform: "rotate(-45deg)", transformOrigin: "top left", whiteSpace: "nowrap" }}>
                {label}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
