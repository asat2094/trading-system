"""NSE Bhavcopy EOD downloader.

Source: archives.nseindia.com — official NSE historical data.
URL format: https://archives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MON}/cm{dd}{MON}{YYYY}bhav.csv.zip
"""
import io
import zipfile
import urllib.request
import pandas as pd
from core.logging import get_logger

log = get_logger(__name__)

_BHAVCOPY_BASE = "https://archives.nseindia.com/content/historical/EQUITIES"
_MONTHS = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.nseindia.com",
}


def fetch_github_eod(date_str: str) -> pd.DataFrame:
    """Fetch NSE Bhavcopy for a given date (YYYY-MM-DD). Returns empty DataFrame on holiday/error."""
    year, month, day = date_str.split("-")
    mon = _MONTHS[int(month)]
    filename = f"cm{day}{mon}{year}bhav.csv.zip"
    url = f"{_BHAVCOPY_BASE}/{year}/{mon}/{filename}"

    log.info("bhavcopy_fetch", date=date_str, url=url)
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except Exception as exc:
        log.warning("bhavcopy_fetch_failed", date=date_str, error=str(exc))
        return pd.DataFrame()

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            csv_name = zf.namelist()[0]
            with zf.open(csv_name) as f:
                df = pd.read_csv(f)
    except Exception as exc:
        log.error("bhavcopy_parse_failed", date=date_str, error=str(exc))
        return pd.DataFrame()

    # Bhavcopy columns: SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE,
    #                   TOTTRDQTY, TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN
    df.columns = [c.strip() for c in df.columns]

    # Keep EQ series only (exclude SME, ETF, derivatives)
    if "SERIES" in df.columns:
        df = df[df["SERIES"].str.strip() == "EQ"].copy()

    if df.empty:
        return df

    return pd.DataFrame({
        "ts": pd.to_datetime(date_str),
        "symbol": df["SYMBOL"].str.strip(),
        "open": pd.to_numeric(df["OPEN"], errors="coerce"),
        "high": pd.to_numeric(df["HIGH"], errors="coerce"),
        "low": pd.to_numeric(df["LOW"], errors="coerce"),
        "close": pd.to_numeric(df["CLOSE"], errors="coerce"),
        "volume": pd.to_numeric(df["TOTTRDQTY"], errors="coerce").fillna(0).astype(int),
    }).dropna(subset=["open", "close"]).reset_index(drop=True)
