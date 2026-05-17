import time
import pandas as pd
import yfinance as yf
from core.logging import get_logger

log = get_logger(__name__)
_MAX_ATTEMPTS = 3
_BACKOFF_BASE = 5


def fetch_daily_ohlcv(ticker: str, start: str, end: str) -> pd.DataFrame:
    symbol = ticker.replace(".NS", "").replace(".BO", "")
    last_exc = None

    for attempt in range(_MAX_ATTEMPTS):
        try:
            df = yf.download(ticker, start=start, end=end, auto_adjust=False, progress=False)
            if df.empty:
                return pd.DataFrame()
            df = df.reset_index()
            # Handle MultiIndex columns from newer yfinance versions
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0] for col in df.columns]
            return pd.DataFrame({
                "ts": pd.to_datetime(df["Date"]),
                "symbol": symbol,
                "open": df["Open"].astype(float),
                "high": df["High"].astype(float),
                "low": df["Low"].astype(float),
                "close": df["Close"].astype(float),
                "volume": df["Volume"].astype(int),
                "adjusted_close": df["Adj Close"].astype(float),
            })
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_ATTEMPTS - 1:
                wait = _BACKOFF_BASE * (2 ** attempt)
                log.warning("yfinance_retry", ticker=ticker, attempt=attempt + 1, wait_s=wait, error=str(exc))
                time.sleep(min(wait, 30))

    log.error("yfinance_failed", ticker=ticker, error=str(last_exc))
    return pd.DataFrame()


def fetch_universe(exchange: str = "NSE") -> pd.DataFrame:
    """Download NSE/BSE equity list from public archive CSV.

    NSE CSV columns: SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,...
    Returns DataFrame with columns: symbol, name, exchange.
    """
    import io
    import urllib.request

    urls = {
        "NSE": "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
        "BSE": "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active",
    }
    url = urls.get(exchange.upper())
    if url is None:
        raise ValueError(f"Unsupported exchange: {exchange!r}. Use 'NSE' or 'BSE'.")

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; trading-system/1.0)",
        "Accept": "text/csv,application/json,*/*",
    }

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    if exchange.upper() == "NSE":
        df = pd.read_csv(io.StringIO(raw))
        # NSE CSV: SYMBOL, NAME OF COMPANY, SERIES, DATE OF LISTING, ...
        # Keep only EQ series (regular equities, exclude SME/ETF etc.)
        if "SERIES" in df.columns:
            df = df[df["SERIES"].str.strip() == "EQ"]
        return pd.DataFrame({
            "symbol": df["SYMBOL"].str.strip(),
            "name": df["NAME OF COMPANY"].str.strip(),
            "exchange": "NSE",
        }).reset_index(drop=True)

    # BSE fallback — JSON response
    import json
    data = json.loads(raw)
    rows = data.get("Table", data) if isinstance(data, dict) else data
    return pd.DataFrame({
        "symbol": [r.get("scrip_cd", r.get("SCRIP_CD", "")) for r in rows],
        "name": [r.get("scrip_name", r.get("Scrip_Name", "")) for r in rows],
        "exchange": "BSE",
    })
