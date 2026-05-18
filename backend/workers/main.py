"""Temporal worker entrypoint — registers all activities and workflows."""
import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from core.config import settings
from core.logging import setup_logging
from workers.registry import register_all
from workers.workflows.backfill import BackfillWorkflow
from workers.workflows.daily_eod import DailyEodWorkflow
from workers.workflows.intraday import Intraday1MinCollectorWorkflow
from workers.workflows.maintenance import (
    MarketCapRefreshWorkflow,
    RetentionSweepWorkflow,
    TradingCalendarSyncWorkflow,
)
from workers.workflows.market_events import MarketEventCollectorWorkflow


async def main() -> None:
    setup_logging()
    log = __import__("structlog").get_logger(__name__)

    client = await Client.connect(
        settings.TEMPORAL_HOST,
        namespace=settings.TEMPORAL_NAMESPACE,
    )

    activities_data = register_all()
    activity_fns = [fn for fn, _name, _stem in activities_data]
    log.info("worker_activities_loaded", count=len(activity_fns))

    worker = Worker(
        client,
        task_queue="trading-main",
        workflows=[
            DailyEodWorkflow,
            Intraday1MinCollectorWorkflow,
            MarketEventCollectorWorkflow,
            BackfillWorkflow,
            RetentionSweepWorkflow,
            MarketCapRefreshWorkflow,
            TradingCalendarSyncWorkflow,
        ],
        activities=activity_fns,
    )

    log.info("worker_starting", task_queue="trading-main")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
