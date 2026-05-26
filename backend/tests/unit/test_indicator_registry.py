# backend/tests/unit/test_indicator_registry.py
import pandas as pd
import pytest
from technical.indicators.registry import get_indicator, list_indicators


def make_ohlcv(n=50, start_price=100.0) -> pd.DataFrame:
    closes = [start_price + i * 0.5 + (i % 5) * 0.3 for i in range(n)]
    return pd.DataFrame({
        "ts":     pd.date_range("2026-01-01", periods=n, freq="1D"),
        "open":   [c - 0.2 for c in closes],
        "high":   [c + 0.5 for c in closes],
        "low":    [c - 0.5 for c in closes],
        "close":  closes,
        "volume": [100_000 + i * 1000 for i in range(n)],
        "symbol": ["TEST"] * n,
    })


@pytest.fixture
def df():
    return make_ohlcv()


def test_all_expected_indicators_registered():
    names = list_indicators()
    expected = [
        "rsi", "macd", "ema", "sma", "wma", "vwap", "bollinger_bands",
        "atr", "stochastic", "cci", "williams_r", "obv", "supertrend",
        "price_vs_resistance",
    ]
    for name in expected:
        assert name in names, f"Missing from registry: {name!r}"


def test_get_indicator_returns_callable(df):
    for name in list_indicators():
        fn = get_indicator(name)
        assert callable(fn), f"{name!r} is not callable"


def test_sma_returns_series(df):
    fn = get_indicator("sma")
    result = fn(df, period=10)
    assert isinstance(result, pd.Series)
    assert not result.dropna().empty


def test_wma_returns_series(df):
    fn = get_indicator("wma")
    result = fn(df, period=10)
    assert isinstance(result, pd.Series)


def test_stochastic_returns_dataframe(df):
    fn = get_indicator("stochastic")
    result = fn(df)
    assert isinstance(result, pd.DataFrame)
    assert any(c.startswith("STOCHk_") for c in result.columns)


def test_cci_returns_series(df):
    fn = get_indicator("cci")
    result = fn(df)
    assert isinstance(result, pd.Series)


def test_williams_r_returns_series(df):
    fn = get_indicator("williams_r")
    result = fn(df)
    assert isinstance(result, pd.Series)


def test_obv_returns_series(df):
    fn = get_indicator("obv")
    result = fn(df)
    assert isinstance(result, pd.Series)


def test_supertrend_returns_dataframe(df):
    fn = get_indicator("supertrend")
    result = fn(df)
    assert isinstance(result, pd.DataFrame)
    assert any(c.startswith("SUPERT_") for c in result.columns)


def test_price_vs_resistance_returns_series(df):
    fn = get_indicator("price_vs_resistance")
    result = fn(df)
    assert isinstance(result, pd.Series)
    assert len(result) == len(df)


def test_get_indicator_unknown_raises():
    with pytest.raises(KeyError, match="not in indicator registry"):
        get_indicator("nonexistent_indicator")


def test_sdk_get_indicator_by_name():
    from core.sdk import get_indicator_by_name
    fn = get_indicator_by_name("rsi")
    assert callable(fn)


def test_sdk_get_indicator_by_name_unknown_raises():
    from core.sdk import get_indicator_by_name
    with pytest.raises(KeyError):
        get_indicator_by_name("nonexistent")


def test_sdk_patterns_detect_candlestick():
    from core.sdk import Patterns
    import pandas as pd
    # hammer: open=100, close=98, high=100, low=90 → body=2, lower_shadow=8
    df = pd.DataFrame({
        "open": [100.0], "high": [100.0], "low": [90.0], "close": [98.0],
        "volume": [100_000],
        "ts": pd.date_range("2026-01-01", periods=1),
        "symbol": ["TEST"],
    })
    result = Patterns.detect_candlestick(df, "hammer")
    assert result is not None
    assert "confidence" in result
