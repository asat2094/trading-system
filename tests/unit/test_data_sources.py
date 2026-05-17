import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from data.sources.yfinance_source import fetch_daily_ohlcv
from data.sources.github_eod_source import fetch_github_eod

def test_yfinance_fetch_returns_normalized_df():
    ticker = "RELIANCE.NS"
    arrays = [
        ["Open", "High", "Low", "Close", "Adj Close", "Volume"],
        [ticker, ticker, ticker, ticker, ticker, ticker],
    ]
    mi = pd.MultiIndex.from_arrays(arrays)
    mock_df = pd.DataFrame(
        [[2800.0, 2810.0, 2795.0, 2805.0, 2805.0, 100000]],
        index=pd.to_datetime(["2024-01-02"]),
        columns=mi,
    )
    mock_df.index.name = "Date"

    with patch("yfinance.download", return_value=mock_df):
        result = fetch_daily_ohlcv("RELIANCE.NS", "2024-01-01", "2024-01-03")

    assert set(result.columns) == {"ts", "symbol", "open", "high", "low", "close", "volume", "adjusted_close"}
    assert result["symbol"].iloc[0] == "RELIANCE"

def test_yfinance_retries_on_failure():
    ticker = "RELIANCE.NS"
    arrays = [
        ["Open", "High", "Low", "Close", "Adj Close", "Volume"],
        [ticker, ticker, ticker, ticker, ticker, ticker],
    ]
    mi = pd.MultiIndex.from_arrays(arrays)
    good_df = pd.DataFrame(
        [[2800.0, 2810.0, 2795.0, 2805.0, 2805.0, 100000]],
        index=pd.to_datetime(["2024-01-02"]),
        columns=mi,
    )
    good_df.index.name = "Date"

    with patch("yfinance.download", side_effect=[Exception("rate limit"), good_df]) as mock_dl:
        with patch("time.sleep"):
            result = fetch_daily_ohlcv("RELIANCE.NS", "2024-01-01", "2024-01-03")
    assert mock_dl.call_count == 2
    assert not result.empty

def test_github_eod_returns_dataframe():
    import io, zipfile
    # Build a real ZIP with NSE Bhavcopy CSV format
    bhavcopy_csv = (
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN\n"
        "RELIANCE,EQ,2800,2810,2795,2805,2805,2790,100000,280500000,02-JAN-2024,1234,INE002A01018\n"
        "TATASTEEL,SM,100,101,99,100,100,98,50000,5000000,02-JAN-2024,500,INE081A01020\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("cm02JAN2024bhav.csv", bhavcopy_csv)
    zip_bytes = buf.getvalue()

    mock_resp = MagicMock()
    mock_resp.read.return_value = zip_bytes
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = fetch_github_eod("2024-01-02")

    assert len(result) == 1  # only EQ series
    assert result["symbol"].iloc[0] == "RELIANCE"
