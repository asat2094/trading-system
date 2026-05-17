"""Seed the stocks table from NSE/BSE public equity list."""
from temporalio import activity
from core.logging import get_logger

log = get_logger(__name__)


@activity.defn(name="seed_stocks")
async def activity_fn(exchange: str = "NSE") -> dict:
    import asyncio
    from data.sources.yfinance_source import fetch_universe
    from core.db import AsyncSessionLocal
    from sqlalchemy import text

    log.info("seed_stocks_start", exchange=exchange)

    df = await asyncio.get_event_loop().run_in_executor(None, fetch_universe, exchange)
    if df.empty:
        log.warning("seed_stocks_empty", exchange=exchange)
        return {"upserted": 0, "exchange": exchange}

    async with AsyncSessionLocal() as session:
        upserted = 0
        for _, row in df.iterrows():
            await session.execute(
                text("""
                    INSERT INTO stocks (symbol, name, exchange)
                    VALUES (:symbol, :name, :exchange)
                    ON CONFLICT (symbol) DO UPDATE
                    SET name = EXCLUDED.name, exchange = EXCLUDED.exchange
                """),
                {"symbol": row["symbol"], "name": row["name"], "exchange": exchange},
            )
            upserted += 1
        await session.commit()

    log.info("seed_stocks_complete", exchange=exchange, upserted=upserted)
    return {"upserted": upserted, "exchange": exchange}
