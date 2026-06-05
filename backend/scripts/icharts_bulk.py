"""
icharts.in bulk F&O OHLCV downloader
Indices: NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX
Range  : 2019-01-01 → today

Download window per contract:
  - from_date = previous expiry date  (not getMinDate — we only want the active week/month)
  - to_date   = this expiry date      (not today — expired contracts don't trade beyond)

Expiry filter:
  - NIFTY       : weekly only (skip monthly, quarterly, far-future)
  - BANKNIFTY   : all expiries (monthly only — no weeklies)
  - MIDCPNIFTY  : all expiries (monthly)
  - SENSEX      : all expiries (monthly)
  - Skip sparse expiries: fewer than MIN_STRIKE_COUNT strikes available

Strikes: 50 CE + 50 PE centred around mid of strike list (ATM proxy)

Usage:
    .venv/bin/python icharts_bulk.py                     # all indices
    .venv/bin/python icharts_bulk.py --index NIFTY
    .venv/bin/python icharts_bulk.py --dry-run
"""

import argparse
import csv
import logging
import random
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from icharts_auth import ensure_auth

# ── Config ─────────────────────────────────────────────────────────────────────

INDICES          = ["NIFTY", "BANKNIFTY", "MIDCPNIFTY", "SENSEX"]
START_DATE       = date(2019, 1, 1)

# Actual launch dates — avoids giant first-expiry window for indices that started later
INDEX_START: dict[str, date] = {
    "NIFTY":      date(2019, 1, 1),
    "BANKNIFTY":  date(2019, 1, 1),
    "MIDCPNIFTY": date(2022, 1, 1),   # MIDCPNIFTY weekly launched Jan 2022
    "SENSEX":     date(2023, 11, 1),  # BSE SENSEX options launched Nov 2023
}
OUT_DIR          = Path(__file__).parent
BASE             = "https://www.icharts.in/opt"
RESOLUTION       = 1
STRIKES_EACH_SIDE = 25    # 25 CE + 25 PE each side → 50 CE + 50 PE total
MIN_STRIKE_COUNT  = 20    # skip expiry if fewer strikes available (sparse/illiquid)

# NIFTY has weekly expiries; others are monthly-only.
# For NIFTY we skip monthly & quarterly to avoid duplicate coverage.
WEEKLY_ONLY: set[str] = set()   # download all expiries for all indices

# Rate-limit knobs
BURST_SIZE        = 5
WINDOW_SECS       = 10
MIN_DELAY         = 1.5
MAX_JITTER        = 2.0
RETRY_BACKOFF     = [5, 15, 30]
BATCH_PAUSE_EVERY = 5
BATCH_PAUSE_SECS  = (8, 15)

IST = timezone(timedelta(hours=5, minutes=30))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(OUT_DIR.parent / "icharts_bulk.log"),
    ],
)
log = logging.getLogger(__name__)

# ── Session ────────────────────────────────────────────────────────────────────

_creds: dict = {}
_http = requests.Session()
_request_times: deque = deque()


def _init_session():
    global _creds
    _creds = ensure_auth(auto_refresh=True)
    _http.headers.update({
        "User-Agent": _creds.get("user_agent", "Mozilla/5.0"),
        "Referer": "https://www.icharts.in/opt/FnOCharts.php",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "x-api-key": _creds.get("api_key", ""),
        "Cookie": _creds.get("cookie", ""),
    })


def _throttle():
    now = time.monotonic()
    while _request_times and now - _request_times[0] > WINDOW_SECS:
        _request_times.popleft()
    if len(_request_times) >= BURST_SIZE:
        sleep_for = WINDOW_SECS - (now - _request_times[0]) + 0.1
        if sleep_for > 0:
            time.sleep(sleep_for)
    if _request_times:
        elapsed = time.monotonic() - _request_times[-1]
        gap = MIN_DELAY + random.uniform(0, MAX_JITTER)
        if elapsed < gap:
            time.sleep(gap - elapsed)
    _request_times.append(time.monotonic())


def _get(url: str, params: dict = None) -> requests.Response:
    for attempt, backoff in enumerate([0] + RETRY_BACKOFF):
        if backoff:
            log.warning(f"Retry {attempt} after {backoff}s")
            time.sleep(backoff)
        _throttle()
        try:
            r = _http.get(url, params=params, timeout=20)
            if r.status_code == 429:
                log.warning("429 — backing off")
                continue
            if "Invalid Session" in r.text:
                log.warning("Session expired — re-harvesting")
                _init_session()
                continue
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            log.warning(f"Network error: {e}")
    raise RuntimeError(f"All retries failed: {url}")


def _post(url: str, data: dict = None) -> requests.Response:
    for attempt, backoff in enumerate([0] + RETRY_BACKOFF):
        if backoff:
            time.sleep(backoff)
        _throttle()
        try:
            r = _http.post(url, data=data, timeout=20)
            if r.status_code == 429:
                continue
            if "Invalid Session" in r.text:
                _init_session()
                continue
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            log.warning(f"Network error: {e}")
    raise RuntimeError(f"All retries failed: {url}")


# ── Expiry helpers ─────────────────────────────────────────────────────────────

def _parse_expiry(e: str) -> date | None:
    try:
        return datetime.strptime(e, "%d%b%y").date()
    except ValueError:
        return None


def _is_monthly(d: date) -> bool:
    """Last occurrence of that weekday in the month — works for any expiry day."""
    return (d + timedelta(days=7)).month != d.month


def build_expiry_schedule(symbol: str, raw_expiries: list[str]) -> list[tuple[date, date, str]]:
    """
    Returns sorted list of (from_date, expiry_date, expiry_str).
    from_date = day after previous expiry = contract's active start.
    For first expiry, from_date = INDEX_START[symbol].
    """
    weekly_only = symbol in WEEKLY_ONLY
    idx_start = INDEX_START.get(symbol, START_DATE)

    parsed = []
    for e in raw_expiries:
        d = _parse_expiry(e)
        if d and d >= idx_start and d <= date.today():
            if weekly_only and _is_monthly(d):
                continue
            parsed.append((d, e))

    parsed.sort()

    schedule = []
    for i, (d, e) in enumerate(parsed):
        prev = idx_start if i == 0 else parsed[i - 1][0] + timedelta(days=1)
        schedule.append((prev, d, e))

    return schedule


# ── API helpers ────────────────────────────────────────────────────────────────

def get_expiries(symbol: str) -> list[str]:
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


def get_strikes(symbol: str, expiry: str, option_type: str) -> list[str]:
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


def build_tv_symbol(symbol: str, expiry: str, strike: str, option_type: str) -> str:
    """DDMMMYY → YYMMMDD in TV symbol. e.g. NIFTY+26MAY26+24000+CE → NIFTY26MAY2624000CE"""
    dd, mmm, yy = expiry[:2], expiry[2:5], expiry[5:7]
    return f"{symbol}{yy}{mmm}{dd}{strike}{option_type}"


def select_strikes(strikes: list[str], n_each_side: int) -> list[str]:
    """Pick 2*n_each_side strikes centred around mid (ATM proxy)."""
    if not strikes:
        return []
    s = sorted(strikes, key=float)
    mid = len(s) // 2
    return s[max(0, mid - n_each_side): min(len(s), mid + n_each_side)]


def fetch_ohlcv(tv_symbol: str, from_date: str, to_date: str) -> list[dict]:
    params = {
        "symbol": tv_symbol,
        "resolution": RESOLUTION,
        "from": from_date,
        "to": to_date,
        "u": _creds["email"],
        "sid": _creds["sid"],
        "DataRequest": 0,
        "firstDataRequest": "true",
        "countback": 999999,
    }
    r = _get(f"{BASE}/getdataFNO_Chart_TV_Charts_Daily_v2.php", params=params)
    try:
        data = r.json()
    except Exception:
        log.warning(f"Non-JSON for {tv_symbol}: {r.text[:80]}")
        return []
    if data.get("s") == "no_data" or not data.get("t"):
        return []
    return [
        {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}
        for t, o, h, l, c, v in zip(
            data["t"], data["o"], data["h"], data["l"], data["c"], data["v"]
        )
    ]


# ── Downloader ────────────────────────────────────────────────────────────────

def _out_path(tv_symbol: str) -> Path:
    return OUT_DIR / f"{tv_symbol}_R{RESOLUTION}.csv"


def download_symbol(
    tv_symbol: str,
    from_date: str,
    to_date: str,
) -> bool:
    """Download and save one contract. Returns True if new data saved."""
    out = _out_path(tv_symbol)
    if out.exists():
        log.debug(f"SKIP {tv_symbol} (exists)")
        return False

    bars = fetch_ohlcv(tv_symbol, from_date, to_date)
    if not bars:
        log.debug(f"  {tv_symbol}: no data in window {from_date}→{to_date}")
        return False

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ts", "open", "high", "low", "close", "volume"])
        w.writeheader()
        for b in bars:
            dt = datetime.fromtimestamp(b["t"], tz=IST)
            w.writerow({
                "ts":     dt.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
                "open":   b["o"],
                "high":   b["h"],
                "low":    b["l"],
                "close":  b["c"],
                "volume": b["v"],
            })

    log.info(f"  SAVED {tv_symbol}: {len(bars)} bars  [{from_date} → {to_date}]")
    return True


def process_expiry(
    symbol: str,
    expiry: str,
    prev_date: date,
    exp_date: date,
) -> int:
    """Download 50 CE + 50 PE strikes for one expiry. Returns count saved."""
    from_date = prev_date.isoformat()
    to_date   = exp_date.isoformat()
    saved = 0

    for opt_type in ["CE", "PE"]:
        strikes_raw = get_strikes(symbol, expiry, opt_type)

        if len(strikes_raw) < MIN_STRIKE_COUNT:
            log.info(f"  SKIP {symbol} {expiry} {opt_type}: only {len(strikes_raw)} strikes (sparse)")
            continue

        strikes = select_strikes(strikes_raw, STRIKES_EACH_SIDE)
        log.info(
            f"  {symbol} {expiry} {opt_type}: {len(strikes_raw)} strikes → "
            f"{len(strikes)} selected  window={from_date}→{to_date}"
        )

        for i, strike in enumerate(strikes):
            tv_sym = build_tv_symbol(symbol, expiry, strike, opt_type)
            try:
                if download_symbol(tv_sym, from_date, to_date):
                    saved += 1
            except Exception as e:
                log.error(f"  ERROR {tv_sym}: {e}")

            if (i + 1) % BATCH_PAUSE_EVERY == 0:
                time.sleep(random.uniform(*BATCH_PAUSE_SECS))

    return saved


# ── Main ───────────────────────────────────────────────────────────────────────

def run(indices: list[str], dry_run: bool = False):
    _init_session()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    grand_total = 0

    for symbol in indices:
        log.info(f"\n{'='*60}\nIndex: {symbol}\n{'='*60}")
        raw_expiries = get_expiries(symbol)
        schedule = build_expiry_schedule(symbol, raw_expiries)

        idx_start = INDEX_START.get(symbol, START_DATE)
        log.info(
            f"{symbol}: {len(raw_expiries)} total expiries → "
            f"{len(schedule)} in range from {idx_start}  "
            f"({'weekly' if symbol in WEEKLY_ONLY else 'monthly'})"
        )

        if dry_run:
            sample = schedule[:3]
            for prev, exp, e in sample:
                window_days = (exp - prev).days
                log.info(f"  sample: {e}  window {prev}→{exp}  ({window_days} cal days)")
            est = len(schedule) * 100
            log.info(f"  DRY RUN: ~{est} contracts")
            grand_total += est
            continue

        total_saved = 0
        for idx, (prev_dt, exp_dt, expiry) in enumerate(schedule):
            log.info(
                f"\n[{symbol}] {idx+1}/{len(schedule)}: {expiry}  "
                f"{prev_dt}→{exp_dt}  ({(exp_dt-prev_dt).days}d)"
            )
            try:
                saved = process_expiry(symbol, expiry, prev_dt, exp_dt)
                total_saved += saved
            except Exception as e:
                log.error(f"Failed expiry {expiry}: {e}")

            time.sleep(random.uniform(3, 6))

        log.info(f"{symbol}: done — {total_saved} new files saved")
        grand_total += total_saved

    if dry_run:
        log.info(f"\nDRY RUN total: ~{grand_total} contracts across {len(indices)} indices")
    else:
        log.info(f"\nAll done. Grand total new files: {grand_total}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", help="Single index (e.g. NIFTY)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    indices = [args.index.upper()] if args.index else INDICES
    run(indices, dry_run=args.dry_run)
