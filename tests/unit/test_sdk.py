# tests/unit/test_sdk.py
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, date
from core.sdk import MarketData

@pytest.mark.asyncio
async def test_ohlcv_returns_dataframe_from_questdb():
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=MagicMock(
        fetchall=lambda: [(datetime(2024,1,2,9,15), "RELIANCE", 2800.0, 2810.0, 2795.0, 2805.0, 100000)],
        description=[("ts",), ("symbol",), ("open",), ("high",), ("low",), ("close",), ("volume",)],
    ))
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("core.sdk.get_questdb_conn", return_value=mock_conn):
        md = MarketData()
        df = await md.ohlcv("RELIANCE", "1min",
                            datetime(2024,1,2,9,15), datetime(2024,1,2,15,30))
    assert isinstance(df, pd.DataFrame)
    assert "close" in df.columns

@pytest.mark.asyncio
async def test_ohlcv_falls_back_to_parquet_when_questdb_empty():
    """If QuestDB returns 0 rows, SDK must fall back to DuckDB+Parquet."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = []
    mock_cur.description = [("ts",), ("symbol",), ("open",), ("high",), ("low",), ("close",), ("volume",)]
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    mock_parquet_df = pd.DataFrame({
        "ts": [datetime(2024,1,2,9,15)],
        "symbol": ["RELIANCE"], "open": [2800.0], "high": [2810.0],
        "low": [2795.0], "close": [2805.0], "volume": [100000],
    })
    mock_storage = MagicMock()
    mock_storage.read_parquet.return_value = mock_parquet_df

    with patch("core.sdk.get_questdb_conn", return_value=mock_conn), \
         patch("core.sdk.get_storage", return_value=mock_storage):
        md = MarketData()
        df = await md.ohlcv("RELIANCE", "1min",
                            datetime(2024,1,2,9,15), datetime(2024,1,2,15,30))

    assert len(df) == 1
    mock_storage.read_parquet.assert_called_once()
