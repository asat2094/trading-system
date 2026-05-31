"""Return the most recent date that has 1-min data in QuestDB.

Used by DailyRefreshWorkflow to detect whether today's data is already
present (idempotency guard — prevents double-fetching on catch-up runs).
"""
from temporalio import activity
from core.logging import get_logger

log = get_logger(__name__)


@activity.defn(name="get_latest_data_date")
async def activity_fn() -> dict:
    """
    Returns:
        {"latest_date": "YYYY-MM-DD" | null}

    Queries LATEST ON ts PARTITION BY symbol on a fixed canary set of
    liquid symbols (always present if any data exists) and returns the
    most recent date seen. Fast — uses partition index, no full scan.
    """
    import asyncio
    import psycopg2
    from core.config import settings

    # Liquid symbols that are reliably present whenever there is any data
    CANARIES = ["RELIANCE", "HDFCBANK", "INFY", "TCS", "ICICIBANK"]

    def _query() -> str | None:
        conn = psycopg2.connect(settings.QUESTDB_URL)
        try:
            sym_list = "', '".join(CANARIES)
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT MAX(ts) FROM ohlcv_1min "
                    f"WHERE symbol IN ('{sym_list}') "
                    f"LATEST ON ts PARTITION BY symbol"
                )
                row = cur.fetchone()
                if row and row[0]:
                    return str(row[0])[:10]   # YYYY-MM-DD
                return None
        finally:
            conn.close()

    latest = await asyncio.get_event_loop().run_in_executor(None, _query)
    log.info("latest_data_date", date=latest)
    return {"latest_date": latest}
