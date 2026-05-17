import asyncio
from temporalio import activity
from core.logging import get_logger
from core.storage import get_storage
import psycopg2

log = get_logger(__name__)


@activity.defn(name="questdb_retention_sweep")
async def activity_fn(retention_days: int = 60) -> dict:
    from core.config import settings
    from datetime import date, timedelta
    import duckdb

    cutoff = date.today() - timedelta(days=retention_days)
    storage = get_storage()

    try:
        parquet_count = duckdb.query(
            f"SELECT COUNT(*) FROM read_parquet('{storage.full_path(\"timeframe=1min/**/*.parquet\")}', "
            f"hive_partitioning=true) WHERE ts::date < '{cutoff}'"
        ).fetchone()[0]
    except Exception as exc:
        log.error("parquet_verify_failed", error=str(exc))
        return {"dropped": 0, "error": str(exc)}

    if parquet_count == 0:
        log.warning("parquet_missing_for_retention_drop", cutoff=str(cutoff))
        return {"dropped": 0, "reason": "no_parquet_data"}

    def _drop():
        conn = psycopg2.connect(settings.QUESTDB_URL)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(f"ALTER TABLE ohlcv_1min DROP PARTITION WHERE ts < '{cutoff}T00:00:00'")
        conn.close()

    await asyncio.get_event_loop().run_in_executor(None, _drop)
    log.info("questdb_partition_dropped", cutoff=str(cutoff), parquet_rows_verified=parquet_count)
    return {"dropped": 1, "cutoff": str(cutoff)}
