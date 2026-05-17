import pytest
import pandas as pd
import numpy as np
from technical.patterns.detector import detect_patterns
from technical.patterns.levels import find_support_resistance
from core.sdk import Patterns

def make_double_bottom(n: int = 100) -> pd.DataFrame:
    t = np.arange(n)
    price = 2800 + 50 * np.sin(2 * np.pi * t / 40)
    price[15:20] = 2750
    price[55:60] = 2752
    return pd.DataFrame({
        "ts": pd.date_range("2024-01-01", periods=n, freq="1min"),
        "open": price - 2, "high": price + 5,
        "low": price - 5, "close": price,
        "volume": np.random.randint(50000, 200000, n),
    })

def test_double_bottom_detected():
    df = make_double_bottom(100)
    results = detect_patterns(df, ["double_bottom"])
    assert isinstance(results, list)
    for r in results:
        assert "pattern" in r
        assert "confidence" in r
        assert 0 <= r["confidence"] <= 1
        assert "direction" in r
        assert r["direction"] in ("bullish", "bearish", "neutral")
    # The synthetic double-bottom must be detected
    assert len(results) >= 1
    assert results[0]["pattern"] == "double_bottom"

def test_detect_unknown_pattern_raises():
    df = make_double_bottom()
    with pytest.raises(ValueError, match="unknown_pattern"):
        detect_patterns(df, ["unknown_pattern"])

def test_support_resistance_returns_levels():
    df = make_double_bottom(100)
    levels = find_support_resistance(df)
    assert isinstance(levels, list)
    for level in levels:
        assert "price" in level
        assert "type" in level
        assert level["type"] in ("support", "resistance")
        assert "strength" in level

def test_patterns_sdk_detect():
    df = make_double_bottom(100)
    results = Patterns.detect(df, ["double_bottom", "head_and_shoulders"])
    assert isinstance(results, list)

def test_double_top_not_detected_on_uptrend():
    """Monotonically rising data should not produce a double-top."""
    n = 100
    t = np.arange(n)
    price = 2800 + t * 5.0  # strict uptrend, no peaks
    df = pd.DataFrame({
        "ts": pd.date_range("2024-01-01", periods=n, freq="1min"),
        "open": price - 2, "high": price + 2,
        "low": price - 2, "close": price,
        "volume": np.ones(n, dtype=int) * 100000,
    })
    results = detect_patterns(df, ["double_top"])
    assert results == []
