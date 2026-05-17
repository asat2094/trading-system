from datetime import date, timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.logging import get_logger


@workflow.defn
class BackfillWorkflow:
    @workflow.run
    async def run(self, symbol: str, from_date: str, to_date: str) -> dict:
        log = get_logger(__name__)
        log.info("backfill_start", symbol=symbol, from_date=from_date, to_date=to_date)

        start = date.fromisoformat(from_date)
        end = date.fromisoformat(to_date)
        current = start
        rows_total = 0

        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            result = await workflow.execute_activity(
                "fetch_github_eod_data",
                args=[date_str],
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
            )
            rows_total += result.get("rows", 0)
            current += timedelta(days=1)

        log.info("backfill_complete", symbol=symbol, rows=rows_total)
        return {"symbol": symbol, "rows": rows_total}
