from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.logging import get_logger


@workflow.defn
class RetentionSweepWorkflow:
    @workflow.run
    async def run(self, retention_days: int = 60) -> None:
        log = get_logger(__name__)
        log.info("retention_sweep_start")
        await workflow.execute_activity(
            "questdb_retention_sweep",
            args=[retention_days],
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        log.info("retention_sweep_complete")


@workflow.defn
class MarketCapRefreshWorkflow:
    @workflow.run
    async def run(self) -> None:
        await workflow.execute_activity(
            "fetch_yfinance_daily",
            start_to_close_timeout=timedelta(minutes=60),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@workflow.defn
class TradingCalendarSyncWorkflow:
    @workflow.run
    async def run(self, year: int) -> None:
        log = get_logger(__name__)
        log.info("trading_calendar_sync_start", year=year)
        await workflow.execute_activity(
            "sync_trading_calendar",
            args=[year],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        log.info("trading_calendar_sync_complete", year=year)
