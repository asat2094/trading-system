"""
icharts F&O bulk download coordinator
======================================
Architecture:
  Phase 1 — Task generation  : fetch all expiries + strikes → populate SQLite task queue
  Phase 2 — Download workers : N threads pull tasks, download OHLCV, mark done
  UI       — Rich live TUI   : real-time progress, ETA, worker status, log tail

Usage:
    .venv/bin/python icharts_coordinator.py             # generate + download (4 workers)
    .venv/bin/python icharts_coordinator.py --workers 6
    .venv/bin/python icharts_coordinator.py --generate-only   # just populate task DB
    .venv/bin/python icharts_coordinator.py --download-only   # skip generation, resume downloads
    .venv/bin/python icharts_coordinator.py --status          # print stats and exit
    .venv/bin/python icharts_coordinator.py --reset-failed    # retry failed tasks
"""

import argparse
import csv
import logging
import os
import random
import sqlite3
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from icharts_auth import ensure_auth

# ── Config ─────────────────────────────────────────────────────────────────────

INDICES           = ["NIFTY", "BANKNIFTY", "MIDCPNIFTY", "SENSEX"]
INDEX_START: dict[str, date] = {
    "NIFTY":      date(2019, 1, 1),
    "BANKNIFTY":  date(2019, 1, 1),
    "MIDCPNIFTY": date(2022, 1, 1),
    "SENSEX":     date(2023, 11, 1),
}
WEEKLY_ONLY: set[str] = set()   # no filtering — download all expiries for all indices
STRIKES_EACH_SIDE = 10    # 10 below + 10 above ATM, per opt_type → 40 total per expiry
MIN_STRIKE_COUNT  = 20

# Spot data directory and symbol mapping (for dynamic ATM calculation)
SPOT_DIR = Path("/Users/ankitatiwari/Desktop/claude-playground/trading-system/rawdata/1min_indices")
SPOT_SYMBOL: dict[str, str] = {
    "NIFTY":      "NSE_NIFTY_50",
    "BANKNIFTY":  "NSE_NIFTY_BANK",
    "MIDCPNIFTY": "NSE_NIFTY_MID_SELECT",
    "SENSEX":     "BSE_SENSEX",
}
OUT_DIR           = Path(__file__).parent
REPO_ROOT         = OUT_DIR.parent.parent
RAW_DIR           = REPO_ROOT / "data" / "raw" / "options"
DB_PATH           = OUT_DIR / "coordinator.db"
BASE              = "https://www.icharts.in/opt"
RESOLUTION        = 1
IST               = timezone(timedelta(hours=5, minutes=30))

# Rate limiting — shared across all workers
BURST_SIZE    = 5
WINDOW_SECS   = 10.0
MIN_DELAY     = 1.2
MAX_JITTER    = 1.8
RETRY_BACKOFF = [5, 15, 30]

# ── Logging (file only — Rich owns stdout) ─────────────────────────────────────

LOG_PATH = OUT_DIR / "icharts_coordinator.log"
_file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s [%(threadName)s] %(message)s"))
log = logging.getLogger("coordinator")
log.setLevel(logging.DEBUG)
log.addHandler(_file_handler)
log.propagate = False

# ── Rate limiters — workers and generator have separate budgets ────────────────
# Workers: 6 req / 10s window, priority traffic
# Generator: 2 req / 10s window, background traffic — never starves workers

_worker_rl_lock  = threading.Lock()
_worker_rl_times: deque = deque()

_gen_rl_lock  = threading.Lock()
_gen_rl_times: deque = deque()


def _make_throttle(lock: threading.Lock, times: deque, burst: int, window: float,
                   min_delay: float, max_jitter: float):
    def throttle():
        with lock:
            now = time.monotonic()
            while times and now - times[0] > window:
                times.popleft()
            if len(times) >= burst:
                sleep_for = window - (now - times[0]) + 0.1
            else:
                sleep_for = 0.0
            if times:
                gap = min_delay + random.uniform(0, max_jitter)
                sleep_for = max(sleep_for, gap - (now - times[-1]))
            times.append(time.monotonic())
        if sleep_for > 0:
            time.sleep(sleep_for)
    return throttle


# Workers get 6 req/10s, min 1.2s gap
_throttle     = _make_throttle(_worker_rl_lock, _worker_rl_times, 6, 10.0, 1.2, 1.5)
# Generator gets 2 req/10s, min 4s gap — slow background budget
_gen_throttle = _make_throttle(_gen_rl_lock,    _gen_rl_times,    2, 10.0, 4.0, 2.0)


# ── HTTP session (per-thread) ──────────────────────────────────────────────────

_thread_local = threading.local()


def _get_session(creds: dict) -> requests.Session:
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update({
            "User-Agent": creds.get("user_agent", "Mozilla/5.0"),
            "Referer": "https://www.icharts.in/opt/FnOCharts.php",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "x-api-key": creds.get("api_key", ""),
            "Cookie": creds.get("cookie", ""),
        })
        _thread_local.session = s
    return _thread_local.session


def _get(url: str, params: dict, creds: dict, gen: bool = False) -> requests.Response:
    sess = _get_session(creds)
    throttle_fn = _gen_throttle if gen else _throttle
    for attempt, backoff in enumerate([0] + RETRY_BACKOFF):
        if backoff:
            time.sleep(backoff)
        throttle_fn()
        try:
            r = sess.get(url, params=params, timeout=20)
            if r.status_code == 429:
                log.warning("429 received")
                time.sleep(15)
                continue
            if "Invalid Session" in r.text:
                raise RuntimeError("SESSION_EXPIRED")
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            log.warning(f"Network error attempt {attempt}: {e}")
    raise RuntimeError(f"All retries failed: {url}")


def _post(url: str, data: dict, creds: dict, gen: bool = False) -> requests.Response:
    sess = _get_session(creds)
    throttle_fn = _gen_throttle if gen else _throttle
    for attempt, backoff in enumerate([0] + RETRY_BACKOFF):
        if backoff:
            time.sleep(backoff)
        throttle_fn()
        try:
            r = sess.post(url, data=data, timeout=20)
            if r.status_code == 429:
                time.sleep(15)
                continue
            if "Invalid Session" in r.text:
                raise RuntimeError("SESSION_EXPIRED")
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            log.warning(f"Network error attempt {attempt}: {e}")
    raise RuntimeError(f"All retries failed: {url}")


# ── Task DB ────────────────────────────────────────────────────────────────────

def _db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with _db_conn() as conn:
        # Tracks every (index, expiry) the generator has fully processed,
        # even if it yielded 0 tasks (sparse expiry). Prevents re-checking on restart.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gen_log (
                index_name TEXT NOT NULL,
                expiry     TEXT NOT NULL,
                PRIMARY KEY (index_name, expiry)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                index_name  TEXT NOT NULL,
                expiry      TEXT NOT NULL,
                strike      TEXT NOT NULL,
                opt_type    TEXT NOT NULL,
                tv_symbol   TEXT NOT NULL UNIQUE,
                from_date   TEXT NOT NULL,
                to_date     TEXT NOT NULL,
                atm_price   REAL,
                status      TEXT NOT NULL DEFAULT 'pending',
                worker_id   TEXT,
                bars_count  INTEGER,
                error       TEXT,
                created_at  REAL DEFAULT (unixepoch('now')),
                updated_at  REAL DEFAULT (unixepoch('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_index  ON tasks(index_name, status)")


def task_counts(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM tasks GROUP BY status"
    ).fetchall()
    counts = {"pending": 0, "in_progress": 0, "done": 0, "failed": 0, "skipped": 0}
    for r in rows:
        counts[r[0]] = r[1]
    counts["total"] = sum(counts.values())
    return counts


def index_counts(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT index_name, status, COUNT(*) FROM tasks GROUP BY index_name, status"
    ).fetchall()
    result: dict[str, dict] = {}
    for r in rows:
        idx = r[0]
        if idx not in result:
            result[idx] = {"pending": 0, "in_progress": 0, "done": 0, "failed": 0, "skipped": 0}
        result[idx][r[1]] = r[2]
    return result


def claim_task(conn: sqlite3.Connection, worker_id: str) -> sqlite3.Row | None:
    """Atomically claim one pending task. Returns the row or None."""
    row = conn.execute(
        "SELECT id, tv_symbol, from_date, to_date, index_name, expiry "
        "FROM tasks WHERE status='pending' LIMIT 1"
    ).fetchone()
    if not row:
        return None
    conn.execute(
        "UPDATE tasks SET status='in_progress', worker_id=?, updated_at=unixepoch('now') WHERE id=?",
        (worker_id, row["id"]),
    )
    conn.commit()
    return row


def mark_done(conn: sqlite3.Connection, task_id: int, bars: int):
    conn.execute(
        "UPDATE tasks SET status='done', bars_count=?, updated_at=unixepoch('now') WHERE id=?",
        (bars, task_id),
    )
    conn.commit()


def mark_skipped(conn: sqlite3.Connection, task_id: int):
    conn.execute(
        "UPDATE tasks SET status='skipped', updated_at=unixepoch('now') WHERE id=?",
        (task_id,),
    )
    conn.commit()


def mark_failed(conn: sqlite3.Connection, task_id: int, error: str):
    conn.execute(
        "UPDATE tasks SET status='failed', error=?, updated_at=unixepoch('now') WHERE id=?",
        (error[:500], task_id),
    )
    conn.commit()


def reset_stale(conn: sqlite3.Connection):
    """Reset in_progress tasks left over from a crashed run."""
    conn.execute(
        "UPDATE tasks SET status='pending', worker_id=NULL WHERE status='in_progress'"
    )
    conn.commit()


# ── Expiry helpers ─────────────────────────────────────────────────────────────

def _parse_expiry(e: str) -> date | None:
    try:
        return datetime.strptime(e, "%d%b%y").date()
    except ValueError:
        return None


def _is_monthly(d: date) -> bool:
    """Last occurrence of that weekday in the month — works for any expiry day."""
    return (d + timedelta(days=7)).month != d.month


def build_tv_symbol(symbol: str, expiry: str, strike: str, opt: str) -> str:
    dd, mmm, yy = expiry[:2], expiry[2:5], expiry[5:7]
    return f"{symbol}{yy}{mmm}{dd}{strike}{opt}"


# ── ATM price from spot data ───────────────────────────────────────────────────

def _read_spot_week(spot_sym: str, from_date: date, to_date: date) -> list[float]:
    """
    Read closing prices from local rawdata CSVs for the given date range.
    Returns list of close prices (may be empty if data not found).
    """
    closes = []
    # Collect all YYYY-MM months in range
    months = set()
    d = from_date.replace(day=1)
    while d <= to_date:
        months.add(d.strftime("%Y-%m"))
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)

    spot_dir = SPOT_DIR / spot_sym
    if not spot_dir.exists():
        # Try flat files (NSE_NIFTY_50_YYYY-MM.csv directly in 1min_indices/)
        spot_dir = SPOT_DIR

    for ym in sorted(months):
        csv_path = spot_dir / f"{spot_sym}_{ym}.csv"
        if not csv_path.exists():
            continue
        try:
            with open(csv_path, newline="") as f:
                for row in csv.DictReader(f):
                    ts_str = row.get("ts", "")
                    if not ts_str:
                        continue
                    # Parse date part only
                    try:
                        bar_date = datetime.fromisoformat(ts_str.replace(" ", "T")[:10]).date()
                    except ValueError:
                        continue
                    if from_date <= bar_date <= to_date:
                        try:
                            closes.append(float(row["close"]))
                        except (ValueError, KeyError):
                            pass
        except Exception as e:
            log.debug(f"Error reading {csv_path}: {e}")

    return closes


def get_atm_price(index_name: str, from_date: date, to_date: date) -> float | None:
    """
    Compute ATM proxy for the expiry period.
    Strategy: midpoint of (week_high + week_low) of close prices.
    Falls back to None if no spot data available.
    """
    spot_sym = SPOT_SYMBOL.get(index_name)
    if not spot_sym:
        return None

    closes = _read_spot_week(spot_sym, from_date, to_date)
    if not closes:
        log.debug(f"No spot data for {index_name} {from_date}→{to_date}")
        return None

    # Midpoint of the week's price range
    return (max(closes) + min(closes)) / 2.0


def select_strikes_atm(
    strikes: list[str],
    atm: float | None,
    n_each_side: int,
) -> list[str]:
    """
    Pick n_each_side strikes below ATM + n_each_side strikes at/above ATM.
    If atm is None, falls back to centre of sorted list.
    Total returned: 2 * n_each_side strikes.
    """
    if not strikes:
        return []

    s = sorted(strikes, key=float)

    if atm is None:
        mid = len(s) // 2
    else:
        # Find index of strike closest to ATM
        mid = min(range(len(s)), key=lambda i: abs(float(s[i]) - atm))

    lo = max(0, mid - n_each_side)
    hi = min(len(s), mid + n_each_side)
    selected = s[lo:hi]

    # Ensure exactly 2*n_each_side if enough strikes exist
    if len(selected) < 2 * n_each_side and len(s) >= 2 * n_each_side:
        if lo == 0:
            hi = min(len(s), 2 * n_each_side)
        else:
            lo = max(0, len(s) - 2 * n_each_side)
        selected = s[lo:hi]

    return selected


# ── Phase 1: Task generation ───────────────────────────────────────────────────

def generate_tasks(creds: dict, progress_cb=None, gen_state: dict | None = None):
    """Fetch all expiries + strikes → insert tasks into DB (idempotent)."""
    conn = _db_conn()

    for symbol in INDICES:
        idx_start = INDEX_START.get(symbol, date(2019, 1, 1))
        weekly_only = symbol in WEEKLY_ONLY

        log.info(f"Fetching expiries for {symbol}")
        r = _get(
            f"{BASE}/hcharts/stx8req/php/getSymbolData_v3.php",
            params={
                "latestOrHistorical": "historical",
                "optionType": "option",
                "defaultSymbol": symbol,
                "getExpiry": "true",
            },
            creds=creds, gen=True,
        )
        all_expiries = r.json().get("expiryDate", [])

        # Filter and sort
        parsed = []
        for e in all_expiries:
            d = _parse_expiry(e)
            if d and d >= idx_start and d <= date.today():
                if weekly_only and _is_monthly(d):
                    continue
                parsed.append((d, e))
        parsed.sort()

        log.info(f"{symbol}: {len(parsed)} expiries to process")

        # Use gen_log — records every processed expiry, even sparse ones with 0 tasks
        processed = {
            r[0] for r in conn.execute(
                "SELECT expiry FROM gen_log WHERE index_name=?", (symbol,)
            ).fetchall()
        }
        skipped = len(processed)
        log.info(f"{symbol}: {len(parsed)} expiries, {skipped} already processed")

        for i, (exp_dt, expiry) in enumerate(parsed):
            prev_dt = idx_start if i == 0 else parsed[i - 1][0] + timedelta(days=1)
            from_date = prev_dt.isoformat()
            to_date   = exp_dt.isoformat()

            if gen_state is not None:
                gen_state[symbol] = {"done": i + 1, "total": len(parsed), "current": expiry}
            if progress_cb:
                progress_cb(symbol, i + 1, len(parsed), expiry, skipped)

            if expiry in processed:
                log.debug(f"SKIP gen {symbol} {expiry} (gen_log)")
                continue

            # Compute ATM from spot data for this expiry's date window
            atm = get_atm_price(symbol, prev_dt, exp_dt)
            atm_log = f"ATM={atm:.0f}" if atm else "ATM=fallback(centre)"
            log.debug(f"{symbol} {expiry} {prev_dt}→{exp_dt} {atm_log}")

            # Fetch strikes for CE + PE
            for opt_type in ["CE", "PE"]:
                r2 = _get(
                    f"{BASE}/hcharts/stx8req/php/getSymbolData_v3.php",
                    params={
                        "latestOrHistorical": "historical",
                        "optionType": opt_type,
                        "defaultSymbol": symbol,
                        "getStrike": "true",
                        "expiryDate": expiry,
                    },
                    creds=creds, gen=True,
                )
                strikes_raw = r2.json().get("strikePrice") or []

                if len(strikes_raw) < MIN_STRIKE_COUNT:
                    log.debug(f"SKIP {symbol} {expiry} {opt_type}: only {len(strikes_raw)} strikes")
                    continue

                # ATM-anchored strike selection (10 below + 10 above)
                selected = select_strikes_atm(strikes_raw, atm, STRIKES_EACH_SIDE)

                rows = [
                    (symbol, expiry, strike, opt_type,
                     build_tv_symbol(symbol, expiry, strike, opt_type),
                     from_date, to_date, atm)
                    for strike in selected
                ]
                conn.executemany(
                    "INSERT OR IGNORE INTO tasks "
                    "(index_name, expiry, strike, opt_type, tv_symbol, from_date, to_date, atm_price) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    rows,
                )
            # Mark expiry processed regardless of task count
            conn.execute(
                "INSERT OR IGNORE INTO gen_log (index_name, expiry) VALUES (?,?)",
                (symbol, expiry),
            )
            conn.commit()

    conn.close()
    log.info("Task generation complete")


# ── Phase 2: Download worker ───────────────────────────────────────────────────

def fetch_ohlcv(tv_symbol: str, from_date: str, to_date: str, creds: dict) -> list[dict]:
    params = {
        "symbol": tv_symbol,
        "resolution": RESOLUTION,
        "from": from_date,
        "to": to_date,
        "u": creds["email"],
        "sid": creds["sid"],
        "DataRequest": 0,
        "firstDataRequest": "true",
        "countback": 999999,
    }
    r = _get(f"{BASE}/getdataFNO_Chart_TV_Charts_Daily_v2.php", params=params, creds=creds)
    try:
        data = r.json()
    except Exception:
        return []
    if data.get("s") == "no_data" or not data.get("t"):
        return []
    return [
        {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}
        for t, o, h, l, c, v in zip(
            data["t"], data["o"], data["h"], data["l"], data["c"], data["v"]
        )
    ]


def _out_path(tv_symbol: str) -> Path:
    idx = next((i for i in INDICES if tv_symbol.startswith(i)), "OTHER")
    d = RAW_DIR / idx
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{tv_symbol}_R{RESOLUTION}.csv"


def save_csv(tv_symbol: str, bars: list[dict]):
    out = _out_path(tv_symbol)
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
    return out


def worker_loop(worker_id: str, creds: dict, state: dict, stop_event: threading.Event):
    """Worker thread: claim → download → mark done. Loops until stop_event set."""
    conn = _db_conn()
    log.info(f"{worker_id} started")

    while not stop_event.is_set():
        task = claim_task(conn, worker_id)
        if task is None:
            # No pending tasks — wait and check again
            time.sleep(2)
            continue

        tv_sym    = task["tv_symbol"]
        from_date = task["from_date"]
        to_date   = task["to_date"]
        task_id   = task["id"]

        state[worker_id] = tv_sym

        # Skip if file already exists
        out = _out_path(tv_sym)
        if out.exists():
            mark_skipped(conn, task_id)
            state["skipped"] = state.get("skipped", 0) + 1
            continue

        try:
            bars = fetch_ohlcv(tv_sym, from_date, to_date, creds)
            if bars:
                save_csv(tv_sym, bars)
                mark_done(conn, task_id, len(bars))
                state["done"] = state.get("done", 0) + 1
                state["session_done"] = state.get("session_done", 0) + 1
                # Append to recent log
                state.setdefault("log", deque(maxlen=12)).appendleft(
                    f"[green]✓[/] {tv_sym}  {len(bars)}b  {from_date}→{to_date}"
                )
                log.info(f"{worker_id} DONE {tv_sym}: {len(bars)} bars")
            else:
                mark_skipped(conn, task_id)
                state["skipped"] = state.get("skipped", 0) + 1
                log.debug(f"{worker_id} NODATA {tv_sym}")
        except RuntimeError as e:
            if "SESSION_EXPIRED" in str(e):
                log.error("Session expired — stopping workers")
                stop_event.set()
                break
            mark_failed(conn, task_id, str(e))
            state["failed"] = state.get("failed", 0) + 1
            state.setdefault("log", deque(maxlen=12)).appendleft(
                f"[red]✗[/] {tv_sym}  {str(e)[:50]}"
            )
            log.error(f"{worker_id} FAILED {tv_sym}: {e}")
        except Exception as e:
            mark_failed(conn, task_id, str(e))
            state["failed"] = state.get("failed", 0) + 1
            log.error(f"{worker_id} ERROR {tv_sym}: {e}")

        state[worker_id] = "—"

    conn.close()
    state[worker_id] = "[dim]stopped[/]"
    log.info(f"{worker_id} stopped")


# ── UI ─────────────────────────────────────────────────────────────────────────

def build_ui(counts: dict, idx_counts: dict, state: dict, start_time: float, worker_ids: list[str], gen_state: dict | None = None, gen_log_counts: dict | None = None) -> Layout:
    gen_height = 2 + len(INDICES) if gen_state and not gen_state.get("done") else 0
    layout = Layout()
    layout.split_column(
        Layout(name="gen",    size=gen_height) if gen_height else Layout(name="gen", size=0, visible=False),
        Layout(name="header", size=4),
        Layout(name="body",   size=16),
        Layout(name="footer", size=16),
    )
    layout["body"].split_row(
        Layout(name="stats",   ratio=1),
        Layout(name="workers", ratio=1),
        Layout(name="indices", ratio=3),
    )

    total    = counts.get("total", 0)
    done     = counts.get("done", 0)
    skipped  = counts.get("skipped", 0)
    failed   = counts.get("failed", 0)
    pending  = counts.get("pending", 0)
    in_prog  = counts.get("in_progress", 0)
    finished = done + skipped
    elapsed      = time.time() - start_time
    session_done = state.get("session_done", 0)

    # Rate: based on THIS session's completions only — not cumulative from prior runs
    if elapsed >= 30:
        rate = session_done / elapsed * 60
    elif elapsed >= 5:
        rate = session_done / elapsed * 60 * (elapsed / 30)  # damp first 30s
    else:
        rate = 0.0

    remaining = (pending + in_prog) / (rate / 60) if rate > 1 else 0
    eta_str   = str(timedelta(seconds=int(remaining))) if remaining > 0 else "calculating..."

    pct = finished / total * 100 if total else 0
    bar_w = 48
    bf  = int(pct / 100 * bar_w)
    bar = f"[green]{'█' * bf}[/][dim]{'░' * (bar_w - bf)}[/]"

    # ── Generation panel (shown only while gen is running) ────────────────────
    if gen_height > 0 and gen_state:
        gt = Table.grid(padding=(0, 2))
        gt.add_column(min_width=12, style="bold")
        gt.add_column(min_width=6,  justify="right")
        gt.add_column(min_width=6,  justify="right")
        gt.add_column(min_width=24)
        for idx in INDICES:
            gs   = gen_state.get(idx, {})
            done = gs.get("done", 0)
            tot  = gs.get("total", 0)
            cur  = gs.get("current", "waiting...")
            if done == tot and tot > 0:
                bar = f"[green]{'█' * 20}[/] done"
            elif tot > 0:
                bf  = int(done / tot * 20)
                bar = f"[cyan]{'█' * bf}[/][dim]{'░' * (20-bf)}[/] {cur}"
            else:
                bar = f"[dim]{'░' * 20}[/] pending"
            gt.add_row(idx, str(done), f"/{tot}" if tot else "/?", bar)
        layout["gen"].update(Panel(gt, title="[cyan]Phase 1 — Generating tasks[/]"))

    # ── Header ────────────────────────────────────────────────────────────────
    layout["header"].update(Panel(
        f"{bar} [bold]{pct:.1f}%[/]\n"
        f"[green]{done:,} done[/]  [yellow]{skipped} skip[/]  "
        f"[red]{failed} fail[/]  [cyan]{pending:,} pending[/]  "
        f"[white]{rate:.1f}/min[/]  ETA [bold]{eta_str}[/]  "
        f"elapsed {str(timedelta(seconds=int(elapsed)))}",
        title="[bold cyan]icharts F&O Coordinator[/]",
    ))

    # ── Stats ─────────────────────────────────────────────────────────────────
    st = Table.grid(padding=(0, 2))
    st.add_column(justify="right", style="dim", min_width=10)
    st.add_column(justify="left",  min_width=10)
    st.add_row("Total",     f"[bold]{total:,}[/]")
    st.add_row("Done",      f"[green]{done:,}[/]")
    st.add_row("Skipped",   f"[yellow]{skipped:,}[/]")
    st.add_row("Failed",    f"[red]{failed:,}[/]")
    st.add_row("Pending",   f"[cyan]{pending:,}[/]")
    st.add_row("In-flight", f"[magenta]{in_prog}[/]")
    st.add_row("Session ↓", f"[bold]{session_done:,}[/]")
    st.add_row("Rate",      f"[bold]{rate:.1f}[/]/min")
    st.add_row("ETA",       eta_str)

    # Generation progress rows
    st.add_row("", "")
    st.add_row("[bold]Gen Progress[/]", "")
    EXPIRY_TOTALS_STATS = {"NIFTY": 382, "BANKNIFTY": 327, "MIDCPNIFTY": 177, "SENSEX": 136}
    for idx in INDICES:
        gd  = (gen_log_counts or {}).get(idx, 0)
        tot = EXPIRY_TOTALS_STATS.get(idx, "?")
        pct = gd / tot * 100 if isinstance(tot, int) and tot else 0
        if gd >= (tot or 0):
            val = f"[green]{gd}/{tot} ✓[/]"
        else:
            val = f"[cyan]{gd}[/][dim]/{tot}[/] [white]{pct:.0f}%[/]"
        st.add_row(f"  {idx}", val)

    layout["stats"].update(Panel(st, title="Stats"))

    # ── Workers ───────────────────────────────────────────────────────────────
    wt = Table.grid(padding=(0, 1))
    wt.add_column(style="bold cyan", min_width=4)
    wt.add_column(min_width=28)
    for wid in worker_ids:
        task = state.get(wid, "—")
        wt.add_row(wid, Text(str(task)[:36], overflow="ellipsis"))
    layout["workers"].update(Panel(wt, title=f"Workers ({len(worker_ids)})"))

    # ── Per-index ─────────────────────────────────────────────────────────────
    # Expected total expiries per index (from live gen_state + known totals)
    EXPIRY_TOTALS = {"NIFTY": 382, "BANKNIFTY": 327, "MIDCPNIFTY": 177, "SENSEX": 136}

    it = Table(show_header=True, header_style="bold white", box=None, padding=(0, 2))
    it.add_column("Index",      min_width=12, style="bold")
    it.add_column("Expiries",   justify="right", style="magenta", min_width=10)
    it.add_column("Done",       justify="right", style="green",   min_width=6)
    it.add_column("Skipped",    justify="right", style="yellow",  min_width=7)
    it.add_column("Failed",     justify="right", style="red",     min_width=6)
    it.add_column("Pending",    justify="right", style="cyan",    min_width=8)
    it.add_column("Progress",   min_width=22)
    for idx in INDICES:
        c     = idx_counts.get(idx, {})
        d_    = c.get("done", 0) + c.get("skipped", 0)
        t_    = sum(c.values()) if c else 0
        p_    = c.get("pending", 0)
        pct_  = d_ / t_ * 100 if t_ else 0
        bf_   = int(pct_ / 100 * 18)
        ibar  = f"[green]{'█' * bf_}[/][dim]{'░' * (18 - bf_)}[/] {pct_:.0f}%"

        # Gen progress: expiries processed / total
        gen_done_n = (gen_log_counts or {}).get(idx, 0)
        exp_total  = EXPIRY_TOTALS.get(idx, "?")
        if gen_done_n >= exp_total:
            gen_str = f"[green]{gen_done_n}/{exp_total}[/]"
        elif gen_done_n > 0:
            gen_str = f"[cyan]{gen_done_n}[/][dim]/{exp_total}[/]"
        else:
            gen_str = f"[dim]0/{exp_total}[/]"

        it.add_row(
            idx,
            gen_str,
            str(c.get("done", 0)),
            str(c.get("skipped", 0)),
            str(c.get("failed", 0)),
            str(p_) if p_ else "[dim]0[/]",
            ibar,
        )
    layout["indices"].update(Panel(it, title="Per Index"))

    # ── Recent log ────────────────────────────────────────────────────────────
    lines     = list(state.get("log", deque()))
    log_text  = "\n".join(lines) if lines else "[dim]waiting for downloads...[/]"
    layout["footer"].update(Panel(log_text, title="Recent Downloads"))

    return layout


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers",       type=int, default=4)
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--status",        action="store_true")
    parser.add_argument("--reset-failed",  action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    init_db()

    if args.status:
        conn = _db_conn()
        c = task_counts(conn)
        print(f"Total: {c['total']:,}  Done: {c['done']:,}  Skipped: {c['skipped']:,}  "
              f"Failed: {c['failed']:,}  Pending: {c['pending']:,}")
        ic = index_counts(conn)
        for idx, counts in ic.items():
            print(f"  {idx}: {counts}")
        conn.close()
        return

    creds = ensure_auth(auto_refresh=True)

    if args.reset_failed:
        with _db_conn() as conn:
            n = conn.execute(
                "UPDATE tasks SET status='pending', error=NULL WHERE status='failed'"
            ).rowcount
            conn.commit()
        print(f"Reset {n} failed tasks to pending")
        if not args.download_only and not args.generate_only:
            return

    # Reset stale in_progress from prior run
    with _db_conn() as conn:
        reset_stale(conn)

    console = Console()

    # Hoist before Phase 1 so _run_gen closure can reference them
    gen_done   = threading.Event()
    gen_thread = None
    gen_state  = {"done": True}   # default: no generation

    # ── Phase 1: Generate tasks ─────────────────────────────────────────────
    if not args.download_only:
        conn = _db_conn()
        existing = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        conn.close()

        gen_state = {"done": False}

        def _run_gen():
            generate_tasks(creds, gen_state=gen_state)
            conn2 = _db_conn()
            conn2.execute("SELECT COUNT(*) FROM tasks").fetchone()
            conn2.close()
            gen_state["done"] = True
            gen_done.set()

        gen_thread = threading.Thread(target=_run_gen, daemon=False, name="generator")
        gen_thread.start()

    if args.generate_only:
        return

    # ── Phase 2: Download ───────────────────────────────────────────────────
    conn = _db_conn()
    counts = task_counts(conn)
    conn.close()

    if args.download_only:
        gen_done.set()

    n_workers = args.workers
    worker_ids = [f"W{i+1}" for i in range(n_workers)]
    state: dict = {"log": deque(maxlen=12)}
    for wid in worker_ids:
        state[wid] = "—"

    stop_event = threading.Event()
    threads = []
    for wid in worker_ids:
        t = threading.Thread(
            target=worker_loop,
            args=(wid, creds, state, stop_event),
            name=wid,
            daemon=True,
        )
        threads.append(t)

    start_time = time.time()
    state["session_done"] = 0   # only this session's completions
    for t in threads:
        t.start()

    console.print(f"[green]Started {n_workers} workers. Press Ctrl+C to pause.[/]\n")

    try:
        with Live(console=console, refresh_per_second=2, screen=False) as live:
            while True:
                conn = _db_conn()
                counts    = task_counts(conn)
                idx_cnts  = index_counts(conn)
                gen_log_counts = {
                    r[0]: r[1] for r in conn.execute(
                        "SELECT index_name, COUNT(*) FROM gen_log GROUP BY index_name"
                    ).fetchall()
                }
                conn.close()

                live.update(build_ui(counts, idx_cnts, state, start_time, worker_ids, gen_state, gen_log_counts))

                pending = counts.get("pending", 0) + counts.get("in_progress", 0)
                if pending == 0:
                    if gen_done.is_set() or args.download_only:
                        # Generator finished and queue empty — truly done
                        stop_event.set()
                        break
                    # else: generator still running — workers keep polling for new tasks

                time.sleep(0.5)

    except KeyboardInterrupt:
        console.print("\n[yellow]Pausing — waiting for workers to finish current tasks...[/]")
        stop_event.set()

    for t in threads:
        t.join(timeout=30)

    # Wait for generator to finish if still running (non-daemon)
    if gen_thread is not None:
        gen_thread.join(timeout=300)

    conn = _db_conn()
    final = task_counts(conn)
    conn.close()
    console.print(
        f"\n[bold]Final:[/] done={final['done']:,}  skipped={final['skipped']:,}  "
        f"failed={final['failed']:,}  pending={final['pending']:,}"
    )


if __name__ == "__main__":
    main()
