import { useState, useEffect } from "react";

const TIMEZONES = [
  { label: "IST",  offsetHours: 5.5  },
  { label: "UTC",  offsetHours: 0    },
  { label: "EST",  offsetHours: -5   },
  { label: "EDT",  offsetHours: -4   },
  { label: "CST",  offsetHours: -6   },
  { label: "PST",  offsetHours: -8   },
  { label: "SGT",  offsetHours: 8    },
  { label: "JST",  offsetHours: 9    },
  { label: "CET",  offsetHours: 1    },
  { label: "CEST", offsetHours: 2    },
];

const TF_MS: Record<string, number> = {
  "1min": 60_000, "3min": 180_000, "5min": 300_000, "15min": 900_000,
  "30min": 1_800_000, "1h": 3_600_000, "4h": 14_400_000,
  "1d": 86_400_000, "1w": 604_800_000,
};

function barCountdown(timeframe: string): string {
  const step = TF_MS[timeframe];
  if (!step) return "";
  const now = Date.now();
  const remaining = step - (now % step); // ms until next boundary
  const totalSec = Math.floor(remaining / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

interface Props {
  timeframe: string;
}

export default function PaneClock({ timeframe }: Props) {
  const [tzLabel, setTzLabel] = useState<string>(() =>
    localStorage.getItem("pane-clock-tz") ?? "IST"
  );
  const [clockDisplay, setClockDisplay] = useState("");

  useEffect(() => {
    const tz = TIMEZONES.find(t => t.label === tzLabel) ?? TIMEZONES[0];
    const tick = () => {
      const shifted = new Date(Date.now() + tz.offsetHours * 3_600_000);
      const H = shifted.getUTCHours().toString().padStart(2, "0");
      const M = shifted.getUTCMinutes().toString().padStart(2, "0");
      const S = shifted.getUTCSeconds().toString().padStart(2, "0");
      setClockDisplay(`${H}:${M}:${S}`);
      void barCountdown(timeframe); // computed in ChartPane price label instead
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [tzLabel, timeframe]);

  const handleTzChange = (label: string) => {
    setTzLabel(label);
    localStorage.setItem("pane-clock-tz", label);
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
      {/* Current time */}
      <span style={{
        fontFamily: "monospace", fontSize: 11,
        color: "#d1d4dc", letterSpacing: "0.5px", userSelect: "none",
      }}>
        {clockDisplay}
      </span>
      <select
        value={tzLabel}
        onChange={e => handleTzChange(e.target.value)}
        style={{
          background: "transparent", border: "none",
          color: "#787b86", fontSize: 10,
          cursor: "pointer", outline: "none", padding: 0,
        }}
      >
        {TIMEZONES.map(t => (
          <option key={t.label} value={t.label} style={{ background: "#1e222d", color: "#d1d4dc" }}>
            {t.label}
          </option>
        ))}
      </select>
    </div>
  );
}
