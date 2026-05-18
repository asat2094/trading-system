"""Populate trading_calendar table for a given year from NSE holiday data."""
from temporalio import activity
from core.logging import get_logger

log = get_logger(__name__)


@activity.defn(name="sync_trading_calendar")
async def activity_fn(year: int) -> dict:
    import asyncio
    from data.sources.nse_public_source import fetch_trading_calendar
    from core.db import AsyncSessionLocal
    from sqlalchemy import text

    log.info("sync_trading_calendar_start", year=year)

    from datetime import time as dt_time

    df = await asyncio.get_event_loop().run_in_executor(None, fetch_trading_calendar, year)

    def _to_time(val):
        if val is None:
            return None
        if isinstance(val, dt_time):
            return val
        h, m, s = str(val).split(":")
        return dt_time(int(h), int(m), int(s))

    async with AsyncSessionLocal() as session:
        upserted = 0
        for _, row in df.iterrows():
            await session.execute(
                text("""
                    INSERT INTO trading_calendar
                        (date, exchange, is_trading, session_type, open_time, close_time, minutes)
                    VALUES
                        (:date, :exchange, :is_trading, :session_type, :open_time, :close_time, :minutes)
                    ON CONFLICT (date, exchange) DO UPDATE SET
                        is_trading   = EXCLUDED.is_trading,
                        session_type = EXCLUDED.session_type,
                        open_time    = EXCLUDED.open_time,
                        close_time   = EXCLUDED.close_time,
                        minutes      = EXCLUDED.minutes
                """),
                {
                    "date": row["date"],
                    "exchange": row["exchange"],
                    "is_trading": bool(row["is_trading"]),
                    "session_type": row["session_type"],
                    "open_time": _to_time(row["open_time"]) if row["is_trading"] else None,
                    "close_time": _to_time(row["close_time"]) if row["is_trading"] else None,
                    "minutes": int(row["minutes"]),
                },
            )
            upserted += 1
        await session.commit()

    trading_days = int(df["is_trading"].sum())
    log.info("sync_trading_calendar_complete", year=year, rows=upserted, trading_days=trading_days)
    return {"year": year, "rows": upserted, "trading_days": trading_days}
