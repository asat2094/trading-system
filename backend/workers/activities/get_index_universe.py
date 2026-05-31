"""Return the full index universe (NSE + BSE indices) in QuestDB symbol format."""
from temporalio import activity
from core.logging import get_logger

log = get_logger(__name__)


@activity.defn(name="get_index_universe")
async def activity_fn() -> dict:
    """
    Returns:
        {"symbols": ["NSE_NIFTY_50", "BSE_SENSEX", ...]}

    Symbols are in QuestDB naming format (EXCHANGE_TRADINGSYMBOL_SPACES_REPLACED).
    List is sourced from core.universe.INDEX_UNIVERSE — same list used by the
    original index download scripts.
    """
    from core.universe import get_index_questdb_symbols
    symbols = get_index_questdb_symbols()
    log.info("index_universe_loaded", count=len(symbols))
    return {"symbols": symbols}
