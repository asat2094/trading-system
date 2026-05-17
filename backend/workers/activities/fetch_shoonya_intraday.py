import asyncio
from temporalio import activity
from core.logging import get_logger

log = get_logger(__name__)


@activity.defn(name="fetch_shoonya_intraday")
async def activity_fn(symbol: str, date_str: str) -> dict:
    log.info("fetch_shoonya_intraday_start", symbol=symbol, date=date_str)
    # Shoonya adapter not yet implemented — stub returns empty
    log.warning("fetch_shoonya_intraday_stub", symbol=symbol)
    return {"rows": 0, "symbol": symbol, "date": date_str}
