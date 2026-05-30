export interface Bar {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

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

export interface BBResult {
  upper: number[];
  mid: number[];
  lower: number[];
}

export function calcBB(closes: number[], period: number, std: number): BBResult {
  const mid = calcSMA(closes, period);
  const upper: number[] = [];
  const lower: number[] = [];
  for (let i = 0; i < closes.length; i++) {
    if (isNaN(mid[i])) { upper.push(NaN); lower.push(NaN); continue; }
    let variance = 0;
    for (let j = i - period + 1; j <= i; j++) {
      variance += (closes[j] - mid[i]) ** 2;
    }
    const sigma = Math.sqrt(variance / period);
    upper.push(mid[i] + std * sigma);
    lower.push(mid[i] - std * sigma);
  }
  return { upper, mid, lower };
}

export function calcVWAP(bars: Bar[]): number[] {
  const result: number[] = [];
  let cumTPV = 0, cumVol = 0;
  let lastDate = "";
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

export interface MACDResult {
  macd: number[];
  signal: number[];
  histogram: number[];
}

export function calcMACD(closes: number[], fast: number, slow: number, sig: number): MACDResult {
  const emaFast = calcEMA(closes, fast);
  const emaSlow = calcEMA(closes, slow);
  const macd    = emaFast.map((f, i) => f - emaSlow[i]);
  const signal  = calcEMA(macd, sig);
  const histogram = macd.map((m, i) => m - signal[i]);
  return { macd, signal, histogram };
}

export interface StochResult {
  k: number[];
  d: number[];
}

export function calcStoch(bars: Bar[], kPeriod: number, dPeriod: number, smooth: number): StochResult {
  const kRaw = bars.map((_, i) => {
    if (i < kPeriod - 1) return NaN;
    let lo = Infinity, hi = -Infinity;
    for (let j = i - kPeriod + 1; j <= i; j++) {
      lo = Math.min(lo, bars[j].low);
      hi = Math.max(hi, bars[j].high);
    }
    return hi === lo ? 50 : ((bars[i].close - lo) / (hi - lo)) * 100;
  });
  // Smooth %K (slow stoch uses smooth=3; fast uses smooth=1)
  const kSmoothed = smooth > 1 ? calcSMA(kRaw, smooth) : kRaw;
  const d = calcSMA(kSmoothed, dPeriod);
  return { k: kSmoothed, d };
}

// ---------------------------------------------------------------------------
// Volume Profile
// ---------------------------------------------------------------------------

export interface VolumeProfileBucket {
  priceFrom: number;
  priceTo:   number;
  upVol:     number;
  downVol:   number;
  isPoc:     boolean;
}

/**
 * Compute volume profile from OHLCV bars.
 * Returns `rows` price buckets sorted ascending, with POC bucket flagged.
 */
export function calcVolumeProfile(bars: Bar[], rows: number): VolumeProfileBucket[] {
  if (bars.length === 0 || rows < 1) return [];

  const minPrice = Math.min(...bars.map((b) => b.low));
  const maxPrice = Math.max(...bars.map((b) => b.high));
  const step     = (maxPrice - minPrice) / rows;
  if (step === 0) return [];

  const upVols   = new Float64Array(rows);
  const downVols = new Float64Array(rows);

  for (const bar of bars) {
    const idx = Math.min(Math.floor((bar.close - minPrice) / step), rows - 1);
    if (bar.close >= bar.open) {
      upVols[idx]   += bar.volume;
    } else {
      downVols[idx] += bar.volume;
    }
  }

  let maxTotal = 0;
  let pocIdx   = 0;
  for (let i = 0; i < rows; i++) {
    const total = upVols[i] + downVols[i];
    if (total > maxTotal) { maxTotal = total; pocIdx = i; }
  }

  return Array.from({ length: rows }, (_, i) => ({
    priceFrom: minPrice + i * step,
    priceTo:   minPrice + (i + 1) * step,
    upVol:     upVols[i],
    downVol:   downVols[i],
    isPoc:     i === pocIdx,
  }));
}

// ---------------------------------------------------------------------------
// Fair Value Gap
// ---------------------------------------------------------------------------

export interface FVGZone {
  time:      number;   // unix seconds of middle candle
  high:      number;   // upper edge of gap
  low:       number;   // lower edge of gap
  direction: "bull" | "bear";
}

/**
 * Detect Fair Value Gaps.
 * Bull FVG: bars[i+2].low > bars[i].high  (price gapped up)
 * Bear FVG: bars[i+2].high < bars[i].low  (price gapped down)
 * minGapPct: minimum gap size as % of bar i price (default 0.1%).
 */
export function calcFVG(bars: Bar[], minGapPct = 0.1): FVGZone[] {
  const zones: FVGZone[] = [];
  for (let i = 0; i < bars.length - 2; i++) {
    const a = bars[i];
    const b = bars[i + 1];
    const c = bars[i + 2];
    const midTime = new Date(b.ts.includes("T") ? b.ts + "+05:30" : b.ts).getTime() / 1000;

    if (c.low > a.high) {
      const gapPct = ((c.low - a.high) / a.high) * 100;
      if (gapPct >= minGapPct) {
        zones.push({ time: midTime, high: c.low, low: a.high, direction: "bull" });
      }
    }
    if (c.high < a.low) {
      const gapPct = ((a.low - c.high) / a.low) * 100;
      if (gapPct >= minGapPct) {
        zones.push({ time: midTime, high: a.low, low: c.high, direction: "bear" });
      }
    }
  }
  return zones;
}
