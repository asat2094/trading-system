export interface Bar {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// ── Source selector ──────────────────────────────────────────────────────────

export type SourceType = "close" | "open" | "high" | "low" | "hl2" | "hlc3" | "ohlc4" | "hlcc4";

export function getSourceValues(bars: Bar[], source: string): number[] {
  return bars.map(b => {
    switch (source) {
      case "open":  return b.open;
      case "high":  return b.high;
      case "low":   return b.low;
      case "hl2":   return (b.high + b.low) / 2;
      case "hlc3":  return (b.high + b.low + b.close) / 3;
      case "ohlc4": return (b.open + b.high + b.low + b.close) / 4;
      case "hlcc4": return (b.high + b.low + b.close + b.close) / 4;
      default:      return b.close;
    }
  });
}

// ── EMA / SMA ────────────────────────────────────────────────────────────────

export function calcEMA(values: number[], period: number): number[] {
  const k = 2 / (period + 1);
  const out: number[] = [];
  let prev = values[0];
  for (let i = 0; i < values.length; i++) {
    const v = i === 0 ? values[0] : values[i] * k + prev * (1 - k);
    out.push(v);
    prev = v;
  }
  return out;
}

export function calcSMA(values: number[], period: number): number[] {
  return values.map((_, i) => {
    if (i < period - 1) return NaN;
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += values[j];
    return sum / period;
  });
}

// ── RSI ──────────────────────────────────────────────────────────────────────

export function calcRSI(closes: number[], period = 14): number[] {
  const result: number[] = new Array(period).fill(NaN);
  let avgGain = 0, avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff > 0) avgGain += diff; else avgLoss += Math.abs(diff);
  }
  avgGain /= period; avgLoss /= period;
  result.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss));
  for (let i = period + 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    avgGain = (avgGain * (period - 1) + (diff > 0 ? diff : 0)) / period;
    avgLoss = (avgLoss * (period - 1) + (diff < 0 ? -diff : 0)) / period;
    result.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss));
  }
  return result;
}

// ── Bollinger Bands ──────────────────────────────────────────────────────────

export interface BBResult { upper: number[]; mid: number[]; lower: number[] }

export function calcBB(closes: number[], period: number, std: number): BBResult {
  const mid = calcSMA(closes, period);
  const upper: number[] = [], lower: number[] = [];
  for (let i = 0; i < closes.length; i++) {
    if (isNaN(mid[i])) { upper.push(NaN); lower.push(NaN); continue; }
    let variance = 0;
    for (let j = i - period + 1; j <= i; j++) variance += (closes[j] - mid[i]) ** 2;
    const sigma = Math.sqrt(variance / period);
    upper.push(mid[i] + std * sigma);
    lower.push(mid[i] - std * sigma);
  }
  return { upper, mid, lower };
}

// ── VWAP + Standard Deviation Bands ─────────────────────────────────────────

export function calcVWAP(bars: Bar[]): number[] {
  const result: number[] = [];
  let cumTPV = 0, cumVol = 0, lastDate = "";
  for (const b of bars) {
    const date = b.ts.split("T")[0];
    if (date !== lastDate) { cumTPV = 0; cumVol = 0; lastDate = date; }
    const tp = (b.high + b.low + b.close) / 3;
    cumTPV += tp * b.volume;
    cumVol += b.volume;
    result.push(cumVol > 0 ? cumTPV / cumVol : NaN);
  }
  return result;
}

export interface VWAPBandsResult {
  vwap:   number[];
  upper1: number[]; lower1: number[];
  upper2: number[]; lower2: number[];
  upper3: number[]; lower3: number[];
}

export function calcVWAPBands(bars: Bar[]): VWAPBandsResult {
  const vwap: number[] = [], upper1: number[] = [], lower1: number[] = [];
  const upper2: number[] = [], lower2: number[] = [], upper3: number[] = [], lower3: number[] = [];
  let cumTPV = 0, cumTP2V = 0, cumVol = 0, lastDate = "";
  for (const b of bars) {
    const date = b.ts.split("T")[0];
    if (date !== lastDate) { cumTPV = 0; cumTP2V = 0; cumVol = 0; lastDate = date; }
    const tp  = (b.high + b.low + b.close) / 3;
    cumTPV   += tp * b.volume;
    cumTP2V  += tp * tp * b.volume;
    cumVol   += b.volume;
    if (cumVol === 0) {
      [vwap, upper1, lower1, upper2, lower2, upper3, lower3].forEach(a => a.push(NaN));
      continue;
    }
    const v  = cumTPV / cumVol;
    const sd = Math.sqrt(Math.max(0, cumTP2V / cumVol - v * v));
    vwap.push(v);
    upper1.push(v + sd);     lower1.push(v - sd);
    upper2.push(v + 2 * sd); lower2.push(v - 2 * sd);
    upper3.push(v + 3 * sd); lower3.push(v - 3 * sd);
  }
  return { vwap, upper1, lower1, upper2, lower2, upper3, lower3 };
}

// ── Pivot Points ─────────────────────────────────────────────────────────────

export interface PivotLevels {
  pp: number;
  r1: number; r2: number; r3: number; r4?: number;
  s1: number; s2: number; s3: number; s4?: number;
  periodLabel: string;
}

function isoWeekKey(ts: string): string {
  const d    = new Date(ts);
  const temp = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dow  = temp.getUTCDay() || 7;
  temp.setUTCDate(temp.getUTCDate() + 4 - dow);
  const year1  = new Date(Date.UTC(temp.getUTCFullYear(), 0, 1));
  const weekNo = Math.ceil(((temp.getTime() - year1.getTime()) / 86400000 + 1) / 7);
  return `${temp.getUTCFullYear()}-W${String(weekNo).padStart(2, "0")}`;
}

function periodKey(ts: string, period: string): string {
  if (period === "monthly") return ts.slice(0, 7);
  if (period === "weekly")  return isoWeekKey(ts);
  return ts.split("T")[0];
}

function computeLevels(H: number, L: number, C: number, pivotType: string): Omit<PivotLevels, "periodLabel"> {
  const range = H - L;
  switch (pivotType) {
    case "fibonacci": {
      const pp = (H + L + C) / 3;
      return { pp, r1: pp + 0.382 * range, r2: pp + 0.618 * range, r3: pp + range, s1: pp - 0.382 * range, s2: pp - 0.618 * range, s3: pp - range };
    }
    case "woodie": {
      const pp = (H + L + 2 * C) / 4;
      return { pp, r1: 2 * pp - L, r2: pp + range, r3: H + 2 * (pp - L), s1: 2 * pp - H, s2: pp - range, s3: L - 2 * (H - pp) };
    }
    case "camarilla": {
      const pp = (H + L + C) / 3;
      return { pp, r1: C + 1.1*range/12, r2: C + 1.1*range/6, r3: C + 1.1*range/4, r4: C + 1.1*range/2, s1: C - 1.1*range/12, s2: C - 1.1*range/6, s3: C - 1.1*range/4, s4: C - 1.1*range/2 };
    }
    default: { // standard / classic
      const pp = (H + L + C) / 3;
      return { pp, r1: 2*pp - L, r2: pp + range, r3: H + 2*(pp - L), s1: 2*pp - H, s2: pp - range, s3: L - 2*(H - pp) };
    }
  }
}

export function calcPivots(bars: Bar[], pivotType: string, period: string): PivotLevels | null {
  if (bars.length < 2) return null;
  const map = new Map<string, { h: number; l: number; c: number }>();
  for (const b of bars) {
    const k  = periodKey(b.ts, period);
    const ex = map.get(k);
    if (!ex) map.set(k, { h: b.high, l: b.low, c: b.close });
    else { ex.h = Math.max(ex.h, b.high); ex.l = Math.min(ex.l, b.low); ex.c = b.close; }
  }
  const currentKey = periodKey(bars[bars.length - 1].ts, period);
  const prevKeys   = [...map.keys()].sort().filter(k => k < currentKey);
  if (prevKeys.length === 0) return null;
  const prev = map.get(prevKeys[prevKeys.length - 1])!;
  return { ...computeLevels(prev.h, prev.l, prev.c, pivotType), periodLabel: prevKeys[prevKeys.length - 1] };
}

// ── MACD ─────────────────────────────────────────────────────────────────────

export interface MACDResult { macd: number[]; signal: number[]; histogram: number[] }

export function calcMACD(closes: number[], fast: number, slow: number, sig: number): MACDResult {
  const emaFast = calcEMA(closes, fast), emaSlow = calcEMA(closes, slow);
  const macd    = emaFast.map((f, i) => f - emaSlow[i]);
  const signal  = calcEMA(macd, sig);
  return { macd, signal, histogram: macd.map((m, i) => m - signal[i]) };
}

// ── Stochastic ───────────────────────────────────────────────────────────────

export interface StochResult { k: number[]; d: number[] }

export function calcStoch(bars: Bar[], kPeriod: number, dPeriod: number, smooth: number): StochResult {
  const kRaw = bars.map((_, i) => {
    if (i < kPeriod - 1) return NaN;
    let lo = Infinity, hi = -Infinity;
    for (let j = i - kPeriod + 1; j <= i; j++) { lo = Math.min(lo, bars[j].low); hi = Math.max(hi, bars[j].high); }
    return hi === lo ? 50 : ((bars[i].close - lo) / (hi - lo)) * 100;
  });
  const kSmoothed = smooth > 1 ? calcSMA(kRaw, smooth) : kRaw;
  return { k: kSmoothed, d: calcSMA(kSmoothed, dPeriod) };
}

// ── Volume Profile ────────────────────────────────────────────────────────────

export interface VolumeProfileBucket { priceFrom: number; priceTo: number; upVol: number; downVol: number; isPoc: boolean }

export function calcVolumeProfile(bars: Bar[], rows: number): VolumeProfileBucket[] {
  if (bars.length === 0 || rows < 1) return [];
  const minPrice = Math.min(...bars.map(b => b.low)), maxPrice = Math.max(...bars.map(b => b.high));
  const step = (maxPrice - minPrice) / rows;
  if (step === 0) return [];
  const upVols = new Float64Array(rows), downVols = new Float64Array(rows);
  for (const bar of bars) {
    const idx = Math.min(Math.floor((bar.close - minPrice) / step), rows - 1);
    if (bar.close >= bar.open) upVols[idx] += bar.volume; else downVols[idx] += bar.volume;
  }
  let maxTotal = 0, pocIdx = 0;
  for (let i = 0; i < rows; i++) { const t = upVols[i] + downVols[i]; if (t > maxTotal) { maxTotal = t; pocIdx = i; } }
  return Array.from({ length: rows }, (_, i) => ({ priceFrom: minPrice + i * step, priceTo: minPrice + (i+1) * step, upVol: upVols[i], downVol: downVols[i], isPoc: i === pocIdx }));
}

// ── Fair Value Gap ────────────────────────────────────────────────────────────

export interface FVGZone { time: number; high: number; low: number; direction: "bull" | "bear" }

export function calcFVG(bars: Bar[], minGapPct = 0.1): FVGZone[] {
  const zones: FVGZone[] = [];
  for (let i = 0; i < bars.length - 2; i++) {
    const a = bars[i], b = bars[i+1], c = bars[i+2];
    const midTime = new Date(b.ts.includes("T") ? b.ts + "+05:30" : b.ts).getTime() / 1000;
    if (c.low > a.high && ((c.low - a.high) / a.high) * 100 >= minGapPct)
      zones.push({ time: midTime, high: c.low, low: a.high, direction: "bull" });
    if (c.high < a.low && ((a.low - c.high) / a.low) * 100 >= minGapPct)
      zones.push({ time: midTime, high: a.low, low: c.high, direction: "bear" });
  }
  return zones;
}
