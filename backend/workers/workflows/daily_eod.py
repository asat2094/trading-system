from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.logging import get_logger


@workflow.defn
class DailyEodWorkflow:
    @workflow.run
    async def run(self) -> None:
        log = get_logger(__name__)
        log.info("daily_eod_start")

        for activity_name, timeout_min, max_attempts in [
            ("fetch_github_eod_data",  10, 3),
            ("fetch_yfinance_daily",   15, 2),
            ("aggregate_hourly",       20, 2),
            ("compute_indicators",     30, 2),
            ("run_scanner_presets",    20, 2),
            ("invalidate_cache",        2, 1),
            ("data_quality_check",      5, 1),
        ]:
            await workflow.execute_activity(
                activity_name,
                start_to_close_timeout=timedelta(minutes=timeout_min),
                retry_policy=RetryPolicy(
                    maximum_attempts=max_attempts,
                    initial_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                ),
            )

        log.info("daily_eod_complete")
