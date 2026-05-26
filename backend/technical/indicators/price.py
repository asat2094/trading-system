# backend/technical/indicators/price.py
"""Price-relative indicators — indicators that compare close to chart levels."""
from __future__ import annotations
import pandas as pd


def price_vs_resistance(data: pd.DataFrame) -> pd.Series:
    """
    Returns ratio of close price to nearest resistance level above.
    Values > 1.0 mean close is above all resistance (breakout).
    Values approaching 1.0 from below = close near resistance.
    Returns 1.1 for bars above all resistance levels.
    Returns 1.0 when no resistance levels found.
    """
    from technical.patterns.levels import find_support_resistance

    levels = find_support_resistance(data)
    resistance_levels = [lv["price"] for lv in levels if lv["type"] == "resistance"]

    if not resistance_levels:
        return pd.Series([1.0] * len(data), index=data.index)

    result = []
    for close in data["close"]:
        above = [r for r in resistance_levels if r >= close]
        if above:
            result.append(close / min(above))
        else:
            result.append(1.1)  # above all resistance = breakout
    return pd.Series(result, index=data.index)
