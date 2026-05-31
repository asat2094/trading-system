"""Return the full Nifty500 + FnO trading universe."""
from temporalio import activity
from core.logging import get_logger

log = get_logger(__name__)


@activity.defn(name="get_trading_universe")
async def activity_fn() -> dict:
    from core.universe import build_trading_universe
    symbols = build_trading_universe()
    log.info("trading_universe_loaded", count=len(symbols))
    return {"symbols": symbols}
