"""Fetch 1-min OHLCV from Kite MCP for a symbol + date range, load into QuestDB."""
import asyncio
import json
import threading
import time
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import httpx
from temporalio import activity

from core.logging import get_logger
from core.metrics import ingestion_rows, ingestion_failures

log = get_logger(__name__)

MCP_URL      = "https://mcp.kite.trade/mcp"
SESSION_FILE = Path(__file__).parent.parent.parent / "scripts" / ".kitemcp_session"
TOKEN_FILE   = Path(__file__).parent.parent.parent / "scripts" / ".kitemcp_tokens.json"
IST_OFFSET   = timedelta(hours=5, minutes=30)


class _TokenBucket:
    """Thread-safe token bucket rate limiter."""

    def __init__(self, rate_per_min: int) -> None:
        self._rate     = rate_per_min / 60.0   # tokens per second
        self._capacity = float(rate_per_min)
        self._tokens   = float(rate_per_min)   # start full
        self._last     = time.monotonic()
        self._lock     = threading.Lock()

    def acquire(self) -> None:
        """Block the calling thread until a token is available."""
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self._capacity,
                    self._tokens + (now - self._last) * self._rate,
                )
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            time.sleep(wait)


# 180 RPM — 10% headroom below the 200 RPM hard limit.
# Shared across all activity threads in this worker process.
_kite_limiter = _TokenBucket(rate_per_min=180)


def _session_id() -> str:
    if SESSION_FILE.exists():
        return SESSION_FILE.read_text().strip()
    raise RuntimeError("No Kite MCP session. Authenticate first via scripts/backfill_1min_kitemcp.py --auth")


def _token_cache() -> dict:
    return json.loads(TOKEN_FILE.read_text()) if TOKEN_FILE.exists() else {}


def _mcp_call(client: httpx.Client, session_id: str, tool: str, args: dict) -> dict:
    _kite_limiter.acquire()   # enforce ≤180 RPM globally across all threads
    resp = client.post(MCP_URL, json={
        "jsonrpc": "2.0", "method": "tools/call",
        "params": {"name": tool, "arguments": args}, "id": 1,
    }, headers={"Content-Type": "application/json", "mcp-session-id": session_id},
    timeout=30)
    resp.raise_for_status()
    return resp.json()


def _get_text(result: dict) -> str:
    return result.get("result", {}).get("content", [{}])[0].get("text", "")


def _resolve_token(session_id: str, symbol: str, cache: dict) -> int | None:
    """Look up instrument token, update cache."""
    if symbol in cache:
        return cache[symbol]
    with httpx.Client(timeout=30) as client:
        r = _mcp_call(client, session_id, "search_instruments", {"query": f"NSE:{symbol}"})
        instruments = json.loads(_get_text(r))
        for inst in instruments:
            if (inst.get("tradingsymbol") == symbol
                    and inst.get("exchange") == "NSE"
                    and inst.get("instrument_type") == "EQ"):
                token = inst["instrument_token"]
                cache[symbol] = token
                TOKEN_FILE.write_text(json.dumps(cache, indent=2))
                return token
    return None


def _fetch_candles(session_id: str, token: int, from_date: str, to_date: str) -> list:
    """Fetch 1-min candles from Kite MCP. from_date/to_date: YYYY-MM-DD."""
    with httpx.Client(timeout=30) as client:
        r = _mcp_call(client, session_id, "get_historical_data", {
            "instrument_token": token,
            "interval": "minute",
            "from_date": f"{from_date} 09:00:00",
            "to_date":   f"{to_date} 15:30:00",
        })
        text = _get_text(r)
        if "error" in text.lower() or "failed" in text.lower():
            raise RuntimeError(f"Kite MCP error: {text[:200]}")
        return json.loads(text)


def _to_utc(ts_str: str) -> str:
    """Convert IST timestamp string to UTC ISO string for QuestDB."""
    ts = datetime.fromisoformat(ts_str)
    if ts.utcoffset() is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        ts = ts - IST_OFFSET          # assume IST if no tzinfo
    return ts.strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def _bulk_import_questdb(candles: list, symbol: str) -> int:
    """Bulk-import candles into QuestDB via psycopg2 executemany."""
    if not candles:
        return 0

    import psycopg2
    from core.config import settings

    rows = [
        (_to_utc(c.get("date", "")), symbol,
         c["open"], c["high"], c["low"], c["close"], int(c["volume"]))
        for c in candles
    ]

    conn = psycopg2.connect(settings.QUESTDB_URL)
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.executemany(
            "INSERT INTO ohlcv_1min (ts,symbol,open,high,low,close,volume) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            rows,
        )
    finally:
        conn.close()

    return len(rows)


def _missing_dates_for_symbol(symbol: str, from_date: str, to_date: str) -> list[str]:
    """Return weekdays in [from_date, to_date] that have no data in QuestDB."""
    import psycopg2
    from core.config import settings

    conn = psycopg2.connect(settings.QUESTDB_URL)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT cast(ts as date) FROM ohlcv_1min "
            "WHERE symbol=$1 AND ts BETWEEN $2 AND $3",
            (symbol, from_date, to_date),
        )
        existing = {str(row[0])[:10] for row in cur.fetchall()}
    finally:
        conn.close()

    start = datetime.fromisoformat(from_date).date()
    end   = datetime.fromisoformat(to_date).date()
    delta = (end - start).days + 1

    from datetime import date
    missing = []
    for i in range(delta):
        d = start + timedelta(days=i)
        if d.weekday() < 5 and d.isoformat() not in existing:   # Mon-Fri only
            missing.append(d.isoformat())
    return missing


@activity.defn(name="fetch_kitemcp_1min")
async def activity_fn(
    symbol: str,
    from_date: str,
    to_date: str,
    skip_existing: bool = True,
) -> dict:
    """
    Fetch 1-min OHLCV from Kite MCP for `symbol` over [from_date, to_date]
    and bulk-import into QuestDB ohlcv_1min.

    Args:
        symbol:        NSE trading symbol e.g. "CDSL"
        from_date:     YYYY-MM-DD
        to_date:       YYYY-MM-DD
        skip_existing: if True, skip date ranges already in QuestDB
    """
    loop = asyncio.get_event_loop()

    session_id = await loop.run_in_executor(None, _session_id)
    cache      = await loop.run_in_executor(None, _token_cache)
    token      = await loop.run_in_executor(None, _resolve_token, session_id, symbol, cache)

    if token is None:
        log.warning("kitemcp_token_not_found", symbol=symbol)
        ingestion_failures.labels(source="kitemcp_1min").inc()
        return {"symbol": symbol, "rows": 0, "error": "token_not_found"}

    # Find which weeks are missing
    if skip_existing:
        missing = await loop.run_in_executor(
            None, _missing_dates_for_symbol, symbol, from_date, to_date
        )
        if not missing:
            log.info("kitemcp_1min_already_complete", symbol=symbol,
                     from_date=from_date, to_date=to_date)
            return {"symbol": symbol, "rows": 0, "skipped": True}
        # Build weekly chunks covering missing dates
        from_dt = date.fromisoformat(missing[0])
        to_dt   = date.fromisoformat(missing[-1])
    else:
        from_dt = date.fromisoformat(from_date)
        to_dt   = date.fromisoformat(to_date)

    # Chunk into 7-day windows
    chunks = []
    d = to_dt
    end_date = from_dt
    while d >= end_date:
        start = max(d - timedelta(days=6), end_date)
        chunks.append((start.isoformat(), d.isoformat()))
        d = start - timedelta(days=1)

    total_rows = 0
    for chunk_from, chunk_to in chunks:
        try:
            candles = await loop.run_in_executor(
                None, _fetch_candles, session_id, token, chunk_from, chunk_to
            )
            rows = await loop.run_in_executor(
                None, _bulk_import_questdb, candles, symbol
            )
            total_rows += rows
            log.info("kitemcp_1min_chunk_ok",
                     symbol=symbol, from_date=chunk_from, to_date=chunk_to, rows=rows)
        except Exception as exc:
            log.warning("kitemcp_1min_chunk_fail",
                        symbol=symbol, from_date=chunk_from, error=str(exc))
            ingestion_failures.labels(source="kitemcp_1min").inc()

    ingestion_rows.labels(source="kitemcp_1min", timeframe="1min").inc(total_rows)
    log.info("kitemcp_1min_done", symbol=symbol, rows=total_rows)
    return {"symbol": symbol, "rows": total_rows}
