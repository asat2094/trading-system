"""
icharts.in F&O data scraper
Pulls: OHLCV bars, expiry dates, strike prices, symbol list
Auth: session id from URL params (u + sid)
"""

import json
import requests
import pandas as pd
from datetime import datetime, date
import time
import random
import logging
from pathlib import Path
from collections import deque

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BASE = "https://www.icharts.in/opt"

# Credentials — loaded from auth.json (run icharts_auth.py to refresh)
# Fallback hardcoded values used if auth.json missing:
USER_EMAIL = "asat2094@gmail.com"
SESSION_ID = "flocan0ph1trshdd1lqgl0i8r7"   # also PHPSESSID cookie value
API_KEY    = "woope1Pei5zieg"
COOKIES    = (
    "_ga=GA1.1.950861119.1776582351; "
    "_fbp=fb.1.1776582351153.741242181246789670; "
    f"PHPSESSID={SESSION_ID}; "
    "g_state={\"i_l\":0,\"i_ll\":1780051014279,\"i_e\":{\"enable_itp_optimization\":0},\"i_et\":1776582356264}; "
    "_ga_ZN58C89YGF=GS2.1.s1780051011$o13$g1$t1780052087$j59$l0$h0; "
    "cf_clearance=RWdJ3iQydFpG1N6SJg_PrSusqZmuumBw7ZE9Jmplqr0-1780052087-1.2.1.1-I1k.SI.marhpLbtKmPvkiayk1O2G6ckXpeiBbq_sbxC3pcvkCQwEJ6t35.VMSTz6bXbkrYSv77GiApEKbXCtS3TLX3dwmty39aUuMy32wC9HmZ2rCWx1LKv1Bd1O72GQDECqe9sOZap_rl6jMuHXDqwYpgr9abeJkPdFZVLzCuiPJnNyiUcvfY01bPwJMmze2chq559Iq1Y5On5tPTasG1avkSV4VwfEsqQtY.Xtew6rCHiIxLxrTzcmpGVXsIxBKcvRJUzjYc8BJwaN3vh6rjpZK2eWfFUv8w0lURl6OKpylsUr6axQ4Et3i25H9ZrZwOmEiTwVu_G.uDN3RqEBuA"
)
# -----------------------------------------

OUT_DIR = Path(__file__).parent

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "Referer": "https://www.icharts.in/opt/FnOCharts.php",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "priority": "u=1, i",
    "x-api-key": API_KEY,
    "Cookie": COOKIES,
}

# ── Rate limiter ───────────────────────────────────────────────────────────────
# Token-bucket: max BURST_SIZE requests in any WINDOW_SECS window
# Plus per-request jitter to avoid mechanical patterns

BURST_SIZE = 5          # max requests per window
WINDOW_SECS = 10        # rolling window in seconds
MIN_DELAY = 1.5         # min seconds between consecutive requests
MAX_JITTER = 2.0        # max extra random seconds added per request
RETRY_BACKOFF = [5, 15, 30]  # seconds to wait on 429 / error, per attempt

_request_times: deque = deque()


def _throttle():
    """Block until within rate limits, then record the request timestamp."""
    now = time.monotonic()

    # Drop timestamps outside the rolling window
    while _request_times and now - _request_times[0] > WINDOW_SECS:
        _request_times.popleft()

    # If at burst limit, sleep until oldest request falls out of window
    if len(_request_times) >= BURST_SIZE:
        sleep_for = WINDOW_SECS - (now - _request_times[0]) + 0.1
        if sleep_for > 0:
            log.debug(f"Rate limit: sleeping {sleep_for:.1f}s")
            time.sleep(sleep_for)

    # Per-request minimum delay from last call
    if _request_times:
        elapsed = time.monotonic() - _request_times[-1]
        gap = MIN_DELAY + random.uniform(0, MAX_JITTER)
        if elapsed < gap:
            time.sleep(gap - elapsed)

    _request_times.append(time.monotonic())


def _get(url: str, params: dict = None) -> requests.Response:
    """GET with throttle + retry on transient errors."""
    for attempt, backoff in enumerate([0] + RETRY_BACKOFF):
        if backoff:
            log.warning(f"Retry {attempt}/{len(RETRY_BACKOFF)} after {backoff}s — {url}")
            time.sleep(backoff)
        _throttle()
        try:
            r = http.get(url, params=params, timeout=15)
            if r.status_code == 429:
                log.warning("429 Too Many Requests")
                continue
            if "Invalid Session" in r.text:
                raise RuntimeError("Session expired — update SESSION_ID")
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            log.warning(f"Network error: {e}")
    raise RuntimeError(f"All retries failed for {url}")


def _post(url: str, data: dict = None) -> requests.Response:
    """POST with throttle + retry."""
    for attempt, backoff in enumerate([0] + RETRY_BACKOFF):
        if backoff:
            log.warning(f"Retry {attempt}/{len(RETRY_BACKOFF)} after {backoff}s")
            time.sleep(backoff)
        _throttle()
        try:
            r = http.post(url, data=data, timeout=15)
            if r.status_code == 429:
                continue
            if "Invalid Session" in r.text:
                raise RuntimeError("Session expired — update SESSION_ID")
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            log.warning(f"Network error: {e}")
    raise RuntimeError(f"All retries failed for {url}")


# Try loading live auth from auth.json
_auth_file = Path(__file__).parent / "auth.json"
if _auth_file.exists():
    try:
        _auth = json.loads(_auth_file.read_text())
        USER_EMAIL = _auth.get("email", USER_EMAIL)
        SESSION_ID = _auth.get("sid", SESSION_ID)
        API_KEY    = _auth.get("api_key", API_KEY)
        COOKIES    = _auth.get("cookie", COOKIES)
        HEADERS["User-Agent"] = _auth.get("user_agent", HEADERS["User-Agent"])
        HEADERS["x-api-key"]  = API_KEY
        HEADERS["Cookie"]     = COOKIES
    except Exception:
        pass  # fall through to hardcoded values

http = requests.Session()
http.headers.update(HEADERS)


# ── API calls ──────────────────────────────────────────────────────────────────

def check_session() -> bool:
    r = _post(f"{BASE}/hcharts/stx8req/php/checkUserSession.php")
    return "valid" in r.text.lower()


def get_symbols() -> dict:
    """Returns {'Indices': [...], 'BSE': [...], 'Stocks': [...]}"""
    r = _get(
        f"{BASE}/hcharts/stx8req/php/getSymbolData_v3.php",
        params={"latestOrHistorical": "historical", "optionType": "option", "getSymbol": "true"},
    )
    return r.json().get("Symbols", {})


def get_expiries(symbol: str) -> list[str]:
    """Returns list of expiry strings (DDMMMYY), newest-first."""
    r = _get(
        f"{BASE}/hcharts/stx8req/php/getSymbolData_v3.php",
        params={
            "latestOrHistorical": "historical",
            "optionType": "option",
            "defaultSymbol": symbol,
            "getExpiry": "true",
        },
    )
    return r.json().get("expiryDate", [])


def get_strikes(symbol: str, expiry: str, option_type: str = "CE") -> list[str]:
    """Returns list of strike price strings. option_type: CE or PE"""
    r = _get(
        f"{BASE}/hcharts/stx8req/php/getSymbolData_v3.php",
        params={
            "latestOrHistorical": "historical",
            "optionType": option_type,
            "defaultSymbol": symbol,
            "getStrike": "true",
            "expiryDate": expiry,
        },
    )
    return r.json().get("strikePrice", [])


def nearest_expiry(symbol: str) -> str:
    """Return the nearest future expiry string (DDMMMYY) for a symbol."""
    expiries = get_expiries(symbol)
    today_dt = date.today()
    future = []
    for e in expiries:
        try:
            exp_dt = datetime.strptime(e, "%d%b%y").date()
            if exp_dt >= today_dt:
                future.append((exp_dt, e))
        except ValueError:
            pass
    future.sort()
    return future[0][1] if future else expiries[-1]


def build_tv_symbol(symbol: str, expiry: str, strike: str, option_type: str) -> str:
    """
    expiry is DDMMMYY from API (e.g. '30JUN26').
    TV symbol format: SYMBOL + YYMMMDD + STRIKE + TYPE
    e.g. NIFTY + 30JUN26 -> NIFTY26JUN3024000CE
    """
    dd, mmm, yy = expiry[:2], expiry[2:5], expiry[5:7]
    return f"{symbol}{yy}{mmm}{dd}{strike}{option_type}"


def get_min_date(tv_symbol: str) -> str:
    """Returns earliest available date string YYYY-MM-DD, or '' if none."""
    r = _post(f"{BASE}/hcharts/stx8req/php/getMinDate_FNO_TV_v2.php", data={"symbol": tv_symbol})
    return r.text.strip()


def get_ohlcv(
    tv_symbol: str,
    from_date: str,
    to_date: str,
    resolution: int = 1,
    first_request: bool = True,
    countback: int = 10000,
) -> pd.DataFrame:
    """
    Fetch OHLCV bars.
    resolution: 1=1min, 3=3min, 5=5min, 15=15min, 60=1hr, D=daily
    Returns DataFrame: datetime, open, high, low, close, volume, symbol
    """
    params = {
        "symbol": tv_symbol,
        "resolution": resolution,
        "from": from_date,
        "to": to_date,
        "u": USER_EMAIL,
        "sid": SESSION_ID,
        "DataRequest": 0 if first_request else 1,
        "firstDataRequest": "true" if first_request else "false",
        "countback": countback,
    }
    r = _get(f"{BASE}/getdataFNO_Chart_TV_Charts_Daily_v2.php", params=params)

    try:
        data = r.json()
    except Exception:
        log.warning(f"Non-JSON response for {tv_symbol}: {r.text[:100]}")
        return pd.DataFrame()

    if data.get("s") == "no_data" or not data.get("t"):
        return pd.DataFrame()

    df = pd.DataFrame({
        "datetime": pd.to_datetime(data["t"], unit="s", utc=True).tz_convert("Asia/Kolkata"),
        "open":   data["o"],
        "high":   data["h"],
        "low":    data["l"],
        "close":  data["c"],
        "volume": data["v"],
    })
    df["symbol"] = tv_symbol
    return df


# ── High-level fetchers ────────────────────────────────────────────────────────

def fetch_full_history(
    tv_symbol: str,
    resolution: int = 1,
    save_csv: bool = True,
    out_dir: str = OUT_DIR,
) -> pd.DataFrame:
    """Fetch all available history for a symbol."""
    min_date = get_min_date(tv_symbol)
    if not min_date or len(min_date) < 8:
        log.warning(f"{tv_symbol}: no min date, skipping")
        return pd.DataFrame()

    today = date.today().isoformat()
    log.info(f"{tv_symbol}: {min_date} → {today}")

    df = get_ohlcv(tv_symbol, min_date, today, resolution, first_request=True)
    if df.empty:
        log.info(f"{tv_symbol}: no data")
        return df

    log.info(f"{tv_symbol}: {len(df)} bars")

    if save_csv:
        Path(out_dir).mkdir(exist_ok=True)
        path = f"{out_dir}/{tv_symbol}_R{resolution}.csv"
        df.to_csv(path, index=False)
        log.info(f"Saved → {path}")

    return df


def fetch_options_chain_ohlcv(
    symbol: str,
    expiry: str,
    resolution: int = 1,
    strikes_limit: int = 10,
    out_dir: str = OUT_DIR,
) -> dict[str, pd.DataFrame]:
    """
    Fetch OHLCV for top N strikes for both CE and PE.
    Returns dict: {tv_symbol: DataFrame}
    """
    results = {}
    for opt_type in ["CE", "PE"]:
        strikes = get_strikes(symbol, expiry, opt_type)
        log.info(f"{symbol} {expiry} {opt_type}: {len(strikes)} strikes, fetching {strikes_limit}")
        for i, strike in enumerate(strikes[:strikes_limit]):
            tv_sym = build_tv_symbol(symbol, expiry, strike, opt_type)
            df = fetch_full_history(tv_sym, resolution, save_csv=True, out_dir=out_dir)
            results[tv_sym] = df
            # Extra pause between strike batches (every 5 symbols)
            if (i + 1) % 5 == 0:
                pause = random.uniform(8, 15)
                log.info(f"Batch pause {pause:.1f}s after {i+1} symbols")
                time.sleep(pause)
    return results


# ── CLI ────────────────────────────────────────────────────────────────────────

def demo_run():
    log.info("Checking session...")
    if not check_session():
        log.error("Session invalid. Update USER_EMAIL and SESSION_ID at top of file.")
        return

    log.info("Session OK")

    syms = get_symbols()
    log.info(f"Indices: {syms.get('Indices')}")
    log.info(f"Stocks: {len(syms.get('Stocks', []))} total")

    near = nearest_expiry("NIFTY")
    log.info(f"Nearest NIFTY expiry: {near}")
    ce_strikes = get_strikes("NIFTY", near, "CE")
    log.info(f"CE strikes (first 10): {ce_strikes[:10]}")

    tv_sym = build_tv_symbol("NIFTY", near, ce_strikes[5], "CE")
    log.info(f"Fetching OHLCV for {tv_sym}...")
    df = fetch_full_history(tv_sym, resolution=1, save_csv=True)
    if not df.empty:
        print(df.tail())


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 1:
        demo_run()

    elif sys.argv[1] == "nifty" and len(sys.argv) >= 3:
        # .venv/bin/python icharts_scraper.py nifty 30JUN26 [resolution] [strikes]
        expiry = sys.argv[2]
        res = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        n = int(sys.argv[4]) if len(sys.argv) > 4 else 20
        if check_session():
            fetch_options_chain_ohlcv("NIFTY", expiry, res, n)

    elif sys.argv[1] == "banknifty" and len(sys.argv) >= 3:
        expiry = sys.argv[2]
        res = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        n = int(sys.argv[4]) if len(sys.argv) > 4 else 20
        if check_session():
            fetch_options_chain_ohlcv("BANKNIFTY", expiry, res, n)

    elif sys.argv[1] == "symbol" and len(sys.argv) >= 3:
        # .venv/bin/python icharts_scraper.py symbol NIFTY26JUN0224000CE [resolution]
        tv_sym = sys.argv[2]
        res = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        if check_session():
            fetch_full_history(tv_sym, resolution=res, save_csv=True)
