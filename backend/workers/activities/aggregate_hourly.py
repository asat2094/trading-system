from temporalio import activity
from core.logging import get_logger

log = get_logger(__name__)


@activity.defn(name="aggregate_hourly")
async def activity_fn() -> dict:
    import asyncio
    import psycopg2
    from core.config import settings

    def _aggregate():
        conn = psycopg2.connect(settings.QUESTDB_URL)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ohlcv_hourly
            SELECT ts, symbol, first(open), max(high), min(low), last(close), sum(volume)
            FROM ohlcv_1min
            WHERE ts >= dateadd('h', -2, now())
            SAMPLE BY 1h ALIGN TO CALENDAR TIME ZONE 'Asia/Kolkata'
        """)
        conn.close()

    await asyncio.get_event_loop().run_in_executor(None, _aggregate)
    log.info("aggregate_hourly_complete")
    return {}
