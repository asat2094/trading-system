import type { UTCTimestamp } from "lightweight-charts";

export function tsToUnix(ts: string): UTCTimestamp {
  // Normalize space separator first — "2026-05-31 09:00:00+00:00" → "2026-05-31T09:00:00+00:00"
  // V8's Date.parse rejects space when a tz offset follows.
  const s = ts.replace(" ", "T");
  if (/[+-]\d{2}:\d{2}$/.test(s) || s.endsWith("Z")) {
    return (new Date(s).getTime() / 1000) as UTCTimestamp;
  }
  return (new Date(s + "Z").getTime() / 1000) as UTCTimestamp;
}
