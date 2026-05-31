import { useEffect, useRef, useImperativeHandle, forwardRef } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  TickMarkType,
  type IChartApi,
  type UTCTimestamp,
  type LogicalRange,
} from "lightweight-charts";

// ---------------------------------------------------------------------------
// IST display helpers
// QuestDB stores UTC; add +05:30 before formatting so labels show IST.
// ---------------------------------------------------------------------------
const IST_OFFSET_MS = 5.5 * 3600 * 1000;
const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const pad2 = (n: number) => String(n).padStart(2, "0");

function istDate(unixSeconds: number): Date {
  return new Date(unixSeconds * 1000 + IST_OFFSET_MS);
}

// Axis tick labels (max 8 chars)
function istTickFormatter(time: UTCTimestamp, type: TickMarkType): string {
  const d = istDate(time as number);
  const H = pad2(d.getUTCHours()), M = pad2(d.getUTCMinutes());
  const day = pad2(d.getUTCDate()), mon = MONTHS[d.getUTCMonth()];
  const yr = d.getUTCFullYear();
  switch (type) {
    case TickMarkType.Year:          return String(yr);
    case TickMarkType.Month:         return `${mon} ${yr}`;
    case TickMarkType.DayOfMonth:    return `${day} ${mon}`;
    case TickMarkType.Time:          return `${H}:${M}`;
    case TickMarkType.TimeWithSeconds: return `${H}:${M}:${pad2(d.getUTCSeconds())}`;
    default:                         return `${day} ${mon}`;
  }
}

// Crosshair label — full IST datetime
function istCrosshairFormatter(time: UTCTimestamp): string {
  const d = istDate(time as number);
  return `${pad2(d.getUTCDate())} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}  ${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())} IST`;
}
import type { StudyConfig } from "./types";
import { OVERLAY_TYPES } from "./types";
import {
  type Bar,
  calcEMA, calcSMA, calcBB, calcVWAP, calcRSI, calcMACD, calcStoch,
} from "./indicators";
import { tsToUnix } from "../../lib/time";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnySeries = any;

export interface ChartHandle {
  candleSeries: AnySeries | null;
  volumeSeries: AnySeries | null;
  chart: IChartApi | null;
}


function filterNaN(
  bars: Bar[],
  values: number[],
  tfOffsetSec = 0,
): { time: UTCTimestamp; value: number }[] {
  return bars
    .map((b, i) => ({ time: (tsToUnix(b.ts) + tfOffsetSec) as UTCTimestamp, value: values[i] }))
    .filter(d => !isNaN(d.value));
}

interface Props {
  bars: Bar[];
  studies: StudyConfig[];
  onNeedMoreData?: () => void;
  /** Seconds to add to each bar's open-time so the chart axis shows candle CLOSE time. */
  tfOffsetSec?: number;
  /** Called whenever the visible time range changes (pan / zoom). Use to re-render drawing overlays. */
  onVisibleRangeChange?: () => void;
}

const CandlestickChart = forwardRef<ChartHandle, Props>(function CandlestickChart(
  { bars, studies, onNeedMoreData, tfOffsetSec = 0, onVisibleRangeChange },
  ref
) {
  const containerRef          = useRef<HTMLDivElement>(null);
  const chartRef              = useRef<IChartApi | null>(null);
  const onNeedMoreRef         = useRef(onNeedMoreData);
  const onVisibleRangeRef     = useRef(onVisibleRangeChange);
  const candleSeriesRef    = useRef<AnySeries>(null);
  const volumeSeriesRef    = useRef<AnySeries>(null);
  const didFitContent      = useRef(false);
  // studyId → array of series belonging to that study
  const studySeriesRef     = useRef<Map<string, AnySeries[]>>(new Map());

  useEffect(() => { onNeedMoreRef.current = onNeedMoreData; }, [onNeedMoreData]);
  useEffect(() => { onVisibleRangeRef.current = onVisibleRangeChange; }, [onVisibleRangeChange]);

  // ── Create chart once ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { color: "#131722" },
        textColor: "#787b86",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#1e222d" },
        horzLines: { color: "#1e222d" },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: "#2a2e39" },
      localization: {
        timeFormatter: istCrosshairFormatter,
        dateFormat: "dd MMM 'yy",
      },
      timeScale: {
        borderColor: "#2a2e39",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 5,
        tickMarkFormatter: istTickFormatter,
      },
    });
    chartRef.current = chart;

    // lastValueVisible: false — ChartPane renders a custom two-line overlay
    // (price + bar-close countdown) so we don't show the default label.
    candleSeriesRef.current = chart.addSeries(CandlestickSeries, {
      upColor: "#26a69a", downColor: "#ef5350",
      borderVisible: false,
      wickUpColor: "#26a69a", wickDownColor: "#ef5350",
      lastValueVisible: false,
    }, 0);

    // Volume overlay on main chart pane — separate price scale at bottom
    volumeSeriesRef.current = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    }, 0);
    chart.priceScale("vol").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    const ro = new ResizeObserver(() => {
      if (!didFitContent.current) chart.timeScale().fitContent();
    });
    ro.observe(containerRef.current!);

    const onRangeChange = (range: LogicalRange | null) => {
      if (range && range.from < 10) onNeedMoreRef.current?.();
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange);

    const onTimeRangeChange = () => onVisibleRangeRef.current?.();
    chart.timeScale().subscribeVisibleTimeRangeChange(onTimeRangeChange);

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRangeChange);
      chart.timeScale().unsubscribeVisibleTimeRangeChange(onTimeRangeChange);
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      studySeriesRef.current.clear();
    };
  }, []);

  // ── Update data + rebuild study series when bars or studies change ─────────
  useEffect(() => {
    if (!chartRef.current || !candleSeriesRef.current || bars.length === 0) return;
    const chart = chartRef.current;

    // Sort + deduplicate by timestamp (guards against scroll-prepend races)
    const sorted = [...bars]
      .sort((a, b) => tsToUnix(a.ts) - tsToUnix(b.ts))
      .filter((b, i, arr) => i === 0 || tsToUnix(b.ts) !== tsToUnix(arr[i - 1].ts));

    // ── Set base candle + volume data ────────────────────────────────────────
    // tfOffsetSec shifts open-time → close-time so the axis shows candle close.
    const toDisplayTime = (ts: string) => (tsToUnix(ts) + tfOffsetSec) as UTCTimestamp;

    candleSeriesRef.current.setData(sorted.map(b => ({
      time: toDisplayTime(b.ts),
      open: b.open, high: b.high, low: b.low, close: b.close,
    })));

    volumeSeriesRef.current.setData(sorted.map(b => ({
      time: toDisplayTime(b.ts),
      value: b.volume,
      color: b.close >= b.open ? "#26a69a66" : "#ef535066",
    })));

    // ── Remove stale study series ────────────────────────────────────────────
    const currentIds = new Set(studies.map(s => s.id));
    for (const [id, seriesList] of studySeriesRef.current) {
      if (!currentIds.has(id)) {
        seriesList.forEach(s => chart.removeSeries(s));
        studySeriesRef.current.delete(id);
      }
    }

    // Recompute data once using sorted bars
    const closes = sorted.map(b => b.close);

    // Oscillator pane assignment: volume is pane 1, oscillators start at pane 2
    // Determine pane indices for oscillators already present
    const oscillatorOrder = studies.filter(s => !OVERLAY_TYPES.includes(s.type)).map(s => s.id);

    // ── Add / update each study ──────────────────────────────────────────────
    for (const study of studies) {
      const isOverlay = OVERLAY_TYPES.includes(study.type);
      const paneIdx   = isOverlay
        ? 0
        : 2 + oscillatorOrder.indexOf(study.id);

      const existing = studySeriesRef.current.get(study.id);

      // ── EMA ────────────────────────────────────────────────────────────────
      if (study.type === "EMA") {
        const data = filterNaN(sorted, calcEMA(closes, study.period), tfOffsetSec);
        if (existing) {
          existing[0].applyOptions({ color: study.color });
          existing[0].setData(data);
        } else {
          const s = chart.addSeries(LineSeries, {
            color: study.color, lineWidth: 1,
            priceLineVisible: false, lastValueVisible: false,
          }, paneIdx);
          s.setData(data);
          studySeriesRef.current.set(study.id, [s]);
        }

      // ── SMA ────────────────────────────────────────────────────────────────
      } else if (study.type === "SMA") {
        const data = filterNaN(sorted, calcSMA(closes, study.period), tfOffsetSec);
        if (existing) {
          existing[0].applyOptions({ color: study.color });
          existing[0].setData(data);
        } else {
          const s = chart.addSeries(LineSeries, {
            color: study.color, lineWidth: 1,
            priceLineVisible: false, lastValueVisible: false,
          }, paneIdx);
          s.setData(data);
          studySeriesRef.current.set(study.id, [s]);
        }

      // ── Bollinger Bands ────────────────────────────────────────────────────
      } else if (study.type === "BB") {
        const { upper, mid, lower } = calcBB(closes, study.period, study.std);
        const uData = filterNaN(sorted, upper, tfOffsetSec);
        const mData = filterNaN(sorted, mid, tfOffsetSec);
        const lData = filterNaN(sorted, lower, tfOffsetSec);
        if (existing && existing.length === 3) {
          existing[0].applyOptions({ color: study.upperColor }); existing[0].setData(uData);
          existing[1].applyOptions({ color: study.midColor });   existing[1].setData(mData);
          existing[2].applyOptions({ color: study.lowerColor }); existing[2].setData(lData);
        } else {
          if (existing) existing.forEach(s => chart.removeSeries(s));
          const makeS = (color: string, title: string) =>
            chart.addSeries(LineSeries, {
              color, lineWidth: 1, lineStyle: 2,
              priceLineVisible: false, lastValueVisible: false, title,
            }, paneIdx);
          const su = makeS(study.upperColor, `BB Upper`);
          const sm = makeS(study.midColor,   `BB Mid`);
          const sl = makeS(study.lowerColor, `BB Lower`);
          su.setData(uData); sm.setData(mData); sl.setData(lData);
          studySeriesRef.current.set(study.id, [su, sm, sl]);
        }

      // ── VWAP ───────────────────────────────────────────────────────────────
      } else if (study.type === "VWAP") {
        const data = filterNaN(sorted, calcVWAP(sorted), tfOffsetSec);
        if (existing) {
          existing[0].applyOptions({ color: study.color });
          existing[0].setData(data);
        } else {
          const s = chart.addSeries(LineSeries, {
            color: study.color, lineWidth: 1,
            priceLineVisible: false, lastValueVisible: false,
          }, paneIdx);
          s.setData(data);
          studySeriesRef.current.set(study.id, [s]);
        }

      // ── RSI ────────────────────────────────────────────────────────────────
      } else if (study.type === "RSI") {
        const rsi   = filterNaN(sorted, calcRSI(closes, study.period), tfOffsetSec);
        const isNew = !existing;
        if (existing) {
          existing[0].applyOptions({ color: study.color });
          existing[0].setData(rsi);
          if (rsi.length > 0) {
            const [first, last] = [rsi[0].time, rsi[rsi.length - 1].time];
            existing[1].setData([{ time: first, value: 70 }, { time: last, value: 70 }]);
            existing[2].setData([{ time: first, value: 30 }, { time: last, value: 30 }]);
          }
        } else {
          const sRSI = chart.addSeries(LineSeries, {
            color: study.color, lineWidth: 1,
            priceLineVisible: false, lastValueVisible: false,
            autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
          }, paneIdx);
          const s70 = chart.addSeries(LineSeries, {
            color: "#ef535044", lineWidth: 1, lineStyle: 2,
            priceLineVisible: false, lastValueVisible: false,
          }, paneIdx);
          const s30 = chart.addSeries(LineSeries, {
            color: "#26a69a44", lineWidth: 1, lineStyle: 2,
            priceLineVisible: false, lastValueVisible: false,
          }, paneIdx);
          sRSI.setData(rsi);
          if (rsi.length > 0) {
            const [first, last] = [rsi[0].time, rsi[rsi.length - 1].time];
            s70.setData([{ time: first, value: 70 }, { time: last, value: 70 }]);
            s30.setData([{ time: first, value: 30 }, { time: last, value: 30 }]);
          }
          chart.panes()[paneIdx]?.setHeight(100);
          studySeriesRef.current.set(study.id, [sRSI, s70, s30]);
        }
        void isNew;

      // ── MACD ───────────────────────────────────────────────────────────────
      } else if (study.type === "MACD") {
        const { macd, signal, histogram } = calcMACD(closes, study.fast, study.slow, study.signal);
        const macdData  = filterNaN(sorted, macd, tfOffsetSec);
        const sigData   = filterNaN(sorted, signal, tfOffsetSec);
        const histData  = sorted
          .map((b, i) => ({
            time: (tsToUnix(b.ts) + tfOffsetSec) as UTCTimestamp, value: histogram[i],
            color: histogram[i] >= 0 ? "#26a69a88" : "#ef535088",
          }))
          .filter(d => !isNaN(d.value));

        if (existing && existing.length === 3) {
          existing[0].applyOptions({ color: study.macdColor });   existing[0].setData(macdData);
          existing[1].applyOptions({ color: study.signalColor }); existing[1].setData(sigData);
          existing[2].setData(histData);
        } else {
          if (existing) existing.forEach(s => chart.removeSeries(s));
          const sMACD = chart.addSeries(LineSeries, {
            color: study.macdColor, lineWidth: 1,
            priceLineVisible: false, lastValueVisible: false,
          }, paneIdx);
          const sSig = chart.addSeries(LineSeries, {
            color: study.signalColor, lineWidth: 1,
            priceLineVisible: false, lastValueVisible: false,
          }, paneIdx);
          const sHist = chart.addSeries(HistogramSeries, {
            priceScaleId: "",
            priceLineVisible: false, lastValueVisible: false,
          }, paneIdx);
          sMACD.setData(macdData);
          sSig.setData(sigData);
          sHist.setData(histData);
          chart.panes()[paneIdx]?.setHeight(100);
          studySeriesRef.current.set(study.id, [sMACD, sSig, sHist]);
        }

      // ── Stochastic ─────────────────────────────────────────────────────────
      } else if (study.type === "Stoch") {
        const { k, d } = calcStoch(bars, study.k, study.d, study.smooth);
        const kData = filterNaN(sorted, k, tfOffsetSec);
        const dData = filterNaN(sorted, d, tfOffsetSec);
        if (existing && existing.length === 2) {
          existing[0].applyOptions({ color: study.kColor }); existing[0].setData(kData);
          existing[1].applyOptions({ color: study.dColor }); existing[1].setData(dData);
        } else {
          if (existing) existing.forEach(s => chart.removeSeries(s));
          const sK = chart.addSeries(LineSeries, {
            color: study.kColor, lineWidth: 1,
            priceLineVisible: false, lastValueVisible: false,
            autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
          }, paneIdx);
          const sD = chart.addSeries(LineSeries, {
            color: study.dColor, lineWidth: 1,
            priceLineVisible: false, lastValueVisible: false,
          }, paneIdx);
          sK.setData(kData);
          sD.setData(dData);
          chart.panes()[paneIdx]?.setHeight(100);
          studySeriesRef.current.set(study.id, [sK, sD]);
        }
      }
    }

    if (!didFitContent.current) {
      chart.timeScale().fitContent();
      didFitContent.current = true;
    }
  }, [bars, studies, tfOffsetSec]);

  useImperativeHandle(ref, () => ({
    get candleSeries() { return candleSeriesRef.current; },
    get volumeSeries() { return volumeSeriesRef.current; },
    get chart() { return chartRef.current; },
  }));

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
});

export default CandlestickChart;
export type { Bar };
