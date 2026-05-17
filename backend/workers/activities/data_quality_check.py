from datetime import date
from temporalio import activity
from core.logging import get_logger
from core.db import AsyncSessionLocal
from sqlalchemy import text

log = get_logger(__name__)


@activity.defn(name="data_quality_check")
async def activity_fn() -> dict:
    today = date.today()
    alerts = []

    async with AsyncSessionLocal() as session:
        result = await session.execute(text("""
            SELECT s.symbol FROM stocks s
            WHERE NOT EXISTS (
                SELECT 1 FROM scan_results sr
                WHERE sr.symbol = s.symbol AND sr.run_at::date = :today
            )
            LIMIT 10
        """), {"today": today})
        gaps = [r[0] for r in result.fetchall()]
        if gaps:
            alerts.append({"check": "ohlcv_gap", "symbols": gaps})

        result = await session.execute(text("""
            SELECT COUNT(*) FROM stocks
            WHERE updated_at < now() - INTERVAL '7 days'
        """))
        stale_count = result.scalar()
        if stale_count > 0:
            alerts.append({"check": "market_cap_stale", "count": stale_count})

        for alert in alerts:
            await session.execute(text("""
                INSERT INTO data_quality_alerts (check_name, detail)
                VALUES (:name, :detail::jsonb)
            """), {"name": alert["check"], "detail": str(alert)})
        await session.commit()

    if alerts:
        log.warning("data_quality_alerts_fired", count=len(alerts), alerts=alerts)
    else:
        log.info("data_quality_check_passed")
    return {"alerts": len(alerts)}
