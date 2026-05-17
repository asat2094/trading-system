# Template for new activities — copy and rename (without leading underscore)
from temporalio import activity
from core.logging import get_logger

log = get_logger(__name__)

@activity.defn(name="template_activity")  # CHANGE: unique name required
async def activity_fn() -> None:
    """Activity body. Use MarketData/Indicators/Patterns/Scanner from core.sdk only."""
    log.info("template_activity_start")
    log.info("template_activity_complete")
