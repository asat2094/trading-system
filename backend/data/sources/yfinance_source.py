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
                df.columns = [col[0] if col[1] == "" else col[0] for col in df.columns]
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
            wait = _BACKOFF_BASE * (2 ** attempt)
            log.warning("yfinance_retry", ticker=ticker, attempt=attempt + 1, wait_s=wait, error=str(exc))
            time.sleep(min(wait, 30))

    log.error("yfinance_failed", ticker=ticker, error=str(last_exc))
    return pd.DataFrame()


def fetch_universe(exchange: str = "NSE") -> pd.DataFrame:
    raise NotImplementedError("fetch_universe: implement with NSE stock list CSV + yfinance batch")
