from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.signal import find_peaks

@dataclass
class PatternResult:
    pattern: str
    confidence: float
    direction: str
    key_levels: list[float]
    formed_at: str
    target: float | None = None

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "confidence": self.confidence,
            "direction": self.direction,
            "key_levels": self.key_levels,
            "formed_at": self.formed_at,
            "target": self.target,
        }


def detect_double_bottom(data: pd.DataFrame) -> PatternResult | None:
    lows = data["low"].values
    troughs, _ = find_peaks(-lows, distance=10, prominence=lows.std() * 0.3)
    if len(troughs) < 2:
        return None

    t1, t2 = troughs[-2], troughs[-1]
    p1, p2 = lows[t1], lows[t2]

    if abs(p1 - p2) / p1 > 0.03:
        return None

    mid_slice = data["high"].values[t1:t2]
    if len(mid_slice) == 0:
        return None
    neck = mid_slice.max()
    trough_avg = (p1 + p2) / 2
    depth = neck - trough_avg
    if depth <= 0:
        return None

    confidence = min(1.0, depth / (lows.std() * 2))
    target = neck + depth
    formed_ts = str(data["ts"].iloc[t2]) if "ts" in data.columns else ""

    return PatternResult(
        pattern="double_bottom",
        confidence=round(confidence, 2),
        direction="bullish",
        key_levels=[round(trough_avg, 2), round(neck, 2)],
        formed_at=formed_ts,
        target=round(target, 2),
    )


def detect_double_top(data: pd.DataFrame) -> PatternResult | None:
    highs = data["high"].values
    peaks, _ = find_peaks(highs, distance=10, prominence=highs.std() * 0.3)
    if len(peaks) < 2:
        return None

    t1, t2 = peaks[-2], peaks[-1]
    p1, p2 = highs[t1], highs[t2]

    if abs(p1 - p2) / p1 > 0.03:
        return None

    mid_slice = data["low"].values[t1:t2]
    if len(mid_slice) == 0:
        return None
    neck = mid_slice.min()
    peak_avg = (p1 + p2) / 2
    depth = peak_avg - neck
    if depth <= 0:
        return None

    confidence = min(1.0, depth / (highs.std() * 2))
    target = neck - depth
    formed_ts = str(data["ts"].iloc[t2]) if "ts" in data.columns else ""

    return PatternResult(
        pattern="double_top",
        confidence=round(confidence, 2),
        direction="bearish",
        key_levels=[round(neck, 2), round(peak_avg, 2)],
        formed_at=formed_ts,
        target=round(target, 2),
    )


def detect_head_and_shoulders(data: pd.DataFrame) -> PatternResult | None:
    highs = data["high"].values
    peaks, props = find_peaks(highs, distance=8, prominence=highs.std() * 0.2)
    if len(peaks) < 3:
        return None

    ls, head, rs = peaks[-3], peaks[-2], peaks[-1]
    h_ls, h_head, h_rs = highs[ls], highs[head], highs[rs]

    if not (h_head > h_ls and h_head > h_rs):
        return None
    if abs(h_ls - h_rs) / h_ls > 0.05:
        return None

    neckline = data["low"].values[ls:rs + 1].min()
    depth = ((h_ls + h_rs) / 2) - neckline
    confidence = min(1.0, depth / highs.std())
    formed_ts = str(data["ts"].iloc[rs]) if "ts" in data.columns else ""

    return PatternResult(
        pattern="head_and_shoulders",
        confidence=round(confidence, 2),
        direction="bearish",
        key_levels=[round(neckline, 2), round(h_head, 2)],
        formed_at=formed_ts,
        target=round(neckline - depth, 2),
    )
