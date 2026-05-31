import { useState, useCallback, useRef, useEffect } from "react";
import { useDashboardStore } from "../../store/dashboard";
import type { IndicatorConfig } from "../../store/dashboard";
import { useLiveQuotesStore } from "../../store/liveQuotes";
import { apiClient } from "../../api/client";
import CandlestickChart from "../Chart/CandlestickChart";
import type { ChartHandle } from "../Chart/CandlestickChart";
import type { Bar } from "../Chart/indicators";
import { calcEMA, calcSMA, calcBB, calcVWAP } from "../Chart/indicators";
import type { StudyConfig } from "../Chart/types";
import { STUDY_DEFAULTS } from "../Chart/types";
import type { UTCTimestamp } from "lightweight-charts";
import { tsToUnix } from "../../lib/time";
import TickerBar from "./TickerBar";
import PaneControls from "./PaneControls";
import IndicatorPanel from "./IndicatorPanel";
import PaneClock from "./PaneClock";
import DrawingToolbar from "./DrawingToolbar";
import type { DrawMode } from "./DrawingToolbar";
import * as marketWs from "../../lib/marketWs";

// ── Drawing types ─────────────────────────────────────────────────────────────
type HLineD   = { id: string; type: "hline";     price: number; color: string };
type TrendD   = { id: string; type: "trendline"; t1: UTCTimestamp; p1: number; t2: UTCTimestamp; p2: number; color: string };
type FibD     = { id: string; type: "fibonacci"; t1: UTCTimestamp; p1: number; t2: UTCTimestamp; p2: number };
type Drawing  = HLineD | TrendD | FibD;

const FIB_LEVELS  = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0];
const FIB_COLORS  = ["#ef5350", "#f59e0b", "#26a69a", "#2196f3", "#26a69a", "#f59e0b", "#ef5350"];
const uid = () => Math.random().toString(36).slice(2, 10);

const TV = {
  bg: "#131722", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86",
  accent: "#2962ff",
} as const;

function isMarketOpen(symbol: string): boolean {
  if (symbol.startsWith("CRYPTO:")) return true;
  // NSE/BSE: Mon–Fri 09:15–15:30 IST
  const ist = new Date(Date.now() + 5.5 * 3_600_000);
  const day = ist.getUTCDay(); // 0=Sun, 6=Sat
  if (day === 0 || day === 6) return false;
  const mins = ist.getUTCHours() * 60 + ist.getUTCMinutes();
  return mins >= 9 * 60 + 15 && mins < 15 * 60 + 30;
}

const TF_DAYS: Record<string, number> = {
  "1min": 3, "5min": 7, "15min": 14, "30min": 21,
  "1h": 60, "4h": 120, "1d": 365, "1w": 730,
};

const TF_MS: Record<string, number> = {
  "1min": 60_000, "3min": 180_000, "5min": 300_000, "15min": 900_000,
  "30min": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "1w": 604_800_000,
};

function candleFloor(tsMs: number, tf: string): number {
  const step = TF_MS[tf] ?? TF_MS["5min"];
  return Math.floor(tsMs / step) * step;
}

function msToTs(ms: number): string {
  return new Date(ms).toISOString().replace("Z", "").replace(/\.\d{3}$/, "");
}

function toStudyConfig(ind: IndicatorConfig): StudyConfig | null {
  if (!ind.visible) return null;
  const defaults = STUDY_DEFAULTS[ind.type as keyof typeof STUDY_DEFAULTS];
  if (!defaults) return null;
  const merged = { id: ind.id, ...defaults };
  for (const [k, v] of Object.entries(ind.inputs))  (merged as Record<string, unknown>)[k] = v;
  for (const [k, v] of Object.entries(ind.style))   (merged as Record<string, unknown>)[k] = v;
  return merged as StudyConfig;
}

interface Props {
  paneId: string;
  focused: boolean;
  onFocus: () => void;
}

export default function ChartPane({ paneId, focused, onFocus }: Props) {
  const pane = useDashboardStore((s) => s.panes.find((p) => p.id === paneId));
  const [bars, setBars]         = useState<Bar[]>([]);
  const [liveBar, setLiveBar]   = useState<Bar | null>(null);
  const [loading, setLoading]   = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const chartRef   = useRef<ChartHandle>(null);
  const barsRef    = useRef<Bar[]>([]);
  const [priceLabel, setPriceLabel] = useState<{
    price: number; countdown: string; y: number; isUp: boolean;
  } | null>(null);

  // ── Drawing state ──────────────────────────────────────────────────────────
  const [drawMode, setDrawMode]   = useState<DrawMode>("cursor");
  const [drawings, setDrawings]   = useState<Drawing[]>([]);
  const [renderTick, setRenderTick] = useState(0);
  const pendingPt = useRef<{ t: UTCTimestamp; p: number } | null>(null);
  const [pendingPtState, setPendingPtState] = useState<{ t: UTCTimestamp; p: number } | null>(null);

  const symbol    = pane?.symbol    ?? "NSE:RELIANCE";
  const timeframe = pane?.timeframe ?? "15min";
  const indicators = pane?.indicators ?? [];

  const studies: StudyConfig[] = indicators
    .map(toStudyConfig)
    .filter((s): s is StudyConfig => s !== null);

  const loadBars = useCallback(async (
    sym: string, tf: string, fromDt: string, toDt: string
  ): Promise<Bar[]> => {
    const isExchange = sym.startsWith("NSE:") || sym.startsWith("BSE:");
    if (isExchange) {
      const ticker = sym.split(":")[1];
      const { data } = await apiClient.get(`/technical/ohlcv/${ticker}`, {
        params: { tf, from_dt: fromDt, to_dt: toDt },
      });
      return (data.rows ?? []) as Bar[];
    } else {
      const { data } = await apiClient.get("/market/ohlcv", {
        params: { symbol: sym, tf, from_dt: fromDt, to_dt: toDt },
      });
      return (data.rows ?? []) as Bar[];
    }
  }, []);

  const loadInitial = useCallback(async () => {
    setLoading(true);
    setBars([]);
    setLiveBar(null);
    barsRef.current = [];
    try {
      const days = TF_DAYS[timeframe] ?? 30;
      const toDt   = new Date().toISOString().slice(0, 19) + "Z";
      const fromDt = new Date(Date.now() - days * 86400_000).toISOString().slice(0, 19) + "Z";
      const fetched = await loadBars(symbol, timeframe, fromDt, toDt);
      barsRef.current = fetched;
      setBars(fetched);
    } catch (err) {
      console.error("ChartPane: loadInitial failed", err);
    } finally {
      setLoading(false);
    }
  }, [symbol, timeframe, loadBars]);

  const handleNeedMoreData = useCallback(async () => {
    if (bars.length === 0) return;
    try {
      const oldestTs = bars[0].ts;
      const toDt   = oldestTs;
      const days = TF_DAYS[timeframe] ?? 30;
      const fromDt = new Date(new Date(oldestTs).getTime() - days * 86400_000).toISOString().slice(0, 19) + "Z";
      const older = await loadBars(symbol, timeframe, fromDt, toDt);
      if (older.length > 0) {
        const merged = [...older, ...bars];
        barsRef.current = merged;
        setBars(merged);
      }
    } catch (err) {
      console.error("ChartPane: handleNeedMoreData failed", err);
    }
  }, [bars, symbol, timeframe, loadBars]);

  // Load bars on symbol/timeframe change
  useEffect(() => {
    void loadInitial();
  }, [loadInitial]);

  // Subscribe/unsubscribe from live feed
  useEffect(() => {
    marketWs.subscribe([symbol]);
    return () => {
      marketWs.unsubscribe([symbol]);
    };
  }, [symbol]);

  // Live ticks: update chart series directly via ref (bypass React re-render).
  // The chart stores CLOSE times (open-time + tfOffsetSec), so all update()
  // calls must use close time too — otherwise lightweight-charts rejects them.
  useEffect(() => {
    const tfOffsetSec = (TF_MS[timeframe] ?? 0) / 1000;

    const unsub = useLiveQuotesStore.subscribe((state) => {
      const q = state.quotes[symbol];
      if (!q) return;
      const cs = chartRef.current?.candleSeries;
      const vs = chartRef.current?.volumeSeries;
      if (!cs) return;

      const prevBars = barsRef.current;
      if (prevBars.length === 0) return;
      const last = prevBars[prevBars.length - 1];

      // lastBarOpenTime — used to match which candle this tick belongs to.
      // lastBarDisplayTime — close time stored in the chart (open + offset).
      const lastBarOpenTime = tsToUnix(last.ts);
      const lastBarDisplayTime = (lastBarOpenTime + tfOffsetSec) as UTCTimestamp;

      const tickMs = new Date(q.ts).getTime();
      const candleStartSec = Math.floor(candleFloor(tickMs, timeframe) / 1000); // open time

      try {
        if (candleStartSec === lastBarOpenTime) {
          // Same candle — update in place
          const updated: Bar = {
            ...last,
            high: Math.max(last.high, q.ltp),
            low: Math.min(last.low, q.ltp),
            close: q.ltp,
            volume: last.volume + q.volume,
          };
          prevBars[prevBars.length - 1] = updated;
          setLiveBar(updated);
          cs.update({
            time: lastBarDisplayTime,
            open: updated.open, high: updated.high,
            low: updated.low, close: updated.close,
          });
          if (vs) {
            vs.update({
              time: lastBarDisplayTime,
              value: updated.volume + q.volume,
              color: updated.close >= updated.open ? "#26a69a66" : "#ef535066",
            });
          }
        } else if (candleStartSec > lastBarOpenTime) {
          // New candle — append
          const newBarOpenTime = candleStartSec;
          const newBarDisplayTime = (newBarOpenTime + tfOffsetSec) as UTCTimestamp;
          const newBar: Bar = {
            ts: msToTs(newBarOpenTime * 1000), // stored as open time for future matching
            open: q.ltp, high: q.ltp, low: q.ltp, close: q.ltp,
            volume: q.volume,
          };
          prevBars.push(newBar);
          setLiveBar(newBar);
          cs.update({
            time: newBarDisplayTime,
            open: q.ltp, high: q.ltp, low: q.ltp, close: q.ltp,
          });
          if (vs) {
            vs.update({ time: newBarDisplayTime, value: q.volume, color: "#26a69a66" });
          }
        }
      } catch (err) {
        console.warn(`[live] ${symbol} update failed`, err);
      }
    });
    return unsub;
  }, [symbol, timeframe]);

  // Unified price+countdown label. Replaces lastValueVisible (disabled in
  // CandlestickChart) so both price and bar-close time appear in one box,
  // coloured green (up) or red (down) like the candle body.
  useEffect(() => {
    const step = TF_MS[timeframe] ?? 0;
    const tick = () => {
      const cs   = chartRef.current?.candleSeries;
      const last = barsRef.current[barsRef.current.length - 1];
      if (!cs || !last) return;
      const y = cs.priceToCoordinate(last.close);
      if (y == null) return;
      let cd = "";
      if (step && isMarketOpen(symbol)) {
        const rem = step - (Date.now() % step);
        const tot = Math.floor(rem / 1000);
        const h = Math.floor(tot / 3600);
        const m = Math.floor((tot % 3600) / 60);
        const s = tot % 60;
        cd = h > 0
          ? `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
          : `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
      }
      setPriceLabel({ price: last.close, countdown: cd, y, isUp: last.close >= last.open });
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => { clearInterval(id); setPriceLabel(null); };
  }, [timeframe]);

  // ── Drawing SVG click ──────────────────────────────────────────────────────
  const handleSvgClick = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (drawMode === "cursor") return;
    const chart = chartRef.current?.chart;
    const cs    = chartRef.current?.candleSeries;
    if (!chart || !cs) return;
    const rect  = e.currentTarget.getBoundingClientRect();
    const x     = e.clientX - rect.left;
    const y     = e.clientY - rect.top;
    const t     = chart.timeScale().coordinateToTime(x) as UTCTimestamp | null;
    const p     = cs.coordinateToPrice(y);
    if (t == null || p == null) return;

    if (drawMode === "hline") {
      setDrawings((prev) => [...prev, { id: uid(), type: "hline", price: p, color: "#f7c948" }]);
    } else {
      if (!pendingPt.current) {
        pendingPt.current = { t, p };
        setPendingPtState({ t, p });
      } else {
        const { t: t1, p: p1 } = pendingPt.current;
        pendingPt.current = null;
        setPendingPtState(null);
        if (drawMode === "trendline") {
          setDrawings((prev) => [...prev, { id: uid(), type: "trendline", t1, p1, t2: t, p2: p, color: "#2962ff" }]);
        } else {
          setDrawings((prev) => [...prev, { id: uid(), type: "fibonacci", t1, p1, t2: t, p2: p }]);
        }
      }
    }
  }, [drawMode]);

  // Re-render SVG when draw mode changes (clear pending)
  useEffect(() => {
    pendingPt.current = null;
    setPendingPtState(null);
  }, [drawMode]);

  const containerStyle: React.CSSProperties = {
    position: "relative",
    display: "flex",
    flexDirection: "column",
    height: "100%",
    border: focused ? `2px solid ${TV.accent}` : `1px solid ${TV.border}`,
    boxSizing: "border-box",
    background: TV.bg,
    overflow: "hidden",
  };

  return (
    <div style={containerStyle} onClick={onFocus}>
      {/* Header */}
      <div style={{
        padding: "3px 8px", background: "#1a1e2e", flexShrink: 0,
        display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6,
      }}>
        <PaneControls paneId={paneId} symbol={symbol} timeframe={timeframe} />
        <DrawingToolbar
          mode={drawMode}
          onMode={setDrawMode}
          hasDrawings={drawings.length > 0}
          onClearAll={() => setDrawings([])}
        />
        <PaneClock timeframe={timeframe} />
      </div>

      {/* Ticker bar */}
      <TickerBar
        symbol={symbol}
        timeframe={timeframe}
        lastBar={liveBar ?? (bars.length > 0 ? bars[bars.length - 1] : null)}
        onOpenIndicators={() => { onFocus(); setPanelOpen((v) => !v); }}
      />

      {/* Chart area */}
      <div style={{ flex: 1, overflow: "hidden", position: "relative", minHeight: 0 }} id={`chart-area-${paneId}`}>
        {loading && (
          <div style={{
            position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
            background: "#13172288", zIndex: 10,
          }}>
            <span style={{ color: TV.muted, fontSize: 12 }}>Loading…</span>
          </div>
        )}
        {!loading && bars.length === 0 && (
          <div style={{
            position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <span style={{ color: TV.muted, fontSize: 12 }}>No data for {symbol}</span>
          </div>
        )}
        {bars.length > 0 && (
          <CandlestickChart
            ref={chartRef}
            bars={bars}
            studies={studies}
            onNeedMoreData={handleNeedMoreData}
            tfOffsetSec={(TF_MS[timeframe] ?? 0) / 1000}
            onVisibleRangeChange={() => setRenderTick((t) => t + 1)}
          />
        )}

        {/* Drawing SVG overlay */}
        {(() => {
          const chart = chartRef.current?.chart;
          const cs    = chartRef.current?.candleSeries;
          void renderTick; // force re-eval on pan/zoom
          if (!chart || !cs || bars.length === 0) return null;
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const scaleW: number = (chart as any).priceScale?.("right")?.width?.() ?? 65;
          const toX = (t: UTCTimestamp) => chart.timeScale().timeToCoordinate(t) ?? -9999;
          const toY = (price: number) => cs.priceToCoordinate(price) ?? -9999;
          return (
            <svg
              style={{
                position: "absolute", inset: 0, width: "100%", height: "100%",
                pointerEvents: drawMode === "cursor" ? "none" : "all",
                cursor: drawMode !== "cursor" ? "crosshair" : "default",
                zIndex: 5,
              }}
              onClick={drawMode !== "cursor" ? handleSvgClick : undefined}
            >
              {/* Existing drawings */}
              {drawings.map((d) => {
                if (d.type === "hline") {
                  const y = toY(d.price);
                  return (
                    <g key={d.id}>
                      <line x1={0} y1={y} x2={`calc(100% - ${scaleW}px)`} y2={y}
                        stroke={d.color} strokeWidth={1} strokeDasharray="5 3" />
                      <text x={4} y={y - 3} fill={d.color} fontSize={9} fontFamily="monospace">
                        {d.price.toFixed(2)}
                      </text>
                    </g>
                  );
                }
                if (d.type === "trendline") {
                  return (
                    <line key={d.id}
                      x1={toX(d.t1)} y1={toY(d.p1)}
                      x2={toX(d.t2)} y2={toY(d.p2)}
                      stroke={d.color} strokeWidth={1.5} strokeLinecap="round" />
                  );
                }
                if (d.type === "fibonacci") {
                  const hi = Math.max(d.p1, d.p2);
                  const lo = Math.min(d.p1, d.p2);
                  const range = hi - lo;
                  return (
                    <g key={d.id}>
                      {FIB_LEVELS.map((lvl, i) => {
                        const price = hi - lvl * range;
                        const y = toY(price);
                        return (
                          <g key={lvl}>
                            <line x1={0} y1={y} x2={`calc(100% - ${scaleW}px)`} y2={y}
                              stroke={FIB_COLORS[i]} strokeWidth={1} opacity={0.85} />
                            <text x={4} y={y - 3} fill={FIB_COLORS[i]} fontSize={9} fontFamily="monospace">
                              {(lvl * 100).toFixed(1)}% &nbsp;{price.toFixed(2)}
                            </text>
                          </g>
                        );
                      })}
                    </g>
                  );
                }
                return null;
              })}

              {/* Pending first-click marker */}
              {pendingPtState && (() => {
                const cx = toX(pendingPtState.t);
                const cy = toY(pendingPtState.p);
                return (
                  <g>
                    <circle cx={cx} cy={cy} r={5} fill="#f7c948" opacity={0.8} />
                    <circle cx={cx} cy={cy} r={5} fill="none" stroke="#f7c948" strokeWidth={1} />
                  </g>
                );
              })()}
            </svg>
          );
        })()}

        {/* Unified Y-axis labels: current price (+ countdown) + indicator last values.
            All labels are stacked so they never overlap. */}
        {bars.length > 0 && (() => {
          const chart = chartRef.current?.chart;
          const cs    = chartRef.current?.candleSeries;
          if (!chart || !cs) return null;
          void renderTick; // recompute on pan / zoom
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const sw: number = (chart as any).priceScale?.("right")?.width?.() ?? 65;

          interface YLabel {
            id: string; y: number; value: number; color: string;
            isPrice?: boolean; countdown?: string;
          }
          const labels: YLabel[] = [];

          // ── Price label ───────────────────────────────────────────────────
          if (priceLabel) {
            const y = cs.priceToCoordinate(priceLabel.price);
            if (y != null) {
              labels.push({
                id: "__price__", y, value: priceLabel.price,
                color: priceLabel.isUp ? "#26a69a" : "#ef5350",
                isPrice: true, countdown: priceLabel.countdown || undefined,
              });
            }
          }

          // ── Indicator labels (overlays only) ──────────────────────────────
          const sorted = [...bars].sort((a, b) => tsToUnix(a.ts) - tsToUnix(b.ts));
          const closes = sorted.map(b => b.close);

          for (const ind of indicators) {
            if (!ind.visible) continue;
            const sty = ind.style as Record<string, string>;

            if (ind.type === "EMA") {
              const vals = calcEMA(closes, Number(ind.inputs.period));
              const last = vals[vals.length - 1];
              if (isNaN(last)) continue;
              const y = cs.priceToCoordinate(last);
              if (y == null) continue;
              labels.push({ id: ind.id, y, value: last, color: sty.color ?? "#f7c948" });

            } else if (ind.type === "SMA") {
              const vals = calcSMA(closes, Number(ind.inputs.period));
              const last = vals[vals.length - 1];
              if (isNaN(last)) continue;
              const y = cs.priceToCoordinate(last);
              if (y == null) continue;
              labels.push({ id: ind.id, y, value: last, color: sty.color ?? "#4caf50" });

            } else if (ind.type === "VWAP") {
              const vals = calcVWAP(sorted);
              const last = vals[vals.length - 1];
              if (isNaN(last)) continue;
              const y = cs.priceToCoordinate(last);
              if (y == null) continue;
              labels.push({ id: ind.id, y, value: last, color: sty.color ?? "#ff9800" });

            } else if (ind.type === "BB") {
              const { upper, mid, lower } = calcBB(
                closes, Number(ind.inputs.period), Number(ind.inputs.std)
              );
              for (const [sfx, arr, ck] of [
                ["u", upper, "upperColor"], ["m", mid, "midColor"], ["l", lower, "lowerColor"],
              ] as [string, number[], string][]) {
                const last = arr[arr.length - 1];
                if (isNaN(last)) continue;
                const y = cs.priceToCoordinate(last);
                if (y == null) continue;
                labels.push({ id: `${ind.id}-${sfx}`, y, value: last, color: sty[ck] ?? "#2196f3" });
              }
            }
          }

          // ── Stack: sort top→bottom, push overlapping labels down ──────────
          labels.sort((a, b) => a.y - b.y);
          const LABEL_H = 16;
          for (let i = 1; i < labels.length; i++) {
            const prevH = labels[i - 1].isPrice && labels[i - 1].countdown ? 32 : LABEL_H;
            const prevBottom = labels[i - 1].y + prevH / 2;
            const currH = labels[i].isPrice && labels[i].countdown ? 32 : LABEL_H;
            const gap = prevBottom - (labels[i].y - currH / 2);
            if (gap > 0) labels[i].y += gap;
          }

          return (
            <>
              {labels.map((l) => {
                const h = l.isPrice && l.countdown ? 32 : LABEL_H;
                return (
                  <div key={l.id} style={{
                    position: "absolute",
                    top: Math.round(l.y) - h / 2,
                    right: 0,
                    width: sw,
                    height: h,
                    background: l.color,
                    color: "#fff",
                    fontFamily: "monospace",
                    fontWeight: l.isPrice ? 700 : 500,
                    fontSize: 10,
                    textAlign: "center",
                    pointerEvents: "none",
                    zIndex: 20,
                    userSelect: "none",
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                  }}>
                    <span style={{ fontSize: l.isPrice ? 11 : 10, lineHeight: "16px" }}>
                      {l.value.toFixed(2)}
                    </span>
                    {l.countdown && (
                      <span style={{ fontSize: 10, lineHeight: "14px", opacity: 0.92 }}>
                        {l.countdown}
                      </span>
                    )}
                  </div>
                );
              })}
            </>
          );
        })()}
      </div>

      {/* Indicator panel */}
      {panelOpen && pane && (
        <IndicatorPanel
          paneId={paneId}
          indicators={pane.indicators}
          onClose={() => setPanelOpen(false)}
        />
      )}
    </div>
  );
}
