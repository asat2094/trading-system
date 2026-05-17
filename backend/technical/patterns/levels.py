import numpy as np
import pandas as pd
from scipy.signal import find_peaks

def find_support_resistance(data: pd.DataFrame, prominence_factor: float = 0.3) -> list[dict]:
    highs = data["high"].values
    lows  = data["low"].values
    std   = data["close"].std()

    resistance_idx, _ = find_peaks(highs, prominence=std * prominence_factor, distance=5)
    support_idx, _    = find_peaks(-lows, prominence=std * prominence_factor, distance=5)

    levels = []
    for idx in resistance_idx:
        levels.append({
            "price": round(float(highs[idx]), 2),
            "type": "resistance",
            "strength": min(5, int(highs[idx] / std)),
            "index": int(idx),
        })
    for idx in support_idx:
        levels.append({
            "price": round(float(lows[idx]), 2),
            "type": "support",
            "strength": min(5, int(std / max(lows[idx], 1))),
            "index": int(idx),
        })
    return sorted(levels, key=lambda x: x["price"])
