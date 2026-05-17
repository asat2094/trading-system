import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from data.sources.yfinance_source import fetch_daily_ohlcv
from data.sources.github_eod_source import fetch_github_eod

def test_yfinance_fetch_returns_normalized_df():
    mock_df = pd.DataFrame({
        "Open": [2800.0], "High": [2810.0], "Low": [2795.0],
        "Close": [2805.0], "Adj Close": [2805.0], "Volume": [100000],
    }, index=pd.to_datetime(["2024-01-02"]))
    mock_df.index.name = "Date"

    with patch("yfinance.download", return_value=mock_df):
        result = fetch_daily_ohlcv("RELIANCE.NS", "2024-01-01", "2024-01-03")

    assert set(result.columns) == {"ts", "symbol", "open", "high", "low", "close", "volume", "adjusted_close"}
    assert result["symbol"].iloc[0] == "RELIANCE"

def test_yfinance_retries_on_failure():
    with patch("yfinance.download", side_effect=[Exception("rate limit"), pd.DataFrame()]) as mock_dl:
        with patch("time.sleep"):
            result = fetch_daily_ohlcv("RELIANCE.NS", "2024-01-01", "2024-01-03")
    assert mock_dl.call_count == 2

def test_github_eod_returns_dataframe():
    mock_csv = "Symbol,Date,Open,High,Low,Close,Volume\nRELIANCE,2024-01-02,2800,2810,2795,2805,100000\n"
    with patch("httpx.get") as mock_get:
        mock_get.return_value.text = mock_csv
        mock_get.return_value.raise_for_status = MagicMock()
        result = fetch_github_eod("2024-01-02")
    assert len(result) == 1
    assert result["symbol"].iloc[0] == "RELIANCE"
