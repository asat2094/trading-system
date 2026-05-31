/**
 * MarketStatusBar — India / US / Crypto open-closed strip.
 * Pure frontend: no API calls. Recomputes every 30 seconds.
 */
import { useState, useEffect } from "react";
import { useLiveQuotesStore } from "../../store/liveQuotes";
import * as marketWs from "../../lib/marketWs";

const TV = {
  bg: "#131722", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86",
  up: "#26a69a", warn: "#f59e0b",
} as const;

function nowIn(tz: string): Date {
  return new Date(new Date().toLocaleString("en-US", { timeZone: tz }));
}

function fmt2(n: number) { return String(n).padStart(2, "0"); }
function timeStr(d: Date) { return `${fmt2(d.getHours())}:${fmt2(d.getMinutes())}`; }
function dayName(d: Date) { return ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][d.getDay()]; }

function fmtCountdown(minutes: number): string {
  const abs = Math.abs(minutes);
  const h = Math.floor(abs / 60);
  const m = abs % 60;
  return h > 0 ? `${h}h ${fmt2(m)}m` : `${m}m`;
}

type MarketStatus = "OPEN" | "PRE" | "AFTER" | "CLOSED" | "WEEKEND";

interface MarketInfo {
  label: string;
  status: MarketStatus;
  statusLabel: string;
  detail: string;
  localTime: string;
  dotColor: string;
}

function indiaStatus(): MarketInfo {
  const d   = nowIn("Asia/Kolkata");
  const day = d.getDay();
  const min = d.getHours() * 60 + d.getMinutes();
  const OPEN_M = 9 * 60 + 15, CLOSE_M = 15 * 60 + 30, PRE_M = 9 * 60;
  let status: MarketStatus, detail: string;

  if (day === 0 || day === 6) {
    status = "WEEKEND";
    detail = `opens Mon 09:15 IST`;
  } else if (min >= PRE_M && min < OPEN_M) {
    status = "PRE";
    detail = `opens in ${fmtCountdown(OPEN_M - min)}`;
  } else if (min >= OPEN_M && min < CLOSE_M) {
    status = "OPEN";
    detail = `closes in ${fmtCountdown(CLOSE_M - min)}`;
  } else {
    status = "CLOSED";
    if (min < OPEN_M) {
      // Early morning — opens later today
      detail = `opens in ${fmtCountdown(OPEN_M - min)}`;
    } else if (day === 5) {
      // Friday after close — opens Monday
      detail = `opens Mon in ${fmtCountdown(OPEN_M + 3 * 1440 - min)}`;
    } else {
      // Weekday after close — opens tomorrow
      detail = `opens ${dayName(new Date(d.getTime() + 86400_000))} in ${fmtCountdown(OPEN_M + 1440 - min)}`;
    }
  }

  return {
    label: "🇮🇳 India NSE",
    status,
    statusLabel: status === "WEEKEND" ? "CLOSED" : status,
    detail,
    localTime: `${timeStr(d)} IST`,
    dotColor: status === "OPEN" ? TV.up : status === "PRE" ? TV.warn : TV.muted,
  };
}

function usStatus(): MarketInfo {
  const d   = nowIn("America/New_York");
  const day = d.getDay();
  const min = d.getHours() * 60 + d.getMinutes();
  const PRE_M = 4 * 60, OPEN_M = 9 * 60 + 30, CLOSE_M = 16 * 60, AFTER_M = 20 * 60;
  let status: MarketStatus, detail: string;

  if (day === 0 || day === 6) {
    status = "WEEKEND";
    detail = `opens Mon 09:30 ET`;
  } else if (min >= PRE_M && min < OPEN_M) {
    status = "PRE";
    detail = `opens in ${fmtCountdown(OPEN_M - min)}`;
  } else if (min >= OPEN_M && min < CLOSE_M) {
    status = "OPEN";
    detail = `closes in ${fmtCountdown(CLOSE_M - min)}`;
  } else if (min >= CLOSE_M && min < AFTER_M) {
    status = "AFTER";
    detail = "after-hours";
  } else {
    status = "CLOSED";
    const next = OPEN_M + (day === 5 ? 3 * 1440 : 1440) - min;
    detail = `opens in ${fmtCountdown(next)}`;
  }

  return {
    label: "🇺🇸 US NYSE",
    status,
    statusLabel: status,
    detail,
    localTime: `${timeStr(d)} ET`,
    dotColor: status === "OPEN" ? TV.up : (status === "PRE" || status === "AFTER") ? TV.warn : TV.muted,
  };
}

function cryptoInfo(btcLtp: number | null): MarketInfo {
  const d = nowIn("UTC");
  const btcStr = btcLtp
    ? btcLtp.toLocaleString("en-US", { maximumFractionDigits: 0 })
    : "—";
  return {
    label: "₿ Crypto 24/7",
    status: "OPEN",
    statusLabel: "24/7",
    detail: btcLtp ? `BTC ${btcStr}` : "connecting…",
    localTime: `${timeStr(d)} UTC`,
    dotColor: TV.up,
  };
}

function StatusCard({ info }: { info: MarketInfo }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "4px 16px", borderRight: `1px solid ${TV.border}`,
      minWidth: 210,
    }}>
      <span style={{
        width: 8, height: 8, borderRadius: "50%",
        background: info.dotColor, flexShrink: 0, display: "inline-block",
      }} />
      <div>
        <div style={{ display: "flex", gap: 7, alignItems: "center" }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: TV.text }}>{info.label}</span>
          <span style={{
            fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 3,
            background: info.dotColor + "22", color: info.dotColor,
          }}>
            {info.statusLabel}
          </span>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 1 }}>
          <span style={{ fontSize: 10, color: TV.muted }}>{info.detail}</span>
          <span style={{ fontSize: 10, color: "#363c4e" }}>{info.localTime}</span>
        </div>
      </div>
    </div>
  );
}

export default function MarketStatusBar() {
  const btcLtp = useLiveQuotesStore((s) => s.quotes["CRYPTO:BTC"]?.ltp ?? null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  // Auto-subscribe to BTC so we always have a price for the status bar
  useEffect(() => {
    marketWs.subscribe(["CRYPTO:BTC"]);
    return () => { marketWs.unsubscribe(["CRYPTO:BTC"]); };
  }, []);

  void tick; // trigger recompute on interval

  const markets: MarketInfo[] = [indiaStatus(), usStatus(), cryptoInfo(btcLtp)];

  return (
    <div style={{
      display: "flex", background: TV.bg,
      borderBottom: `1px solid ${TV.border}`,
      overflowX: "auto", flexShrink: 0,
    }}>
      {markets.map((m) => <StatusCard key={m.label} info={m} />)}
    </div>
  );
}
