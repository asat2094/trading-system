import asyncio
from temporalio import activity
from core.logging import get_logger
from core.storage import get_storage
from data.sources.yfinance_source import fetch_daily_ohlcv
from core.sdk import MarketData

log = get_logger(__name__)


@activity.defn(name="fetch_yfinance_daily")
async def activity_fn() -> dict:
    md = MarketData()
    symbols = await md.universe()
    storage = get_storage()
    total = 0
    for sym in symbols[:50]:
        ticker = f"{sym}.NS"
        df = await asyncio.get_event_loop().run_in_executor(
            None, fetch_daily_ohlcv, ticker, "2024-01-01", "today"
        )
        if not df.empty:
            storage.write_parquet(df, f"timeframe=1d/year=2024/month=01/yf_{sym}.parquet")
            total += len(df)
    log.info("fetch_yfinance_daily_complete", rows=total)
    return {"rows": total}
