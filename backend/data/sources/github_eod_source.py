import httpx
import pandas as pd
from core.logging import get_logger

log = get_logger(__name__)

_REPO_BASE = "https://raw.githubusercontent.com/jugaad-trader/nse-data/main/data"


def fetch_github_eod(date_str: str) -> pd.DataFrame:
    year, month, _ = date_str.split("-")
    url = f"{_REPO_BASE}/{year}/{month}/{date_str}.csv"
    try:
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        log.error("github_eod_fetch_failed", date=date_str, url=url, error=str(exc))
        return pd.DataFrame()

    df = pd.read_csv(pd.io.common.StringIO(resp.text))
    df.columns = [c.strip() for c in df.columns]
    col_map = {
        "Symbol": "symbol", "Date": "ts",
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    }
    df = df.rename(columns=col_map)
    df["ts"] = pd.to_datetime(df["ts"])
    return df[["ts", "symbol", "open", "high", "low", "close", "volume"]]
