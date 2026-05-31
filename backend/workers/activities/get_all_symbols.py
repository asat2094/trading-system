"""Return all symbols from the stocks table (equities + index symbols)."""
from temporalio import activity
from core.logging import get_logger

log = get_logger(__name__)


@activity.defn(name="get_all_symbols")
async def activity_fn() -> dict:
    from core.db import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT symbol FROM stocks ORDER BY symbol"))
        symbols = [r[0] for r in result.fetchall()]

    log.info("all_symbols_loaded", count=len(symbols))
    return {"symbols": symbols}
