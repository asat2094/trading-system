from datetime import date
from temporalio import activity
from core.logging import get_logger
from core.storage import get_storage
from data.sources.github_eod_source import fetch_github_eod

log = get_logger(__name__)


@activity.defn(name="fetch_github_eod_data")
async def activity_fn(date_str: str | None = None) -> dict:
    import asyncio
    if date_str is None:
        date_str = date.today().strftime("%Y-%m-%d")

    log.info("fetch_github_eod_start", date=date_str)

    df = await asyncio.get_event_loop().run_in_executor(None, fetch_github_eod, date_str)
    if df.empty:
        log.warning("fetch_github_eod_empty", date=date_str)
        return {"rows": 0, "date": date_str}

    year, month, _ = date_str.split("-")
    storage = get_storage()
    path = f"timeframe=1d/year={year}/month={month}/data.parquet"
    await asyncio.get_event_loop().run_in_executor(None, storage.write_parquet, df, path)

    rows_written = await _write_questdb(df, "ohlcv_daily")
    log.info("fetch_github_eod_complete", date=date_str, rows=rows_written)
    return {"rows": rows_written, "date": date_str}


async def _write_questdb(df, table: str) -> int:
    import asyncio
    import psycopg2
    from core.config import settings

    def _write():
        conn = psycopg2.connect(settings.QUESTDB_URL)
        conn.autocommit = True
        cur = conn.cursor()
        rows = 0
        for _, row in df.iterrows():
            cur.execute(
                f"INSERT INTO {table} (ts, symbol, open, high, low, close, volume) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (row["ts"], row["symbol"], row["open"], row["high"],
                 row["low"], row["close"], row["volume"]),
            )
            rows += 1
        conn.close()
        return rows

    return await asyncio.get_event_loop().run_in_executor(None, _write)
