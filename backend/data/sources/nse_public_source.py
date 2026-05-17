import httpx
import pandas as pd
from core.logging import get_logger

log = get_logger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com",
}
_PRE_OPEN_MARKET = "https://www.nseindia.com/api/market-turn-overs?key=pre_open_market"


def fetch_preopen_gainers(top_n: int = 20) -> pd.DataFrame:
    with httpx.Client(headers=_HEADERS, follow_redirects=True) as client:
        client.get("https://www.nseindia.com", timeout=10)
        try:
            resp = client.get(_PRE_OPEN_MARKET, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error("nse_preopen_fetch_failed", error=str(exc))
            return pd.DataFrame()

    records = data.get("data", [])
    rows = []
    for item in records:
        rows.append({
            "symbol": item.get("symbol", ""),
            "pre_price": item.get("finalPrice", 0),
            "pre_change_pct": item.get("pChange", 0),
            "pre_volume": item.get("totalTradedVolume", 0),
            "iep": item.get("iep", 0),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.nlargest(top_n, "pre_change_pct").reset_index(drop=True)


def fetch_trading_calendar(year: int) -> pd.DataFrame:
    raise NotImplementedError("Implement: download NSE holiday PDF + parse, or use hardcoded list")
