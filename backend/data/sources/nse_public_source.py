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
        try:
            bootstrap = client.get("https://www.nseindia.com", timeout=10)
            bootstrap.raise_for_status()
        except Exception as exc:
            log.error("nse_bootstrap_failed", error=str(exc))
            return pd.DataFrame()
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


# NSE equity segment holidays — update annually
_NSE_HOLIDAYS: dict[int, list[str]] = {
    2024: [
        "2024-01-22", "2024-01-26", "2024-03-08", "2024-03-25", "2024-03-29",
        "2024-04-11", "2024-04-14", "2024-04-17", "2024-04-21", "2024-05-01",
        "2024-05-20", "2024-06-17", "2024-07-17", "2024-08-15", "2024-10-02",
        "2024-11-01", "2024-11-15", "2024-11-20", "2024-12-25",
    ],
    2025: [
        "2025-01-26", "2025-02-26", "2025-03-14", "2025-03-31", "2025-04-10",
        "2025-04-14", "2025-04-18", "2025-05-01", "2025-06-07", "2025-07-06",
        "2025-08-15", "2025-08-27", "2025-10-02", "2025-10-02", "2025-10-21",
        "2025-10-24", "2025-11-05", "2025-12-25",
    ],
    2026: [
        "2026-01-26", "2026-03-03", "2026-03-20", "2026-04-02", "2026-04-03",
        "2026-04-14", "2026-05-01", "2026-06-27", "2026-07-29", "2026-08-15",
        "2026-10-02", "2026-10-09", "2026-10-29", "2026-11-06", "2026-11-24",
        "2026-12-25",
    ],
}

_NSE_OPEN_TIME = "09:15:00"
_NSE_CLOSE_TIME = "15:30:00"
_NSE_MINUTES = 375


def fetch_trading_calendar(year: int) -> pd.DataFrame:
    """Generate NSE trading calendar for given year.

    Returns DataFrame with columns: date, exchange, is_trading, session_type,
    open_time, close_time, minutes.
    """
    import datetime

    holidays = set(_NSE_HOLIDAYS.get(year, []))
    rows = []
    d = datetime.date(year, 1, 1)
    end = datetime.date(year, 12, 31)
    while d <= end:
        is_weekend = d.weekday() >= 5  # Sat=5, Sun=6
        date_str = d.isoformat()
        is_holiday = date_str in holidays
        is_trading = not is_weekend and not is_holiday
        rows.append({
            "date": d,
            "exchange": "NSE",
            "is_trading": is_trading,
            "session_type": "regular" if is_trading else ("weekend" if is_weekend else "holiday"),
            "open_time": _NSE_OPEN_TIME if is_trading else None,
            "close_time": _NSE_CLOSE_TIME if is_trading else None,
            "minutes": _NSE_MINUTES if is_trading else 0,
        })
        d += datetime.timedelta(days=1)

    return pd.DataFrame(rows)
