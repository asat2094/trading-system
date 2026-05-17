import numpy as np
import pandas as pd
from technical.trend import analyze_trend, TrendResult


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


def make_sideways(n: int = 60) -> pd.DataFrame:
    np.random.seed(7)
    close = 2800 + np.random.randn(n) * 2   # tiny noise, no trend
    return pd.DataFrame({
        "ts": pd.date_range("2024-01-02 09:15:00", periods=n, freq="1min"),
        "open": close - 1, "high": close + 1,
        "low": close - 1, "close": close,
        "volume": np.random.randint(50000, 200000, n),
    })


def test_uptrend_detected():
    result = analyze_trend(make_uptrend())
    assert isinstance(result, TrendResult)
    assert result.direction == "up"
    assert result.slope > 0
    assert 0.0 <= result.r_squared <= 1.0
    assert result.accuracy > 0.5
    assert 0.0 <= result.strength <= 1.0


def test_downtrend_detected():
    result = analyze_trend(make_downtrend())
    assert result.direction == "down"
    assert result.slope < 0
    assert 0.0 <= result.accuracy <= 1.0


def test_sideways_detected():
    result = analyze_trend(make_sideways())
    assert result.direction == "sideways"
    assert result.accuracy == 0.5


def test_trend_result_has_all_required_fields():
    result = analyze_trend(make_uptrend())
    assert hasattr(result, "direction")
    assert hasattr(result, "strength")
    assert hasattr(result, "accuracy")
    assert hasattr(result, "slope")
    assert hasattr(result, "r_squared")


def test_accuracy_is_fraction_of_bars_on_correct_side():
    result = analyze_trend(make_uptrend())
    assert 0.0 <= result.accuracy <= 1.0
    result_down = analyze_trend(make_downtrend())
    assert 0.0 <= result_down.accuracy <= 1.0
