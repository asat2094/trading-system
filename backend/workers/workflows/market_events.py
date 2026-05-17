from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from core.logging import get_logger


@workflow.defn
class MarketEventCollectorWorkflow:
    @workflow.run
    async def run(self, event_type: str, collection_label: str, activity_name: str) -> None:
        log = get_logger(__name__)
        log.info("market_event_collector_start", event_type=event_type, label=collection_label)

        try:
            result = await workflow.execute_activity(
                activity_name,
                args=[collection_label],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
            )
            log.info("market_event_collector_complete",
                     event_type=event_type, label=collection_label, result=result)
        except ActivityError as exc:
            log.error("market_event_collector_failed",
                      event_type=event_type, label=collection_label, error=str(exc))
            raise
