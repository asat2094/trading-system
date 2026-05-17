"""Fetch daily OHLCV for all NSE stocks via yfinance and persist to Parquet + QuestDB."""
import asyncio
from datetime import date, timedelta
from temporalio import activity
from core.logging import get_logger
from core.storage import get_storage
from core.metrics import ingestion_rows, ingestion_failures
from data.sources.yfinance_source import fetch_daily_ohlcv

log = get_logger(__name__)

_BATCH_SIZE = 20  # yfinance parallel requests


@activity.defn(name="fetch_yfinance_daily")
async def activity_fn(
    lookback_days: int = 5,
    symbols: list[str] | None = None,
) -> dict:
    from core.sdk import MarketData
    md = MarketData()

    if symbols:
        all_symbols = symbols
    else:
        all_symbols = await md.universe()

    if not all_symbols:
        log.warning("fetch_yfinance_daily_no_symbols")
        return {"rows": 0, "symbols": 0}

    storage = get_storage()
    to_dt = date.today().isoformat()
    from_dt = (date.today() - timedelta(days=lookback_days)).isoformat()

    total_rows = 0
    failed = 0

    # Process in batches to avoid hammering yfinance
    for i in range(0, len(all_symbols), _BATCH_SIZE):
        batch = all_symbols[i:i + _BATCH_SIZE]
        tasks = [
            asyncio.get_event_loop().run_in_executor(
                None, fetch_daily_ohlcv, f"{sym}.NS", from_dt, to_dt
            )
            for sym in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for sym, result in zip(batch, results):
            if isinstance(result, Exception):
                log.warning("yfinance_symbol_failed", symbol=sym, error=str(result))
                ingestion_failures.labels(source="yfinance_daily").inc()
                failed += 1
                continue

            df = result
            if df.empty:
                continue

            year = df["ts"].iloc[0].strftime("%Y")
            month = df["ts"].iloc[0].strftime("%m")
            path = f"timeframe=1d/year={year}/month={month}/yf_{sym}.parquet"
            try:
                storage.write_parquet(df, path)
            except Exception as exc:
                log.warning("yfinance_parquet_write_failed", symbol=sym, error=str(exc))

            total_rows += len(df)
            ingestion_rows.labels(source="yfinance_daily", timeframe="1d").inc(len(df))

        # Brief pause between batches — be polite to yfinance
        if i + _BATCH_SIZE < len(all_symbols):
            await asyncio.sleep(0.5)

    log.info("fetch_yfinance_daily_complete",
             symbols_attempted=len(all_symbols), rows=total_rows, failed=failed)
    return {"rows": total_rows, "symbols": len(all_symbols), "failed": failed}
