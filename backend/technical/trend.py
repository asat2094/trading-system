from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.stats import linregress


@dataclass
class TrendResult:
    direction: str    # "up" | "down" | "sideways"
    strength: float   # 0.0 – 1.0
    accuracy: float   # 0.0 – 1.0
    slope: float
    r_squared: float


def analyze_trend(data: pd.DataFrame, window: int = 20) -> TrendResult:
    df = data.tail(window) if len(data) > window else data

    if len(df) < 5:
        return TrendResult(direction="sideways", strength=0.0, accuracy=0.5, slope=0.0, r_squared=0.0)

    close = df["close"].values.astype(float)
    x = np.arange(len(close))
    slope, intercept, r_value, _, _ = linregress(x, close)
    r_squared = float(r_value ** 2)

    mean_price = close.mean()
    # Sideways: normalised slope < 0.1% per bar
    if mean_price > 0 and abs(slope) / mean_price < 0.001:
        direction = "sideways"
    elif slope > 0:
        direction = "up"
    else:
        direction = "down"

    strength = min(1.0, abs(slope) / mean_price * 100) if mean_price > 0 else 0.0

    fitted = intercept + slope * x
    if direction == "up":
        accuracy = float(np.mean(close >= fitted))
    elif direction == "down":
        accuracy = float(np.mean(close <= fitted))
    else:
        accuracy = 0.5

    return TrendResult(
        direction=direction,
        strength=round(strength, 4),
        accuracy=round(accuracy, 3),
        slope=round(float(slope), 6),
        r_squared=round(r_squared, 3),
    )
