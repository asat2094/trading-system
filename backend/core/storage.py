from typing import Protocol, runtime_checkable
import pandas as pd
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path


@runtime_checkable
class Storage(Protocol):
    def read_parquet(self, path_pattern: str, **kwargs) -> pd.DataFrame: ...
    def write_parquet(self, df: pd.DataFrame, path: str) -> None: ...
    def full_path(self, relative: str) -> str: ...


class LocalStorage:
    def __init__(self, base_path: str | None = None):
        from core.config import settings
        self._base = Path(base_path or settings.PARQUET_BASE_PATH)

    def full_path(self, relative: str) -> str:
        return str(self._base / relative)

    def write_parquet(self, df: pd.DataFrame, path: str) -> None:
        full = self._base / path
        full.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(df)
        pq.write_table(table, full, compression="snappy")

    def read_parquet(
        self,
        path_pattern: str,
        hive_partitioning: bool = False,
        filters: dict | None = None,
    ) -> pd.DataFrame:
        full_pattern = str(self._base / path_pattern)
        conn = duckdb.connect()

        # Build base query with parameterized path
        hive_flag = "true" if hive_partitioning else "false"
        base_sql = f"SELECT * FROM read_parquet($path, hive_partitioning={hive_flag})"

        if filters:
            _ALLOWED_COLS = frozenset({"year", "month", "timeframe", "symbol", "ts"})
            invalid = set(filters.keys()) - _ALLOWED_COLS
            if invalid:
                raise ValueError(f"Unknown filter columns: {invalid}")
            # Build WHERE clause — keys validated, values parameterized
            where_parts = [f"{k} = ${k}" for k in filters]
            params = {"path": full_pattern, **filters}
            sql = base_sql + " WHERE " + " AND ".join(where_parts)
        else:
            params = {"path": full_pattern}
            sql = base_sql

        return conn.execute(sql, params).df()


class S3Storage:
    """Stub — activate by setting PARQUET_BASE_PATH=s3://bucket/raw."""
    def __init__(self, base_path: str):
        self._base = base_path.rstrip("/")

    def full_path(self, relative: str) -> str:
        return f"{self._base}/{relative}"

    def write_parquet(self, df: pd.DataFrame, path: str) -> None:
        raise NotImplementedError(
            "S3Storage.write_parquet not yet implemented. "
            "Install duckdb httpfs and use DuckDB COPY ... TO 's3://...'"
        )

    def read_parquet(self, path_pattern: str, **kwargs) -> pd.DataFrame:
        raise NotImplementedError(
            "S3Storage.read_parquet not yet implemented. "
            "Configure httpfs credentials and use duckdb.connect() with LOAD httpfs."
        )


def get_storage() -> Storage:
    from core.config import settings
    if settings.PARQUET_BASE_PATH.startswith("s3://"):
        return S3Storage(settings.PARQUET_BASE_PATH)
    return LocalStorage(settings.PARQUET_BASE_PATH)
