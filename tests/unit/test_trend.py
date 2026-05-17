import pytest
import numpy as np
import pandas as pd
from technical.trend import analyze_trend

def make_uptrend(n: int = 60) -> pd.DataFrame:
    np.random.seed(42)
    t = np.arange(n)
    close = 2800 + t * 5 + np.random.randn(n) * 3
    return pd.DataFrame({
        "ts": pd.date_range("2024-01-02 09:15:00", periods=n, freq="1min"),
        "open": close - 2, "high": close + 3,
        "low": close - 3, "close": close,
        "volume": np.random.randint(50000, 200000, n),
    })

def make_downtrend(n: int = 60) -> pd.DataFrame:
    np.random.seed(42)
    t = np.arange(n)
    close = 2800 - t * 4 + np.random.randn(n) * 2
    return pd.DataFrame({
        "ts": pd.date_range("2024-01-02 09:15:00", periods=n, freq="1min"),
        "open": close - 2, "high": close + 3,
        "low": close - 3, "close": close,
        "volume": np.random.randint(50000, 200000, n),
    })

def test_uptrend_detected():
    df = make_uptrend()
    result = analyze_trend(df)
    assert result["direction"] == "up"
    assert result["slope"] > 0
    assert 0 <= result["r_squared"] <= 1
    assert result["accuracy"] > 0.5
    assert result["strength"] in ("strong", "moderate", "weak")

def test_downtrend_detected():
    df = make_downtrend()
    result = analyze_trend(df)
    assert result["direction"] == "down"
    assert result["slope"] < 0

def test_trend_with_time_window():
    df = make_uptrend(200)
    result = analyze_trend(df, from_time="09:30", to_time="10:30")
    assert result["window"] == "09:30–10:30"
    assert "direction" in result

def test_trend_result_has_all_required_fields():
    df = make_uptrend()
    result = analyze_trend(df)
    required = {"direction", "strength", "accuracy", "slope", "r_squared", "window", "timeframe"}
    assert required.issubset(result.keys())
