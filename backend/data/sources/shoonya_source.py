import pandas as pd
from core.logging import get_logger

log = get_logger(__name__)


async def fetch_intraday_1min(symbol: str, date_str: str) -> pd.DataFrame:
    try:
        from NorenRestApiPy.NorenApi import NorenApi
    except ImportError:
        log.error("shoonya_not_installed", msg="pip install NorenRestApiPy")
        return pd.DataFrame()

    log.warning("shoonya_fetch_not_implemented", symbol=symbol, date=date_str)
    return pd.DataFrame()
