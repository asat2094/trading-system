# backend/technical/patterns/candlestick.py
"""
Candlestick pattern detection.
Returns {"confidence": float, "direction": str} or None.
All detectors receive a DataFrame of up to 3 bars.
"""
from __future__ import annotations
import pandas as pd


def _body(row) -> float:
    return abs(row["close"] - row["open"])


def _upper_shadow(row) -> float:
    return row["high"] - max(row["open"], row["close"])


def _lower_shadow(row) -> float:
    return min(row["open"], row["close"]) - row["low"]


def _is_green(row) -> bool:
    return row["close"] >= row["open"]


def _is_red(row) -> bool:
    return row["close"] < row["open"]


def _detect_bearish_engulfing(df: pd.DataFrame) -> dict | None:
    if len(df) < 2:
        return None
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    if not (_is_green(prev) and _is_red(curr)):
        return None
    # curr body must engulf prev body: curr opens above prev close, closes below prev open
    if curr["open"] >= prev["close"] and curr["close"] <= prev["open"]:
        prev_body = _body(prev)
        curr_body = _body(curr)
        if prev_body == 0:
            return None
        confidence = min(curr_body / prev_body / 3.0, 1.0)
        return {"confidence": round(confidence, 4), "direction": "bearish"}
    return None


def _detect_bullish_engulfing(df: pd.DataFrame) -> dict | None:
    if len(df) < 2:
        return None
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    if not (_is_red(prev) and _is_green(curr)):
        return None
    # curr body engulfs prev: curr opens below prev close, closes above prev open
    if curr["open"] <= prev["close"] and curr["close"] >= prev["open"]:
        prev_body = _body(prev)
        curr_body = _body(curr)
        if prev_body == 0:
            return None
        confidence = min(curr_body / prev_body / 3.0, 1.0)
        return {"confidence": round(confidence, 4), "direction": "bullish"}
    return None


def _detect_hammer(df: pd.DataFrame) -> dict | None:
    row = df.iloc[-1]
    body = _body(row)
    if body == 0:
        return None
    lower = _lower_shadow(row)
    upper = _upper_shadow(row)
    if lower >= 2 * body and upper <= 0.1 * body:
        confidence = min(lower / body / 3.0, 1.0)
        return {"confidence": round(confidence, 4), "direction": "bullish"}
    return None


def _detect_shooting_star(df: pd.DataFrame) -> dict | None:
    row = df.iloc[-1]
    body = _body(row)
    if body == 0:
        return None
    upper = _upper_shadow(row)
    lower = _lower_shadow(row)
    if upper >= 2 * body and lower <= 0.1 * body + 1e-9:
        confidence = min(upper / body / 3.0, 1.0)
        return {"confidence": round(confidence, 4), "direction": "bearish"}
    return None


def _detect_doji(df: pd.DataFrame) -> dict | None:
    row = df.iloc[-1]
    price_range = row["high"] - row["low"]
    if price_range == 0:
        return None
    body_pct = _body(row) / price_range
    if body_pct < 0.1:
        confidence = round(1.0 - (body_pct / 0.1), 4)
        return {"confidence": confidence, "direction": "neutral"}
    return None


def _detect_morning_star(df: pd.DataFrame) -> dict | None:
    if len(df) < 3:
        return None
    b1, b2, b3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    if not (_is_red(b1) and _is_green(b3)):
        return None
    b1_body = _body(b1)
    b2_body = _body(b2)
    b3_body = _body(b3)
    # bar1 and bar3 must be large relative to bar2
    if b1_body < 2 * b2_body or b3_body < 2 * b2_body:
        return None
    avg_body = (b1_body + b3_body) / 2
    if avg_body == 0:
        return None
    confidence = min(avg_body / (avg_body + b2_body + 1e-9), 1.0)
    return {"confidence": round(confidence, 4), "direction": "bullish"}


def _detect_evening_star(df: pd.DataFrame) -> dict | None:
    if len(df) < 3:
        return None
    b1, b2, b3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    if not (_is_green(b1) and _is_red(b3)):
        return None
    b1_body = _body(b1)
    b2_body = _body(b2)
    b3_body = _body(b3)
    if b1_body < 2 * b2_body or b3_body < 2 * b2_body:
        return None
    avg_body = (b1_body + b3_body) / 2
    if avg_body == 0:
        return None
    confidence = min(avg_body / (avg_body + b2_body + 1e-9), 1.0)
    return {"confidence": round(confidence, 4), "direction": "bearish"}


_CANDLESTICK_DETECTORS: dict[str, callable] = {
    "bearish_engulfing": _detect_bearish_engulfing,
    "bullish_engulfing": _detect_bullish_engulfing,
    "hammer":            _detect_hammer,
    "shooting_star":     _detect_shooting_star,
    "doji":              _detect_doji,
    "morning_star":      _detect_morning_star,
    "evening_star":      _detect_evening_star,
}


def detect_candlestick(df: pd.DataFrame, pattern: str) -> dict | None:
    """
    Detect a candlestick pattern on the last 1–3 bars of df.

    Args:
        df: DataFrame with columns open, high, low, close. Pass df.tail(3).
        pattern: Pattern name — must be in _CANDLESTICK_DETECTORS.

    Returns:
        {"confidence": float (0–1), "direction": str} if detected, None otherwise.

    Raises:
        ValueError: if pattern name is unknown.
    """
    if pattern not in _CANDLESTICK_DETECTORS:
        raise ValueError(
            f"Unknown candlestick pattern: {pattern!r}. "
            f"Available: {sorted(_CANDLESTICK_DETECTORS)}"
        )
    return _CANDLESTICK_DETECTORS[pattern](df)
