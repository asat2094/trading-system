"""Targeted gap-fill: Nifty500 + FnO equity + NSE/BSE index symbols.

Fetches only missing dates. skip_existing=True per symbol.
Rate: 150 RPM (leaves headroom if Temporal worker also active).
Concurrency: 8 symbols in parallel.

Usage:
    cd backend && PYTHONPATH=. .venv/bin/python scripts/backfill_gaps.py [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time as _time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_ENV = Path(__file__).parent.parent.parent / ".env"
if _ENV.exists():
    from dotenv import load_dotenv; load_dotenv(_ENV)

import httpx
import psycopg2

from core.config import settings
from core.universe import build_trading_universe, get_index_questdb_symbols, questdb_to_index

# ── Rate limiter ──────────────────────────────────────────────────────────────
# 150 RPM — conservative; Temporal worker may add ~50 RPM concurrently.

class _TokenBucket:
    def __init__(self, rate_per_min: int) -> None:
        self._rate     = rate_per_min / 60.0
        self._capacity = float(rate_per_min)
        self._tokens   = float(rate_per_min)
        self._last     = _time.monotonic()
        self._lock     = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = _time.monotonic()
                self._tokens = min(
                    self._capacity,
                    self._tokens + (now - self._last) * self._rate,
                )
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            _time.sleep(wait)

_limiter = _TokenBucket(rate_per_min=150)

# ── Kite MCP constants ────────────────────────────────────────────────────────
MCP_URL            = "https://mcp.kite.trade/mcp"
SESSION_FILE       = Path(__file__).parent / ".kitemcp_session"
EQUITY_TOKEN_FILE  = Path(__file__).parent / ".kitemcp_tokens.json"
INDEX_TOKEN_FILE   = Path(__file__).parent / ".kitemcp_index_tokens.json"
IST_OFFSET         = timedelta(hours=5, minutes=30)


# ── Kite helpers ──────────────────────────────────────────────────────────────

def _session_id() -> str:
    if SESSION_FILE.exists():
        return SESSION_FILE.read_text().strip()
    raise RuntimeError("No Kite MCP session — run backfill_1min_kitemcp.py --auth first")


def _load_cache(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _save_cache(path: Path, cache: dict) -> None:
    path.write_text(json.dumps(cache, indent=2))


def _mcp_post(client: httpx.Client, session_id: str, tool: str, args: dict) -> dict:
    """Single MCP call — rate-limited, raises on HTTP error."""
    _limiter.acquire()
    resp = client.post(MCP_URL, json={
        "jsonrpc": "2.0", "method": "tools/call",
        "params": {"name": tool, "arguments": args}, "id": 1,
    }, headers={"Content-Type": "application/json", "mcp-session-id": session_id},
    timeout=30)
    resp.raise_for_status()
    return resp.json()


def _get_text(r: dict) -> str:
    return r.get("result", {}).get("content", [{}])[0].get("text", "")


def _resolve_equity_token(session_id: str, symbol: str, cache: dict) -> int | None:
    """NSE EQ token for equity symbols."""
    if symbol in cache:
        return cache[symbol]
    with httpx.Client(timeout=30) as c:
        r = _mcp_post(c, session_id, "search_instruments", {"query": f"NSE:{symbol}"})
        for inst in json.loads(_get_text(r)):
            if (inst.get("tradingsymbol") == symbol
                    and inst.get("exchange") == "NSE"
                    and inst.get("instrument_type") == "EQ"):
                cache[symbol] = inst["instrument_token"]
                _save_cache(EQUITY_TOKEN_FILE, cache)
                return cache[symbol]
    return None


def _resolve_index_token(session_id: str, questdb_sym: str, cache: dict) -> int | None:
    """INDICES-segment token for index symbols (NSE_NIFTY_50 etc.)."""
    pair = questdb_to_index(questdb_sym)
    if pair is None:
        return None
    tradingsymbol, exchange = pair
    key = f"{exchange}:{tradingsymbol}"
    if key in cache:
        return cache[key]
    with httpx.Client(timeout=30) as c:
        r = _mcp_post(c, session_id, "search_instruments",
                      {"query": f"{exchange}:{tradingsymbol}"})
        for inst in json.loads(_get_text(r)):
            if (inst.get("tradingsymbol") == tradingsymbol
                    and inst.get("exchange") == exchange
                    and inst.get("segment") == "INDICES"):
                cache[key] = inst["instrument_token"]
                _save_cache(INDEX_TOKEN_FILE, cache)
                return cache[key]
    return None


def _fetch_candles(
    session_id: str, token: int, from_date: str, to_date: str
) -> list:
    with httpx.Client(timeout=30) as c:
        r = _mcp_post(c, session_id, "get_historical_data", {
            "instrument_token": token, "interval": "minute",
            "from_date": f"{from_date} 09:00:00",
            "to_date":   f"{to_date} 15:30:00",
        })
        text = _get_text(r)
        if "error" in text.lower() or "failed" in text.lower():
            raise RuntimeError(f"Kite error: {text[:200]}")
        return json.loads(text)


def _to_utc(ts_str: str) -> str:
    ts = datetime.fromisoformat(ts_str)
    if ts.utcoffset() is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        ts -= IST_OFFSET
    return ts.strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def _write_questdb(candles: list, symbol: str) -> int:
    if not candles:
        return 0
    rows = [(_to_utc(c["date"]), symbol,
             c["open"], c["high"], c["low"], c["close"], int(c["volume"]))
            for c in candles]
    conn = psycopg2.connect(settings.QUESTDB_URL)
    conn.autocommit = True
    try:
        conn.cursor().executemany(
            "INSERT INTO ohlcv_1min (ts,symbol,open,high,low,close,volume) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            rows,
        )
    finally:
        conn.close()
    return len(rows)


def _missing_dates(symbol: str, from_date: str, to_date: str) -> list[str]:
    conn = psycopg2.connect(settings.QUESTDB_URL)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT cast(ts as date) FROM ohlcv_1min "
            "WHERE symbol=$1 AND ts BETWEEN $2 AND $3",
            (symbol, from_date, to_date),
        )
        existing = {str(r[0])[:10] for r in cur.fetchall()}
    finally:
        conn.close()
    start = date.fromisoformat(from_date)
    end   = date.fromisoformat(to_date)
    return [
        (start + timedelta(days=i)).isoformat()
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() < 5
        and (start + timedelta(days=i)).isoformat() not in existing
    ]


def _build_chunks(missing: list[str]) -> list[tuple[str, str]]:
    """7-day windows from newest → oldest over missing dates."""
    from_dt = date.fromisoformat(missing[0])
    to_dt   = date.fromisoformat(missing[-1])
    chunks, d = [], to_dt
    while d >= from_dt:
        start = max(d - timedelta(days=6), from_dt)
        chunks.append((start.isoformat(), d.isoformat()))
        d = start - timedelta(days=1)
    return chunks


# ── Worker coroutine ──────────────────────────────────────────────────────────

counters = {"done": 0, "skipped": 0, "no_token": 0, "failed": 0, "total_rows": 0}
_counter_lock = threading.Lock()


async def backfill_one(
    symbol: str,
    session_id: str,
    equity_cache: dict,
    index_cache: dict,
    from_date: str,
    to_date: str,
    sem: asyncio.Semaphore,
    is_index: bool,
    dry_run: bool,
) -> None:
    async with sem:
        loop = asyncio.get_event_loop()

        # Resolve token
        if is_index:
            token = await loop.run_in_executor(
                None, _resolve_index_token, session_id, symbol, index_cache)
        else:
            token = await loop.run_in_executor(
                None, _resolve_equity_token, session_id, symbol, equity_cache)

        if token is None:
            print(f"  [{symbol}] no token", flush=True)
            with _counter_lock: counters["no_token"] += 1
            return

        # Find missing dates
        missing = await loop.run_in_executor(None, _missing_dates, symbol, from_date, to_date)
        if not missing:
            with _counter_lock: counters["skipped"] += 1
            return

        if dry_run:
            print(f"  [DRY] {symbol}  missing={missing}", flush=True)
            with _counter_lock: counters["done"] += 1
            return

        chunks = _build_chunks(missing)
        sym_rows = 0
        for cf, ct in chunks:
            try:
                candles = await loop.run_in_executor(
                    None, _fetch_candles, session_id, token, cf, ct)
                rows = await loop.run_in_executor(
                    None, _write_questdb, candles, symbol)
                sym_rows += rows
                if rows:
                    print(f"  {symbol}  {cf}→{ct}  +{rows} rows", flush=True)
            except Exception as exc:
                print(f"  {symbol}  {cf}→{ct}  FAIL: {exc}", flush=True)
                with _counter_lock: counters["failed"] += 1

        with _counter_lock:
            counters["done"] += 1
            counters["total_rows"] += sym_rows


# ── Gap discovery ─────────────────────────────────────────────────────────────

def find_equity_gaps(from_date: str, to_date: str, universe: set[str]) -> set[str]:
    """Equity symbols missing any weekday in [from_date, to_date]."""
    conn = psycopg2.connect(settings.QUESTDB_URL)
    cur  = conn.cursor()
    missing: set[str] = set()
    start = date.fromisoformat(from_date)
    end   = date.fromisoformat(to_date)
    check_days = [
        (start + timedelta(days=i)).isoformat()
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() < 5
    ]
    for d in check_days:
        cur.execute(f"""SELECT symbol FROM (SELECT symbol, ts FROM ohlcv_1min
            WHERE ts >= '{d}T00:00:00Z' AND ts < '{d}T23:59:59Z'
            LATEST ON ts PARTITION BY symbol)""")
        have = {r[0] for r in cur.fetchall()}
        missing |= (universe - have)
    conn.close()
    return missing


def find_index_gaps(from_date: str, to_date: str, idx_syms: list[str]) -> set[str]:
    """Index symbols missing any weekday in [from_date, to_date]."""
    return find_equity_gaps(from_date, to_date, set(idx_syms))


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(dry_run: bool) -> None:
    # ── Universe
    universe  = set(s for s in build_trading_universe() if not s.startswith("DUMMY"))
    idx_syms  = get_index_questdb_symbols()

    # ── Gap window: last 30 days, only weekdays
    to_date   = date.today().isoformat()
    from_date = (date.today() - timedelta(days=30)).isoformat()

    print(f"Gap window: {from_date} → {to_date}")
    print("Finding missing equity symbols...", flush=True)
    equity_missing = find_equity_gaps(from_date, to_date, universe)
    equity_missing = {s for s in equity_missing if not s.startswith("DUMMY")}

    print("Finding missing index symbols...", flush=True)
    index_missing = find_index_gaps(from_date, to_date, idx_syms)

    print(f"\nEquity missing: {len(equity_missing)} symbols")
    print(f"Index  missing: {len(index_missing)} symbols")
    print(f"Rate limit: 150 RPM  |  Concurrency: 8")
    if dry_run:
        print("DRY RUN — no writes")
    print()

    session_id   = _session_id()
    equity_cache = _load_cache(EQUITY_TOKEN_FILE)
    index_cache  = _load_cache(INDEX_TOKEN_FILE)
    sem          = asyncio.Semaphore(8)

    tasks = [
        backfill_one(sym, session_id, equity_cache, index_cache,
                     from_date, to_date, sem, is_index=False, dry_run=dry_run)
        for sym in sorted(equity_missing)
    ] + [
        backfill_one(sym, session_id, equity_cache, index_cache,
                     from_date, to_date, sem, is_index=True, dry_run=dry_run)
        for sym in sorted(index_missing)
    ]

    await asyncio.gather(*tasks)

    print()
    print(f"Equity: {len(equity_missing)} symbols  |  Index: {len(index_missing)} symbols")
    print(f"Done: {counters['done']}  Skipped: {counters['skipped']}  "
          f"No-token: {counters['no_token']}  Failed: {counters['failed']}  "
          f"Total rows: {counters['total_rows']:,}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show gaps without writing to QuestDB")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
