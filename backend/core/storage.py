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
        hp_flag = "true" if hive_partitioning else "false"
        query = f"SELECT * FROM read_parquet('{full_pattern}', hive_partitioning={hp_flag})"

        if filters:
            clauses = " AND ".join(f"{k}={v!r}" for k, v in filters.items())
            query += f" WHERE {clauses}"

        return duckdb.query(query).df()


class S3Storage:
    """Stub — activate by setting PARQUET_BASE_PATH=s3://bucket/raw."""
    def __init__(self, base_path: str):
        self._base = base_path

    def full_path(self, relative: str) -> str:
        return f"{self._base}/{relative}"

    def write_parquet(self, df: pd.DataFrame, path: str) -> None:
        conn = duckdb.connect()
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        full = self.full_path(path)
        table = pa.Table.from_pandas(df)
        pq.write_table(table, full)

    def read_parquet(self, path_pattern: str, **kwargs) -> pd.DataFrame:
        conn = duckdb.connect()
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        full_pattern = self.full_path(path_pattern)
        return conn.query(f"SELECT * FROM read_parquet('{full_pattern}')").df()


def get_storage() -> Storage:
    from core.config import settings
    if settings.PARQUET_BASE_PATH.startswith("s3://"):
        return S3Storage(settings.PARQUET_BASE_PATH)
    return LocalStorage(settings.PARQUET_BASE_PATH)
