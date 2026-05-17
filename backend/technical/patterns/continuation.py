import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from technical.patterns.reversal import PatternResult

def detect_bull_flag(data: pd.DataFrame) -> PatternResult | None:
    close = data["close"].values
    n = len(close)
    if n < 20:
        return None

    pole_end = n // 2
    pole_gain = (close[pole_end] - close[0]) / close[0]
    if pole_gain < 0.05:
        return None

    flag_range = close[pole_end:].max() - close[pole_end:].min()
    pole_move = close[pole_end] - close[0]
    if flag_range > pole_move * 0.5:
        return None

    confidence = min(1.0, pole_gain * 5)
    return PatternResult(
        pattern="bull_flag",
        confidence=round(confidence, 2),
        direction="bullish",
        key_levels=[round(close[0], 2), round(close[pole_end], 2)],
        formed_at=str(data["ts"].iloc[-1]) if "ts" in data.columns else "",
        target=round(close[-1] + pole_move, 2),
    )
