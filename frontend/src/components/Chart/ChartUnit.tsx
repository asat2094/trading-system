/**
 * ChartUnit — unified standalone chart component used everywhere in the system.
 *
 * When paneId is provided: reads/writes indicators from the Zustand dashboard store.
 * When paneId is omitted: indicators are local state (not persisted), suitable for
 * modals and one-off chart views (FnO chart modal, etc.).
 */
import { useState, useCallback, useRef, useEffect } from "react";
import { useDashboardStore, makeDefaultIndicator } from "../../store/dashboard";
import type { IndicatorConfig, IndicatorType } from "../../store/dashboard";
import { useLiveQuotesStore } from "../../store/liveQuotes";
import { apiClient } from "../../api/client";
import CandlestickChart from "./CandlestickChart";
import type { ChartHandle } from "./CandlestickChart";
import type { Bar } from "./indicators";
import { calcEMA, calcSMA, calcBB, calcVWAPBands, calcPivots, getSourceValues } from "./indicators";
import type { StudyConfig } from "./types";
import { STUDY_DEFAULTS } from "./types";
import type { UTCTimestamp } from "lightweight-charts";
import { tsToUnix } from "../../lib/time";
import DrawingDrawer from "../Dashboard/DrawingToolbar";
import type { DrawMode, Drawing } from "../Dashboard/DrawingToolbar";
import IndicatorPanel from "../Dashboard/IndicatorPanel";
import TickerBar from "../Dashboard/TickerBar";
import * as marketWs from "../../lib/marketWs";

// ── Constants ─────────────────────────────────────────────────────────────────
const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0];
const FIB_COLORS = ["#ef5350", "#f59e0b", "#26a69a", "#2196f3", "#26a69a", "#f59e0b", "#ef5350"];
const uid = () => Math.random().toString(36).slice(2, 10);

const TV = { bg: "#131722", border: "#2a2e39", muted: "#787b86" } as const;

const CLICKS_NEEDED: Partial<Record<DrawMode, number>> = {
  hline: 1, trendline: 2, fibonacci: 2, long_position: 3, short_position: 3,
};

export const TF_MS: Record<string, number> = {
  "1min": 60_000, "3min": 180_000, "5min": 300_000, "15min": 900_000,
  "30min": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "1w": 604_800_000,
};

export const TF_DAYS: Record<string, number> = {
  "1min": 3, "5min": 7, "15min": 14, "30min": 21,
  "1h": 60, "4h": 120, "1d": 90, "1w": 365,
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function candleFloor(tsMs: number, tf: string): number {
  return Math.floor(tsMs / (TF_MS[tf] ?? TF_MS["5min"])) * (TF_MS[tf] ?? TF_MS["5min"]);
}

function msToTs(ms: number): string {
  return new Date(ms).toISOString().replace("Z", "").replace(/\.\d{3}$/, "");
}

function isMarketOpen(symbol: string): boolean {
  if (symbol.startsWith("CRYPTO:")) return true;
  const ist = new Date(Date.now() + 5.5 * 3_600_000);
  const day = ist.getUTCDay();
  if (day === 0 || day === 6) return false;
  const mins = ist.getUTCHours() * 60 + ist.getUTCMinutes();
  return mins >= 9 * 60 + 15 && mins < 15 * 60 + 30;
}

function contrastText(hex: string): string {
  try {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.55 ? "#131722" : "#fff";
  } catch { return "#fff"; }
}

function toStudyConfig(ind: IndicatorConfig): StudyConfig | null {
  if (!ind.visible) return null;
  const defaults = STUDY_DEFAULTS[ind.type as keyof typeof STUDY_DEFAULTS];
  if (!defaults) return null;
  const merged = { id: ind.id, ...defaults };
  for (const [k, v] of Object.entries(ind.inputs)) (merged as Record<string, unknown>)[k] = v;
  for (const [k, v] of Object.entries(ind.style))  (merged as Record<string, unknown>)[k] = v;
  return merged as StudyConfig;
}

const _EMPTY: IndicatorConfig[] = [];  // stable ref — prevents infinite loop in useDashboardStore selector

// ── Props ─────────────────────────────────────────────────────────────────────
export interface ChartUnitProps {
  symbol:    string;
  timeframe: string;
  paneId?:   string;   // if provided: indicators synced to dashboard store
  focused?:  boolean;
  onFocus?:  () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function ChartUnit({ symbol, timeframe, paneId, focused, onFocus }: ChartUnitProps) {
  // Store indicators (when paneId given) vs local indicators
  const storeIndicators = useDashboardStore(
    (s) => paneId ? (s.panes.find((p) => p.id === paneId)?.indicators ?? _EMPTY) : _EMPTY
  );
  const [localIndicators, setLocalIndicators] = useState<IndicatorConfig[]>([]);
  const indicators = paneId ? storeIndicators : localIndicators;

  // Local handlers for standalone (no paneId) mode
  const localHandlers = paneId ? undefined : {
    onAdd:    (type: IndicatorType) => setLocalIndicators((p) => [...p, makeDefaultIndicator(type)]),
    onRemove: (id: string)          => setLocalIndicators((p) => p.filter((i) => i.id !== id)),
    onUpdate: (ind: IndicatorConfig) => setLocalIndicators((p) => p.map((i) => i.id === ind.id ? ind : i)),
  };

  const [bars, setBars]           = useState<Bar[]>([]);
  const [liveBar, setLiveBar]     = useState<Bar | null>(null);
  const [loading, setLoading]     = useState(false);
  const [fitKey, setFitKey]       = useState(0);
  const [panelOpen, setPanelOpen] = useState(false);
  const [priceLabel, setPriceLabel] = useState<{
    price: number; countdown: string; y: number; isUp: boolean;
  } | null>(null);

  const chartRef  = useRef<ChartHandle>(null);
  const barsRef   = useRef<Bar[]>([]);

  // Drawing state
  const [drawMode, setDrawMode]       = useState<DrawMode>("cursor");
  const [drawings, setDrawings]       = useState<Drawing[]>([]);
  const [renderTick, setRenderTick]   = useState(0);
  const pendingClicks                 = useRef<Array<{ t: UTCTimestamp; p: number }>>([]);
  const [pendingClicksState, setPendingClicksState] = useState<Array<{ t: UTCTimestamp; p: number }>>([]);

  const studies: StudyConfig[] = indicators.map(toStudyConfig).filter((s): s is StudyConfig => s !== null);

  // ── Data loading ─────────────────────────────────────────────────────────────
  const loadBars = useCallback(async (sym: string, tf: string, fromDt: string, toDt: string): Promise<Bar[]> => {
    const isExchange = sym.startsWith("NSE:") || sym.startsWith("BSE:") || sym.startsWith("NFO:") || sym.startsWith("BFO:");
    if (isExchange) {
      const { data } = await apiClient.get("/technical/candles", { params: { symbol: sym, tf, from_dt: fromDt, to_dt: toDt } });
      return (data.rows ?? []) as Bar[];
    }
    const { data } = await apiClient.get("/market/ohlcv", { params: { symbol: sym, tf, from_dt: fromDt, to_dt: toDt } });
    return (data.rows ?? []) as Bar[];
  }, []);

  const loadInitial = useCallback(async () => {
    setLoading(true); setBars([]); setLiveBar(null); barsRef.current = [];
    try {
      const days   = TF_DAYS[timeframe] ?? 30;
      const toDt   = new Date().toISOString().slice(0, 19) + "Z";
      const fromDt = new Date(Date.now() - days * 86400_000).toISOString().slice(0, 19) + "Z";
      const fetched = await loadBars(symbol, timeframe, fromDt, toDt);
      barsRef.current = fetched;
      setBars(fetched);
      setFitKey((k) => k + 1);
    } catch (err) { console.error("ChartUnit loadInitial", err); }
    finally { setLoading(false); }
  }, [symbol, timeframe, loadBars]);

  const handleNeedMoreData = useCallback(async () => {
    if (bars.length === 0) return;
    try {
      const days   = TF_DAYS[timeframe] ?? 30;
      const fromDt = new Date(new Date(bars[0].ts).getTime() - days * 86400_000).toISOString().slice(0, 19) + "Z";
      const older  = await loadBars(symbol, timeframe, fromDt, bars[0].ts);
      if (older.length > 0) { const m = [...older, ...bars]; barsRef.current = m; setBars(m); }
    } catch (err) { console.error("ChartUnit needMoreData", err); }
  }, [bars, symbol, timeframe, loadBars]);

  useEffect(() => { void loadInitial(); }, [loadInitial]);

  // ── WebSocket subscription ────────────────────────────────────────────────
  useEffect(() => {
    marketWs.subscribe([symbol]);
    return () => marketWs.unsubscribe([symbol]);
  }, [symbol]);

  // ── Live tick update ──────────────────────────────────────────────────────
  useEffect(() => {
    const tfOffsetSec = (TF_MS[timeframe] ?? 0) / 1000;
    return useLiveQuotesStore.subscribe((state) => {
      const q = state.quotes[symbol];
      if (!q) return;
      const cs = chartRef.current?.candleSeries;
      const vs = chartRef.current?.volumeSeries;
      if (!cs || barsRef.current.length === 0) return;
      const last              = barsRef.current[barsRef.current.length - 1];
      const lastOpenTime      = tsToUnix(last.ts);
      const lastDisplayTime   = (lastOpenTime + tfOffsetSec) as UTCTimestamp;
      const candleStartSec    = Math.floor(candleFloor(new Date(q.ts).getTime(), timeframe) / 1000);
      try {
        if (candleStartSec === lastOpenTime) {
          const u: Bar = { ...last, high: Math.max(last.high, q.ltp), low: Math.min(last.low, q.ltp), close: q.ltp, volume: last.volume + q.volume };
          barsRef.current[barsRef.current.length - 1] = u; setLiveBar(u);
          cs.update({ time: lastDisplayTime, open: u.open, high: u.high, low: u.low, close: u.close });
          vs?.update({ time: lastDisplayTime, value: u.volume, color: u.close >= u.open ? "#26a69a66" : "#ef535066" });
        } else if (candleStartSec > lastOpenTime) {
          const dt = (candleStartSec + tfOffsetSec) as UTCTimestamp;
          const nb: Bar = { ts: msToTs(candleStartSec * 1000), open: q.ltp, high: q.ltp, low: q.ltp, close: q.ltp, volume: q.volume };
          barsRef.current.push(nb); setLiveBar(nb);
          cs.update({ time: dt, open: q.ltp, high: q.ltp, low: q.ltp, close: q.ltp });
          vs?.update({ time: dt, value: q.volume, color: "#26a69a66" });
        }
      } catch { /* ignore */ }
    });
  }, [symbol, timeframe]);

  // ── Price + countdown label ───────────────────────────────────────────────
  useEffect(() => {
    const step = TF_MS[timeframe] ?? 0;
    const tick = () => {
      const cs = chartRef.current?.candleSeries;
      const last = barsRef.current[barsRef.current.length - 1];
      if (!cs || !last) return;
      const y = cs.priceToCoordinate(last.close);
      if (y == null) return;
      let cd = "";
      if (step && isMarketOpen(symbol)) {
        const rem = step - (Date.now() % step), tot = Math.floor(rem / 1000);
        const h = Math.floor(tot / 3600), m = Math.floor((tot % 3600) / 60), s = tot % 60;
        cd = h > 0 ? `${h}:${m.toString().padStart(2,"0")}:${s.toString().padStart(2,"0")}` : `${m.toString().padStart(2,"0")}:${s.toString().padStart(2,"0")}`;
      }
      setPriceLabel({ price: last.close, countdown: cd, y, isUp: last.close >= last.open });
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => { clearInterval(id); setPriceLabel(null); };
  }, [timeframe, symbol]);

  // ── Drawing helpers ───────────────────────────────────────────────────────
  useEffect(() => { pendingClicks.current = []; setPendingClicksState([]); }, [drawMode]);

  const handleSvgClick = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (drawMode === "cursor") return;
    const chart = chartRef.current?.chart, cs = chartRef.current?.candleSeries;
    if (!chart || !cs) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const t = chart.timeScale().coordinateToTime(e.clientX - rect.left) as UTCTimestamp | null;
    const p = cs.coordinateToPrice(e.clientY - rect.top);
    if (t == null || p == null) return;
    if (drawMode === "hline") { setDrawings((prev) => [...prev, { id: uid(), type: "hline", price: p, color: "#f7c948" }]); return; }
    const clicks = pendingClicks.current;
    clicks.push({ t, p }); setPendingClicksState([...clicks]);
    if (clicks.length < (CLICKS_NEEDED[drawMode] ?? 2)) return;
    const pts = clicks.splice(0); setPendingClicksState([]);
    if (drawMode === "trendline")      setDrawings((prev) => [...prev, { id: uid(), type: "trendline",      t1: pts[0].t, p1: pts[0].p, t2: pts[1].t, p2: pts[1].p, color: "#2962ff" }]);
    else if (drawMode === "fibonacci") setDrawings((prev) => [...prev, { id: uid(), type: "fibonacci",      t1: pts[0].t, p1: pts[0].p, t2: pts[1].t, p2: pts[1].p }]);
    else if (drawMode === "long_position")  setDrawings((prev) => [...prev, { id: uid(), type: "long_position",  t: pts[0].t, entry: pts[0].p, target: pts[1].p, stop: pts[2].p }]);
    else if (drawMode === "short_position") setDrawings((prev) => [...prev, { id: uid(), type: "short_position", t: pts[0].t, entry: pts[0].p, target: pts[1].p, stop: pts[2].p }]);
  }, [drawMode]);

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div
      style={{
        display: "flex", flexDirection: "column", flex: 1, minHeight: 0,
        border: focused ? `2px solid #2962ff` : `1px solid ${TV.border}`,
        boxSizing: "border-box", background: TV.bg, overflow: "hidden", position: "relative",
      }}
      onClick={onFocus}
    >
      {/* Ticker bar — symbol, OHLCV, live flash, ⊕ indicator toggle */}
      <TickerBar
        symbol={symbol}
        timeframe={timeframe}
        lastBar={liveBar ?? (bars.length > 0 ? bars[bars.length - 1] : null)}
        onOpenIndicators={() => setPanelOpen((v) => !v)}
      />

      {/* Content: drawing drawer + chart */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden", minHeight: 0 }}>
        <DrawingDrawer
          mode={drawMode} onMode={setDrawMode}
          drawings={drawings}
          onClearAll={() => setDrawings([])}
          onRemoveDrawing={(id) => setDrawings((prev) => prev.filter((d) => d.id !== id))}
          pendingClicks={pendingClicksState.length}
        />

        {/* Chart area */}
        <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
          {loading && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "#13172288", zIndex: 10 }}>
              <span style={{ color: TV.muted, fontSize: 12 }}>Loading…</span>
            </div>
          )}
          {!loading && bars.length === 0 && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <span style={{ color: TV.muted, fontSize: 12 }}>No data for {symbol}</span>
            </div>
          )}
          {bars.length > 0 && (
            <CandlestickChart
              ref={chartRef} bars={bars} studies={studies}
              onNeedMoreData={handleNeedMoreData}
              tfOffsetSec={(TF_MS[timeframe] ?? 0) / 1000}
              onVisibleRangeChange={() => setRenderTick((t) => t + 1)}
              fitKey={fitKey}
            />
          )}

          {/* Drawing SVG overlay */}
          {(() => {
            const chart = chartRef.current?.chart, cs = chartRef.current?.candleSeries;
            void renderTick;
            if (!chart || !cs || bars.length === 0) return null;
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const scaleW: number = (chart as any).priceScale?.("right")?.width?.() ?? 65;
            const toX = (t: UTCTimestamp) => chart.timeScale().timeToCoordinate(t) ?? -9999;
            const toY = (price: number) => cs.priceToCoordinate(price) ?? -9999;
            return (
              <svg
                style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: drawMode === "cursor" ? "none" : "all", cursor: drawMode !== "cursor" ? "crosshair" : "default", zIndex: 5 }}
                onClick={drawMode !== "cursor" ? handleSvgClick : undefined}
              >
                {drawings.map((d) => {
                  if (d.type === "hline") {
                    const y = toY(d.price);
                    return <g key={d.id}><line x1={0} y1={y} x2={`calc(100% - ${scaleW}px)`} y2={y} stroke={d.color} strokeWidth={1} strokeDasharray="5 3" /><text x={4} y={y - 3} fill={d.color} fontSize={9} fontFamily="monospace">{d.price.toFixed(2)}</text></g>;
                  }
                  if (d.type === "trendline") return <line key={d.id} x1={toX(d.t1)} y1={toY(d.p1)} x2={toX(d.t2)} y2={toY(d.p2)} stroke={d.color} strokeWidth={1.5} strokeLinecap="round" />;
                  if (d.type === "fibonacci") {
                    const hi = Math.max(d.p1, d.p2), lo = Math.min(d.p1, d.p2), range = hi - lo;
                    return <g key={d.id}>{FIB_LEVELS.map((lvl, i) => { const price = hi - lvl * range, y = toY(price); return <g key={lvl}><line x1={0} y1={y} x2={`calc(100% - ${scaleW}px)`} y2={y} stroke={FIB_COLORS[i]} strokeWidth={1} opacity={0.85} /><text x={4} y={y - 3} fill={FIB_COLORS[i]} fontSize={9} fontFamily="monospace">{(lvl*100).toFixed(1)}% {price.toFixed(2)}</text></g>; })}</g>;
                  }
                  if (d.type === "long_position" || d.type === "short_position") {
                    const isLong = d.type === "long_position";
                    const eY = toY(d.entry), tY = toY(d.target), sY = toY(d.stop), x = toX(d.t), W = 130;
                    const pClr = isLong ? "#26a69a" : "#ef5350", lClr = isLong ? "#ef5350" : "#26a69a";
                    const rr = Math.abs(tY - eY) > 0 ? (Math.abs(sY - eY) / Math.abs(tY - eY)).toFixed(2) : "—";
                    return <g key={d.id}>
                      <rect x={x} y={Math.min(eY, tY)} width={W} height={Math.abs(tY - eY)} fill={pClr} opacity={0.18} />
                      <rect x={x} y={Math.min(eY, sY)} width={W} height={Math.abs(sY - eY)} fill={lClr} opacity={0.18} />
                      <line x1={x} y1={eY} x2={x+W} y2={eY} stroke="#2962ff" strokeWidth={1.5} />
                      <line x1={x} y1={tY} x2={x+W} y2={tY} stroke={pClr} strokeWidth={1} strokeDasharray="4 2" />
                      <line x1={x} y1={sY} x2={x+W} y2={sY} stroke={lClr} strokeWidth={1} strokeDasharray="4 2" />
                      <text x={x+4} y={Math.min(eY,tY)-3} fill={pClr} fontSize={9} fontFamily="monospace">TP {d.target.toFixed(2)}</text>
                      <text x={x+4} y={eY-3} fill="#a0aec0" fontSize={9} fontFamily="monospace">E {d.entry.toFixed(2)}</text>
                      <text x={x+4} y={Math.max(eY,sY)+10} fill={lClr} fontSize={9} fontFamily="monospace">SL {d.stop.toFixed(2)} · R/R {rr}</text>
                    </g>;
                  }
                  return null;
                })}
                {/* Pivot lines */}
                {indicators.filter(ind => ind.visible && ind.type === "Pivot").map(ind => {
                  const sty = ind.style as Record<string, string>;
                  const pivots = calcPivots(
                    [...bars].sort((a,b) => tsToUnix(a.ts) - tsToUnix(b.ts)),
                    String(ind.inputs.pivotType ?? "standard"),
                    String(ind.inputs.period ?? "daily")
                  );
                  if (!pivots) return null;
                  const levels: [string, number, string, string][] = [
                    ["pp", pivots.pp, sty.ppColor ?? "#2196f3", "PP"],
                    ["r1", pivots.r1, sty.rColor ?? "#26a69a", "R1"],
                    ["r2", pivots.r2, sty.rColor ?? "#26a69a", "R2"],
                    ["r3", pivots.r3, sty.rColor ?? "#26a69a", "R3"],
                    ["s1", pivots.s1, sty.sColor ?? "#ef5350", "S1"],
                    ["s2", pivots.s2, sty.sColor ?? "#ef5350", "S2"],
                    ["s3", pivots.s3, sty.sColor ?? "#ef5350", "S3"],
                    ...(pivots.r4 != null ? [["r4", pivots.r4, sty.rColor ?? "#26a69a", "R4"] as [string,number,string,string]] : []),
                    ...(pivots.s4 != null ? [["s4", pivots.s4, sty.sColor ?? "#ef5350", "S4"] as [string,number,string,string]] : []),
                  ];
                  return <g key={ind.id}>{levels.map(([sfx, val, color, tag]) => {
                    const y = toY(val); if (y < -100 || y > 9999) return null;
                    return <g key={sfx}>
                      <line x1={0} y1={y} x2={`calc(100% - ${scaleW}px)`} y2={y} stroke={color} strokeWidth={1} strokeDasharray={sfx === "pp" ? "none" : "6 3"} opacity={0.85} />
                      <text x={6} y={y - 3} fill={color} fontSize={9} fontFamily="monospace" fontWeight={sfx === "pp" ? 700 : 400}>{tag} {val.toFixed(2)}</text>
                    </g>;
                  })}</g>;
                })}

                {/* VWAP bands in SVG */}
                {indicators.filter(ind => ind.visible && ind.type === "VWAP" && ind.inputs.showBands).map(ind => {
                  const sty = ind.style as Record<string, string>;
                  const sorted2 = [...bars].sort((a,b) => tsToUnix(a.ts) - tsToUnix(b.ts));
                  const bands = calcVWAPBands(sorted2);
                  const vwapBandLines: [string, number[], string][] = [
                    ["u1", bands.upper1, sty.band1Color ?? "#ff980066"],
                    ["l1", bands.lower1, sty.band1Color ?? "#ff980066"],
                    ["u2", bands.upper2, sty.band2Color ?? "#ff980044"],
                    ["l2", bands.lower2, sty.band2Color ?? "#ff980044"],
                    ["u3", bands.upper3, sty.band3Color ?? "#ff980022"],
                    ["l3", bands.lower3, sty.band3Color ?? "#ff980022"],
                  ];
                  return <g key={ind.id}>{vwapBandLines.map(([sfx, arr]) => {
                    const last = arr[arr.length-1]; if (!last || isNaN(last)) return null;
                    const y = toY(last);
                    const color = vwapBandLines.find(([s]) => s === sfx)?.[2] ?? "#ff980044";
                    return <line key={sfx} x1={0} y1={y} x2={`calc(100% - ${scaleW}px)`} y2={y} stroke={color} strokeWidth={1} strokeDasharray="3 3" opacity={0.7} />;
                  })}</g>;
                })}

                {pendingClicksState.map((pt, i) => {
                  const cx = toX(pt.t), cy = toY(pt.p);
                  return <g key={i}><circle cx={cx} cy={cy} r={4} fill="#f7c948" opacity={0.8} /><circle cx={cx} cy={cy} r={4} fill="none" stroke="#f7c948" strokeWidth={1} /></g>;
                })}
              </svg>
            );
          })()}

          {/* Y-axis price + indicator labels */}
          {bars.length > 0 && (() => {
            const chart = chartRef.current?.chart, cs = chartRef.current?.candleSeries;
            if (!chart || !cs) return null;
            void renderTick;
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const sw: number = (chart as any).priceScale?.("right")?.width?.() ?? 65;
            interface YLabel { id: string; y: number; value: number; color: string; tag?: string; isPrice?: boolean; countdown?: string; }
            const labels: YLabel[] = [];
            if (priceLabel) {
              const y = cs.priceToCoordinate(priceLabel.price);
              if (y != null) labels.push({ id: "__price__", y, value: priceLabel.price, color: priceLabel.isUp ? "#26a69a" : "#ef5350", isPrice: true, countdown: priceLabel.countdown || undefined });
            }
            const sorted = [...bars].sort((a, b) => tsToUnix(a.ts) - tsToUnix(b.ts));
            const closes = sorted.map(b => b.close);
            for (const ind of indicators) {
              if (!ind.visible) continue;
              const sty = ind.style as Record<string, string>;
              if (ind.type === "EMA") {
                const src = getSourceValues(sorted, String(ind.inputs.source ?? "close"));
                const vals = calcEMA(src, Number(ind.inputs.period)), last = vals[vals.length-1];
                if (!isNaN(last)) { const y = cs.priceToCoordinate(last); if (y != null) labels.push({ id: ind.id, y, value: last, color: sty.color ?? "#f7c948" }); }
              } else if (ind.type === "SMA") {
                const src = getSourceValues(sorted, String(ind.inputs.source ?? "close"));
                const vals = calcSMA(src, Number(ind.inputs.period)), last = vals[vals.length-1];
                if (!isNaN(last)) { const y = cs.priceToCoordinate(last); if (y != null) labels.push({ id: ind.id, y, value: last, color: sty.color ?? "#4caf50" }); }
              } else if (ind.type === "VWAP") {
                const bands = calcVWAPBands(sorted);
                const last = bands.vwap[bands.vwap.length-1];
                if (!isNaN(last)) { const y = cs.priceToCoordinate(last); if (y != null) labels.push({ id: ind.id, y, value: last, color: sty.color ?? "#ff9800" }); }
                if (ind.inputs.showBands) {
                  const bandPairs: [string, number[], string, string][] = [
                    [`${ind.id}-u1`, bands.upper1, sty.band1Color ?? "#ff980066", "+1σ"],
                    [`${ind.id}-l1`, bands.lower1, sty.band1Color ?? "#ff980066", "-1σ"],
                    [`${ind.id}-u2`, bands.upper2, sty.band2Color ?? "#ff980044", "+2σ"],
                    [`${ind.id}-l2`, bands.lower2, sty.band2Color ?? "#ff980044", "-2σ"],
                    [`${ind.id}-u3`, bands.upper3, sty.band3Color ?? "#ff980022", "+3σ"],
                    [`${ind.id}-l3`, bands.lower3, sty.band3Color ?? "#ff980022", "-3σ"],
                  ];
                  for (const [id, arr, color] of bandPairs) {
                    const v = arr[arr.length-1]; if (!isNaN(v)) { const y = cs.priceToCoordinate(v); if (y != null) labels.push({ id, y, value: v, color }); }
                  }
                }
              } else if (ind.type === "BB") {
                const { upper, mid, lower } = calcBB(closes, Number(ind.inputs.period), Number(ind.inputs.std));
                for (const [sfx, arr, ck] of [["u",upper,"upperColor"],["m",mid,"midColor"],["l",lower,"lowerColor"]] as [string,number[],string][]) {
                  const last = arr[arr.length-1]; if (!isNaN(last)) { const y = cs.priceToCoordinate(last); if (y != null) labels.push({ id: `${ind.id}-${sfx}`, y, value: last, color: sty[ck] ?? "#2196f3" }); }
                }
              } else if (ind.type === "Pivot") {
                const pivots = calcPivots(sorted, String(ind.inputs.pivotType ?? "standard"), String(ind.inputs.period ?? "daily"));
                if (pivots) {
                  const levels: [string, number, string, string][] = [
                    ["pp", pivots.pp, sty.ppColor ?? "#2196f3", "PP"],
                    ["r1", pivots.r1, sty.rColor ?? "#26a69a", "R1"],
                    ["r2", pivots.r2, sty.rColor ?? "#26a69a", "R2"],
                    ["r3", pivots.r3, sty.rColor ?? "#26a69a", "R3"],
                    ["s1", pivots.s1, sty.sColor ?? "#ef5350", "S1"],
                    ["s2", pivots.s2, sty.sColor ?? "#ef5350", "S2"],
                    ["s3", pivots.s3, sty.sColor ?? "#ef5350", "S3"],
                    ...(pivots.r4 != null ? [["r4", pivots.r4, sty.rColor ?? "#26a69a", "R4"] as [string,number,string,string]] : []),
                    ...(pivots.s4 != null ? [["s4", pivots.s4, sty.sColor ?? "#ef5350", "S4"] as [string,number,string,string]] : []),
                  ];
                  for (const [sfx, val, color, tag] of levels) {
                    const y = cs.priceToCoordinate(val); if (y != null) labels.push({ id: `${ind.id}-${sfx}`, y, value: val, color, tag });
                  }
                }
              }
            }
            labels.sort((a, b) => a.y - b.y);
            const LH = 16;
            for (let i = 1; i < labels.length; i++) {
              const ph = labels[i-1].isPrice && labels[i-1].countdown ? 32 : LH;
              const gap = (labels[i-1].y + ph/2) - (labels[i].y - (labels[i].isPrice && labels[i].countdown ? 32 : LH)/2);
              if (gap > 0) labels[i].y += gap;
            }
            return <>{labels.map((l) => {
              const h = l.isPrice && l.countdown ? 32 : LH;
              return <div key={l.id} style={{ position: "absolute", top: Math.round(l.y) - h/2, right: 0, width: sw, height: h, background: l.color, color: contrastText(l.color), fontFamily: "monospace", fontWeight: l.isPrice ? 700 : 500, fontSize: 10, textAlign: "center", pointerEvents: "none", zIndex: 20, userSelect: "none", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
                {l.tag ? <span style={{ fontSize: 9, lineHeight: "14px", opacity: 0.9 }}>{l.tag}</span> : null}
                <span style={{ fontSize: l.isPrice ? 11 : 10, lineHeight: "14px" }}>{l.value.toFixed(2)}</span>
                {l.countdown && <span style={{ fontSize: 10, lineHeight: "14px", opacity: 0.92 }}>{l.countdown}</span>}
              </div>;
            })}</>;
          })()}
        </div>
      </div>

      {/* Per-chart indicator panel overlay */}
      {panelOpen && (
        <div style={{ position: "absolute", top: 0, right: 0, bottom: 0, width: 260, zIndex: 100, boxShadow: "-4px 0 16px rgba(0,0,0,0.6)", display: "flex", flexDirection: "column" }}>
          <IndicatorPanel
            paneId={paneId ?? "__local__"}
            indicators={indicators}
            onClose={() => setPanelOpen(false)}
            mode="individual"
            local={localHandlers}
          />
        </div>
      )}
    </div>
  );
}
