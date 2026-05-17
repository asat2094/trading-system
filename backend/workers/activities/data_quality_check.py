"""Data quality checks — fires alerts into data_quality_alerts table."""
from datetime import date, timedelta
from temporalio import activity
from core.logging import get_logger
from core.db import AsyncSessionLocal
from sqlalchemy import text

log = get_logger(__name__)


@activity.defn(name="data_quality_check")
async def activity_fn() -> dict:
    today = date.today()
    yesterday = today - timedelta(days=1)
    alerts = []

    async with AsyncSessionLocal() as session:
        # Check 1: Stocks with no scan results in last 2 days (proxy for missing OHLCV)
        result = await session.execute(text("""
            SELECT s.symbol FROM stocks s
            WHERE NOT EXISTS (
                SELECT 1 FROM scan_results sr
                WHERE sr.symbol = s.symbol
                  AND sr.run_at >= :since
            )
            LIMIT 20
        """), {"since": yesterday})
        gaps = [r[0] for r in result.fetchall()]
        if gaps:
            alerts.append({"check": "ohlcv_gap", "symbols": gaps[:10], "count": len(gaps)})

        # Check 2: Stocks table populated at all
        result = await session.execute(text("SELECT COUNT(*) FROM stocks"))
        stock_count = result.scalar() or 0
        if stock_count == 0:
            alerts.append({"check": "stocks_table_empty", "count": 0})

        # Check 3: Trading calendar populated for current year
        result = await session.execute(text("""
            SELECT COUNT(*) FROM trading_calendar
            WHERE EXTRACT(YEAR FROM date) = :year AND exchange = 'NSE'
        """), {"year": today.year})
        cal_count = result.scalar() or 0
        if cal_count < 200:
            alerts.append({"check": "trading_calendar_sparse",
                           "year": today.year, "rows": cal_count})

        # Insert alerts
        import json
        for alert in alerts:
            await session.execute(text("""
                INSERT INTO data_quality_alerts (check_name, detail)
                VALUES (:name, :detail::jsonb)
            """), {"name": alert["check"], "detail": json.dumps(alert)})
        await session.commit()

    if alerts:
        log.warning("data_quality_alerts_fired", count=len(alerts), alerts=alerts)
    else:
        log.info("data_quality_check_passed", stocks=stock_count)
    return {"alerts": len(alerts)}
