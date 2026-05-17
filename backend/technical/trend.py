from __future__ import annotations
import numpy as np
import pandas as pd
from scipy.stats import linregress

def analyze_trend(
    data: pd.DataFrame,
    from_time: str | None = None,
    to_time: str | None = None,
    timeframe: str = "1min",
) -> dict:
    df = data.copy()

    if from_time and to_time and "ts" in df.columns:
        df["_time"] = pd.to_datetime(df["ts"]).dt.strftime("%H:%M")
        df = df[(df["_time"] >= from_time) & (df["_time"] <= to_time)]
        window = f"{from_time}–{to_time}"
    else:
        window = "full"

    if len(df) < 5:
        return _flat_result(window, timeframe)

    close = df["close"].values
    x = np.arange(len(close))
    slope, intercept, r_value, _, _ = linregress(x, close)
    r_squared = r_value ** 2

    if slope > 0 and r_squared > 0.3:
        direction = "up"
    elif slope < 0 and r_squared > 0.3:
        direction = "down"
    else:
        direction = "sideways"

    if r_squared > 0.75:
        strength = "strong"
    elif r_squared > 0.4:
        strength = "moderate"
    else:
        strength = "weak"

    fitted = intercept + slope * x

    # Measure accuracy as the proportion of bars that are in the direction of the trend
    if len(close) > 1:
        close_diff = np.diff(close)
        if direction == "up":
            accuracy = float(np.mean(close_diff > 0))
        elif direction == "down":
            accuracy = float(np.mean(close_diff < 0))
        else:
            accuracy = 0.5
    else:
        accuracy = 0.5

    return {
        "direction":  direction,
        "strength":   strength,
        "accuracy":   round(accuracy, 3),
        "slope":      round(float(slope), 4),
        "r_squared":  round(float(r_squared), 3),
        "window":     window,
        "timeframe":  timeframe,
    }

def _flat_result(window: str, timeframe: str) -> dict:
    return {
        "direction": "sideways", "strength": "weak",
        "accuracy": 0.5, "slope": 0.0, "r_squared": 0.0,
        "window": window, "timeframe": timeframe,
    }
