"""Intraday OHLCV fetcher using yfinance.

yfinance intraday availability:
  1m  — last 7 days
  2m  — last 60 days
  5m  — last 60 days
  15m — last 60 days
  30m — last 60 days
  60m — last 730 days
"""
import time
import pandas as pd
import yfinance as yf
from core.logging import get_logger

log = get_logger(__name__)

_INTERVAL_MAP = {
    "1min": "1m",
    "5min": "5m",
    "15min": "15m",
    "30min": "30m",
    "1h": "60m",
    "60min": "60m",
}
_MAX_ATTEMPTS = 3


def fetch_intraday(symbol: str, date_str: str, interval: str = "1min") -> pd.DataFrame:
    """Fetch intraday OHLCV for a single NSE symbol on a given date.

    Args:
        symbol: NSE symbol without suffix, e.g. "RELIANCE"
        date_str: ISO date string "YYYY-MM-DD"
        interval: "1min", "5min", "15min", "30min", "1h"

    Returns:
        DataFrame with columns: ts, symbol, open, high, low, close, volume
    """
    yf_interval = _INTERVAL_MAP.get(interval, interval)
    ticker = f"{symbol}.NS"

    # yfinance requires end = start + 1 day for single-day intraday
    import datetime
    start = date_str
    end = (datetime.date.fromisoformat(date_str) + datetime.timedelta(days=1)).isoformat()

    last_exc = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            df = yf.download(
                ticker,
                start=start,
                end=end,
                interval=yf_interval,
                auto_adjust=False,
                progress=False,
                multi_level_index=False,
            )
            break
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_ATTEMPTS - 1:
                wait = 5 * (2 ** attempt)
                log.warning("yfinance_intraday_retry",
                            ticker=ticker, attempt=attempt + 1, wait_s=wait)
                time.sleep(min(wait, 30))
    else:
        log.error("yfinance_intraday_failed", ticker=ticker, error=str(last_exc))
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    df = df.reset_index()
    ts_col = "Datetime" if "Datetime" in df.columns else df.columns[0]

    return pd.DataFrame({
        "ts": pd.to_datetime(df[ts_col]),
        "symbol": symbol,
        "open": df["Open"].astype(float),
        "high": df["High"].astype(float),
        "low": df["Low"].astype(float),
        "close": df["Close"].astype(float),
        "volume": df["Volume"].astype(int),
    })


# Legacy async wrapper kept for backward compat
async def fetch_intraday_1min(symbol: str, date_str: str) -> pd.DataFrame:
    import asyncio
    return await asyncio.get_event_loop().run_in_executor(
        None, fetch_intraday, symbol, date_str, "1min"
    )
