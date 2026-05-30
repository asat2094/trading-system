"""On-demand Temporal workflow: fetch FnO snapshot for a given symbol."""
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from workers.activities.fetch_fno_snapshot import fetch_fno_snapshot_activity


@workflow.defn(name="FnoSnapshotWorkflow")
class FnoSnapshotWorkflow:
    """
    Short-lived on-demand workflow triggered by the FastAPI /fno/snapshot endpoint.
    Runs fetch_fno_snapshot_activity once and returns the result dict.
    """

    @workflow.run
    async def run(self, symbol: str, strikes: int) -> dict:
        return await workflow.execute_activity(
            fetch_fno_snapshot_activity,
            args=[symbol, strikes],
            schedule_to_close_timeout=timedelta(seconds=90),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=2, backoff_coefficient=1.5),
        )
