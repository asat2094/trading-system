import asyncio
from datetime import date
from temporalio import activity
from core.logging import get_logger
from core.db import AsyncSessionLocal
from data.sources.nse_public_source import fetch_preopen_gainers
from sqlalchemy import text

log = get_logger(__name__)


@activity.defn(name="fetch_nse_preopen")
async def activity_fn(collection_label: str = "default", top_n: int = 20) -> dict:
    today = date.today().isoformat()
    log.info("fetch_nse_preopen_start", label=collection_label, date=today)

    df = await asyncio.get_event_loop().run_in_executor(None, fetch_preopen_gainers, top_n)
    if df.empty:
        log.warning("fetch_nse_preopen_empty", date=today, label=collection_label)
        return {"rows": 0}

    async with AsyncSessionLocal() as session:
        await session.execute(text("""
            INSERT INTO market_event_types (name, description, source, collection_windows)
            VALUES ('premarket_gainers', 'NSE pre-open top gainers', 'nse_public',
                    '[{"cron":"9 9 * * 1-5","label":"order_open","delay_s":0},
                      {"cron":"11 9 * * 1-5","label":"iep_final","delay_s":60}]'::jsonb)
            ON CONFLICT (name) DO NOTHING
        """))

        rows = 0
        for rank, row in enumerate(df.itertuples(), start=1):
            await session.execute(text("""
                INSERT INTO market_events
                    (event_type, collection_label, date, symbol, rank, data)
                VALUES
                    ('premarket_gainers', :label, :date, :symbol, :rank, :data)
                ON CONFLICT (event_type, collection_label, date, symbol) DO UPDATE
                    SET data = EXCLUDED.data, captured_at = now()
            """), {
                "label": collection_label,
                "date": today,
                "symbol": row.symbol,
                "rank": rank,
                "data": f'{{"pre_price":{row.pre_price},"pre_change_pct":{row.pre_change_pct},"pre_volume":{row.pre_volume}}}',
            })
            rows += 1
        await session.commit()

    log.info("fetch_nse_preopen_complete", rows=rows, label=collection_label)
    return {"rows": rows}
