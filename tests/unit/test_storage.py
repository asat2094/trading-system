import pandas as pd
import tempfile
import pytest
from pathlib import Path
from core.storage import LocalStorage, S3Storage, get_storage

def test_local_storage_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        storage = LocalStorage(base_path=tmp)
        df = pd.DataFrame({
            "ts": pd.to_datetime(["2024-01-02 09:15:00", "2024-01-02 09:16:00"]),
            "symbol": ["RELIANCE", "RELIANCE"],
            "open": [2800.0, 2802.0],
            "high": [2810.0, 2808.0],
            "low":  [2795.0, 2798.0],
            "close":[2805.0, 2803.0],
            "volume":[100000, 95000],
        })

        path = "timeframe=1min/year=2024/month=01/data.parquet"
        storage.write_parquet(df, path)
        result = storage.read_parquet("timeframe=1min/year=2024/month=01/*.parquet")

        assert len(result) == 2
        assert set(result.columns) == set(df.columns)

def test_local_storage_hive_partition_pruning():
    with tempfile.TemporaryDirectory() as tmp:
        storage = LocalStorage(base_path=tmp)
        df = pd.DataFrame({
            "ts": pd.to_datetime(["2024-01-02"]),
            "symbol": ["INFY"],
            "open": [1500.0], "high": [1510.0],
            "low": [1495.0], "close": [1505.0], "volume": [50000],
        })
        storage.write_parquet(df, "timeframe=1min/year=2024/month=01/data.parquet")

        result = storage.read_parquet(
            "timeframe=1min/**/*.parquet",
            hive_partitioning=True,
            filters={"year": 2024, "month": 1},
        )
        assert len(result) == 1

def test_s3_storage_raises_not_implemented():
    s3 = S3Storage("s3://bucket/raw")
    df = pd.DataFrame({"a": [1]})
    with pytest.raises(NotImplementedError):
        s3.write_parquet(df, "foo/bar.parquet")
    with pytest.raises(NotImplementedError):
        s3.read_parquet("foo/**/*.parquet")

def test_filter_key_allowlist_rejects_unknown():
    with tempfile.TemporaryDirectory() as tmp:
        storage = LocalStorage(base_path=tmp)
        df = pd.DataFrame({
            "ts": pd.to_datetime(["2024-01-02"]),
            "symbol": ["INFY"],
            "open": [1500.0], "high": [1510.0],
            "low": [1495.0], "close": [1505.0], "volume": [50000],
        })
        storage.write_parquet(df, "timeframe=1min/year=2024/month=01/data.parquet")
        with pytest.raises(ValueError, match="Unknown filter columns"):
            storage.read_parquet(
                "timeframe=1min/**/*.parquet",
                hive_partitioning=True,
                filters={"year; DROP TABLE x": 2024},
            )

def test_filter_value_sql_metacharacters_treated_as_literal():
    """Filter values with SQL metacharacters must be passed as bind params, not raise."""
    with tempfile.TemporaryDirectory() as tmp:
        storage = LocalStorage(base_path=tmp)
        df = pd.DataFrame({
            "ts": pd.to_datetime(["2024-01-02"]),
            "symbol": ["INFY"],
            "open": [1500.0], "high": [1510.0],
            "low": [1495.0], "close": [1505.0], "volume": [50000],
        })
        storage.write_parquet(df, "timeframe=1min/year=2024/month=01/data.parquet")
        # This symbol value won't match — query should return empty, not raise
        result = storage.read_parquet(
            "timeframe=1min/year=2024/month=01/*.parquet",
            filters={"symbol": "'; DROP TABLE ohlcv--"},
        )
        assert len(result) == 0
