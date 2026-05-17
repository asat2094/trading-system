"""Fetch 1-minute intraday OHLCV via yfinance and persist to QuestDB."""
import asyncio
from datetime import date
from temporalio import activity
from core.logging import get_logger
from core.metrics import ingestion_rows, ingestion_failures

log = get_logger(__name__)


@activity.defn(name="fetch_shoonya_intraday")
async def activity_fn(symbol: str, date_str: str | None = None, interval: str = "1min") -> dict:
    from data.sources.shoonya_source import fetch_intraday
    from core.storage import get_storage

    if date_str is None:
        date_str = date.today().isoformat()

    log.info("fetch_intraday_start", symbol=symbol, date=date_str, interval=interval)

    df = await asyncio.get_event_loop().run_in_executor(
        None, fetch_intraday, symbol, date_str, interval
    )
    if df.empty:
        log.warning("fetch_intraday_empty", symbol=symbol, date=date_str)
        ingestion_failures.labels(source="yfinance_intraday").inc()
        return {"rows": 0, "symbol": symbol, "date": date_str}

    # Persist to Parquet
    year, month, day = date_str.split("-")
    storage = get_storage()
    path = f"timeframe={interval}/year={year}/month={month}/{day}_{symbol}.parquet"
    try:
        storage.write_parquet(df, path)
    except Exception as exc:
        log.warning("intraday_parquet_write_failed", symbol=symbol, error=str(exc))

    # Write to QuestDB ohlcv_1min
    rows_written = await _write_questdb(df)
    ingestion_rows.labels(source="yfinance_intraday", timeframe=interval).inc(rows_written)
    log.info("fetch_intraday_complete", symbol=symbol, date=date_str, rows=rows_written)
    return {"rows": rows_written, "symbol": symbol, "date": date_str}


async def _write_questdb(df) -> int:
    import psycopg2
    from core.config import settings

    def _write():
        conn = psycopg2.connect(settings.QUESTDB_URL)
        conn.autocommit = True
        cur = conn.cursor()
        rows = 0
        for _, row in df.iterrows():
            cur.execute(
                "INSERT INTO ohlcv_1min (ts, symbol, open, high, low, close, volume) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (row["ts"], row["symbol"],
                 row["open"], row["high"], row["low"], row["close"], int(row["volume"])),
            )
            rows += 1
        conn.close()
        return rows

    return await asyncio.get_event_loop().run_in_executor(None, _write)
