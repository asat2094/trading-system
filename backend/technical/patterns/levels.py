import numpy as np
import pandas as pd
from scipy.signal import find_peaks

def find_support_resistance(data: pd.DataFrame, prominence_factor: float = 0.3) -> list[dict]:
    highs = data["high"].values
    lows  = data["low"].values
    std   = data["close"].std()
    if std == 0:
        std = 1.0  # fallback for flat data

    resistance_idx, res_props = find_peaks(highs, prominence=std * prominence_factor, distance=5)
    support_idx, sup_props    = find_peaks(-lows, prominence=std * prominence_factor, distance=5)

    levels = []
    for i, idx in enumerate(resistance_idx):
        levels.append({
            "price": round(float(highs[idx]), 2),
            "type": "resistance",
            "strength": min(5, max(1, round(res_props["prominences"][i] / std))),
            "index": int(idx),
        })
    for i, idx in enumerate(support_idx):
        levels.append({
            "price": round(float(lows[idx]), 2),
            "type": "support",
            "strength": min(5, max(1, round(sup_props["prominences"][i] / std))),
            "index": int(idx),
        })
    return sorted(levels, key=lambda x: x["price"])


def pivot_highs(df: pd.DataFrame, left: int = 5, right: int = 5) -> list[int]:
    """
    Return bar indices where high[i] is greater than or equal to
    all highs in the [i-left, i-1] and [i+1, i+right] windows.
    """
    highs = df["high"].values
    n = len(highs)
    result = []
    for i in range(left, n - right):
        window = list(highs[i - left:i]) + list(highs[i + 1:i + right + 1])
        if len(window) == left + right and highs[i] >= max(window):
            result.append(i)
    return result


def pivot_lows(df: pd.DataFrame, left: int = 5, right: int = 5) -> list[int]:
    """
    Return bar indices where low[i] is less than or equal to
    all lows in the [i-left, i-1] and [i+1, i+right] windows.
    """
    lows = df["low"].values
    n = len(lows)
    result = []
    for i in range(left, n - right):
        window = list(lows[i - left:i]) + list(lows[i + 1:i + right + 1])
        if len(window) == left + right and lows[i] <= min(window):
            result.append(i)
    return result
