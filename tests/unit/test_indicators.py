import pytest
import pandas as pd
import numpy as np
from core.sdk import Indicators
from technical.indicators.registry import get_indicator, list_indicators

def make_ohlcv(n: int = 50) -> pd.DataFrame:
    np.random.seed(42)
    close = 2800 + np.cumsum(np.random.randn(n) * 10)
    return pd.DataFrame({
        "ts": pd.date_range("2024-01-01", periods=n, freq="1min"),
        "open":   close - 5,
        "high":   close + 10,
        "low":    close - 10,
        "close":  close,
        "volume": np.random.randint(50000, 200000, n),
    })

def test_rsi_returns_series_length_matches_input():
    df = make_ohlcv(50)
    result = Indicators.rsi(df, period=14)
    assert len(result) == len(df)
    # pandas_ta uses EMA (Wilder) smoothing — only the first row is NaN
    assert result.iloc[0:1].isna().all()
    assert result.dropna().shape[0] > 0
    assert (result.dropna() >= 0).all()
    assert (result.dropna() <= 100).all()

def test_ema_period_20_returns_series():
    df = make_ohlcv(50)
    result = Indicators.ema(df, period=20)
    assert len(result) == len(df)
    assert result.dropna().shape[0] > 0

def test_macd_returns_dataframe_with_required_columns():
    df = make_ohlcv(100)
    result = Indicators.macd(df)
    assert result is not None
    assert any("MACD" in str(c) for c in result.columns)

def test_bollinger_bands_returns_upper_lower():
    df = make_ohlcv(50)
    result = Indicators.bollinger_bands(df, period=20, std=2.0)
    col_names = [str(c).lower() for c in result.columns]
    assert any("upper" in c or "bbu" in c for c in col_names)
    assert any("lower" in c or "bbl" in c for c in col_names)

def test_registry_get_indicator_returns_callable():
    fn = get_indicator("rsi")
    assert callable(fn)

def test_registry_unknown_indicator_raises():
    with pytest.raises(KeyError, match="unknown_indicator"):
        get_indicator("unknown_indicator")

def test_registry_list_includes_core_indicators():
    indicators = list_indicators()
    assert "rsi" in indicators
    assert "macd" in indicators
    assert "ema" in indicators
    assert "vwap" in indicators

def test_vwap_returns_series_aligned_with_input():
    df = make_ohlcv(5)
    result = Indicators.vwap(df)
    assert len(result) == len(df)
    assert result.dropna().shape[0] > 0

def test_obv_returns_series():
    df = make_ohlcv(5)
    result = Indicators.obv(df)
    assert isinstance(result, pd.Series)
    assert len(result) == len(df)
