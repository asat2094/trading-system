"""One-shot seed script: NSE stocks + 2026 trading calendar.

Run from repo root:
    cd backend && PYTHONPATH=. python scripts/seed.py
"""
import asyncio
import sys
import os

# Load .env from repo root
from pathlib import Path
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)


async def main() -> None:
    import structlog
    from core.logging import setup_logging
    setup_logging()
    log = structlog.get_logger(__name__)

    # Seed NSE stocks
    log.info("seed_start", step="stocks")
    try:
        from workers.activities.seed_stocks import activity_fn as seed_stocks
        result = await seed_stocks("NSE")
        log.info("seed_stocks_done", **result)
    except Exception as exc:
        log.error("seed_stocks_failed", error=str(exc))
        sys.exit(1)

    # Seed 2026 + 2025 trading calendars
    from workers.activities.sync_trading_calendar import activity_fn as sync_cal
    for year in (2025, 2026):
        log.info("seed_start", step=f"calendar_{year}")
        try:
            result = await sync_cal(year)
            log.info("seed_calendar_done", **result)
        except Exception as exc:
            log.error("seed_calendar_failed", year=year, error=str(exc))
            sys.exit(1)

    log.info("seed_complete")


if __name__ == "__main__":
    asyncio.run(main())
