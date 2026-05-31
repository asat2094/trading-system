"""Daily 1-min OHLCV refresh + gap backfill via Kite Connect.

Fetches today's data for every symbol in the stocks table, then detects and
fills any gaps in QuestDB going back GAP_LOOKBACK_DAYS.

Writes directly to QuestDB via ILP (port 9009) — no Parquet intermediate,
data available for scanning immediately after run.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DAILY WORKFLOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Authenticate once per morning (before 9:15 AM IST):
       cd backend && PYTHONPATH=. python scripts/backfill_1min_kite.py --auth

2. Cron runs automatically after market close (3:30 PM IST = 10:00 UTC):
       PYTHONPATH=. python scripts/daily_refresh.py

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRON SETUP  (crontab -e)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Run Mon–Fri at 4:15 PM IST (10:45 UTC) — 45 min after NSE close
45 10 * * 1-5 cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/backend && PYTHONPATH=. .venv/bin/python scripts/daily_refresh.py >> /tmp/daily_refresh.log 2>&1

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MANUAL RUN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Today only:
    PYTHONPATH=. python scripts/daily_refresh.py

    # Override gap lookback:
    PYTHONPATH=. python scripts/daily_refresh.py --gap-days 60

    # Dry-run (show gaps, don't fetch):
    PYTHONPATH=. python scripts/daily_refresh.py --dry-run
"""

from __future__ import annotations

import argparse
import errno
import os
import socket
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

TOKEN_FILE  = Path(__file__).parent / ".kite_access_token"
QDB_HOST    = "localhost"
QDB_ILP_PORT = 9009
TABLE       = "ohlcv_1min"
BATCH_LINES = 2000
IST_OFFSET  = timedelta(hours=5, minutes=30)
GAP_LOOKBACK_DAYS = 30   # how far back to scan for gaps
CHUNK_DAYS  = 59          # Kite max window for minute data
WORKERS     = 6           # concurrent symbol workers


# ─────────────────────────────────────────────────────────────────────────────
# Token
# ─────────────────────────────────────────────────────────────────────────────

def load_token() -> str:
    token = os.environ.get("KITE_ACCESS_TOKEN", "")
    if not token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
    return token


def check_token_fresh() -> str:
    """Return access token or exit with clear message."""
    token = load_token()
    if not token:
        print(
            "[daily_refresh] ERROR: No Kite access token found.\n"
            "  Run: cd backend && PYTHONPATH=. python scripts/backfill_1min_kite.py --auth\n"
            "  Then re-run this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Token file mtime check — warn if older than 24h (may still work, Kite tokens last 1 day)
    if TOKEN_FILE.exists():
        age_h = (time.time() - TOKEN_FILE.stat().st_mtime) / 3600
        if age_h > 20:
            print(
                f"[daily_refresh] WARNING: Access token is {age_h:.1f}h old — may be stale.\n"
                f"  If you see auth errors, run: python scripts/backfill_1min_kite.py --auth",
                file=sys.stderr,
            )
    return token


# ─────────────────────────────────────────────────────────────────────────────
# Kite client
# ─────────────────────────────────────────────────────────────────────────────

def get_kite(access_token: str):
    from kiteconnect import KiteConnect
    api_key = os.environ.get("KITE_API_KEY", "")
    if not api_key:
        print("[daily_refresh] ERROR: KITE_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    return kite


def build_token_map(kite) -> dict[str, int]:
    instruments = kite.instruments("NSE")
    return {
        inst["tradingsymbol"]: inst["instrument_token"]
        for inst in instruments
        if inst.get("instrument_type") == "EQ" and inst.get("segment") == "NSE"
    }


# ─────────────────────────────────────────────────────────────────────────────
# QuestDB gap detection
# ─────────────────────────────────────────────────────────────────────────────

def get_latest_dates(symbols: list[str]) -> dict[str, date | None]:
    """Return {symbol: latest_date_in_qdb} for each symbol. None if no data."""
    import psycopg2
    from core.config import settings

    conn = psycopg2.connect(settings.QUESTDB_URL)
    result: dict[str, date | None] = {s: None for s in symbols}
    try:
        with conn.cursor() as cur:
            # Single query: latest ts per symbol
            sym_list = "', '".join(symbols)
            cur.execute(
                f"SELECT symbol, MAX(ts) FROM {TABLE} "
                f"WHERE symbol IN ('{sym_list}') "
                f"SAMPLE BY 1d FILL(NONE) "
                f"ORDER BY symbol"
            )
            # SAMPLE BY doesn't give MAX per symbol — use direct GROUP BY equivalent
            # QuestDB doesn't support GROUP BY on timestamp in all versions; use LATEST ON

        # Alternative: use timestamp sub-queries per symbol batch is slow.
        # Best: query LATEST ON ts PARTITION BY symbol — returns last row per symbol.
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT symbol, ts FROM {TABLE} "
                f"WHERE symbol IN ('{sym_list}') "
                f"LATEST ON ts PARTITION BY symbol"
            )
            for row in cur.fetchall():
                sym, ts = row[0], row[1]
                if ts is not None:
                    result[sym] = ts.date() if hasattr(ts, "date") else ts
    finally:
        conn.close()
    return result


def compute_gaps(
    latest: dict[str, date | None],
    today: date,
    lookback: int,
) -> dict[str, tuple[date, date]]:
    """
    For each symbol, return (from_date, to_date) to fetch.
    - Symbol with no data → fetch full lookback window
    - Symbol with data older than yesterday → fetch from day after latest to today
    - Symbol with data from today or yesterday → skip
    """
    cutoff = today - timedelta(days=lookback)
    gaps: dict[str, tuple[date, date]] = {}
    yesterday = today - timedelta(days=1)

    for sym, latest_dt in latest.items():
        if latest_dt is None:
            # No data at all — fetch full lookback
            gaps[sym] = (cutoff, today)
        elif latest_dt < yesterday:
            # Data exists but stale — fill from day after latest
            from_dt = latest_dt + timedelta(days=1)
            if from_dt < cutoff:
                from_dt = cutoff
            gaps[sym] = (from_dt, today)
        # else: data is current (today or yesterday) — no gap

    return gaps


# ─────────────────────────────────────────────────────────────────────────────
# ILP writer
# ─────────────────────────────────────────────────────────────────────────────

def dt_to_ns(dt: datetime) -> int:
    """Convert datetime (may be tz-aware IST or naive IST) → UTC nanoseconds."""
    if dt.tzinfo is not None:
        utc_dt = dt.astimezone(timezone.utc)
    else:
        # Naive → assume IST → convert to UTC
        utc_dt = (dt - IST_OFFSET).replace(tzinfo=timezone.utc)
    return int(utc_dt.timestamp() * 1_000_000_000)


def ilp_send(sock: socket.socket, lines: list[str]) -> None:
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    view = memoryview(payload)
    sent = 0
    retries = 10
    while sent < len(payload):
        try:
            n = sock.send(view[sent:])
            if n == 0:
                raise RuntimeError("socket closed")
            sent += n
        except OSError as exc:
            if exc.errno in (errno.ENOBUFS, errno.EAGAIN, errno.EWOULDBLOCK) and retries > 0:
                retries -= 1
                time.sleep(1.0)
                continue
            raise


def candles_to_ilp(symbol: str, candles: list) -> list[str]:
    lines = []
    for c in candles:
        try:
            ts_dt = c.get("date") or c.get("timestamp")
            if ts_dt is None:
                continue
            ts_ns = dt_to_ns(ts_dt) if isinstance(ts_dt, datetime) else dt_to_ns(
                datetime.fromisoformat(str(ts_dt))
            )
            o = float(c["open"])
            h = float(c["high"])
            l = float(c["low"])
            cl = float(c["close"])
            v = int(c.get("volume", 0))
            lines.append(
                f"{TABLE},symbol={symbol} open={o},high={h},low={l},close={cl},volume={v}i {ts_ns}"
            )
        except (KeyError, ValueError, TypeError):
            pass
    return lines


def write_to_questdb(symbol: str, candles: list) -> int:
    if not candles:
        return 0
    ilp_lines = candles_to_ilp(symbol, candles)
    if not ilp_lines:
        return 0

    sock = socket.create_connection((QDB_HOST, QDB_ILP_PORT), timeout=30)
    sock.settimeout(120)
    try:
        batch: list[str] = []
        for line in ilp_lines:
            batch.append(line)
            if len(batch) >= BATCH_LINES:
                ilp_send(sock, batch)
                batch = []
        if batch:
            ilp_send(sock, batch)
    finally:
        sock.close()
    return len(ilp_lines)


# ─────────────────────────────────────────────────────────────────────────────
# Fetch one chunk from Kite
# ─────────────────────────────────────────────────────────────────────────────

def fetch_candles(kite, token: int, from_dt: date, to_dt: date) -> list:
    try:
        return kite.historical_data(
            instrument_token=token,
            from_date=from_dt,
            to_date=to_dt,
            interval="minute",
            continuous=False,
            oi=False,
        )
    except Exception as exc:
        msg = str(exc)
        if "Invalid" in msg and ("token" in msg.lower() or "access" in msg.lower()):
            raise RuntimeError("ACCESS_TOKEN_EXPIRED") from exc
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def run(gap_days: int, dry_run: bool) -> None:
    import asyncio
    import random
    import structlog
    from core.logging import setup_logging
    from core.db import AsyncSessionLocal
    from sqlalchemy import text

    setup_logging()
    log = structlog.get_logger(__name__)

    access_token = check_token_fresh()
    kite = get_kite(access_token)
    token_map = build_token_map(kite)
    log.info("kite_connected", tokens=len(token_map))

    # Load all symbols from postgres
    import asyncio as _asyncio

    async def load_symbols() -> list[str]:
        async with AsyncSessionLocal() as s:
            r = await s.execute(text("SELECT symbol FROM stocks ORDER BY symbol"))
            return [row[0] for row in r.fetchall()]

    all_symbols = _asyncio.run(load_symbols())
    # Only symbols that exist in Kite token map (excludes index symbols NSE_/BSE_)
    symbols = [s for s in all_symbols if s in token_map]
    log.info("symbols_loaded", total=len(all_symbols), kite_mapped=len(symbols))

    today = date.today()

    # Detect gaps
    log.info("detecting_gaps", lookback_days=gap_days)
    latest = get_latest_dates(symbols)
    gaps = compute_gaps(latest, today, gap_days)

    # Separate today's refresh from historical gaps
    todays = {s: (f, t) for s, (f, t) in gaps.items() if t == today and f == today}
    historical = {s: (f, t) for s, (f, t) in gaps.items() if not (f == today and t == today)}
    gap_only = {s: (f, t) for s, (f, t) in gaps.items() if f != today}

    log.info(
        "gap_summary",
        symbols_needing_today=len(gaps),
        symbols_with_history_gap=len([s for s, (f, t) in gaps.items() if f < today]),
        total_symbols=len(symbols),
    )

    if dry_run:
        print(f"\n{'─'*60}")
        print(f"DRY RUN — no data fetched")
        print(f"{'─'*60}")
        print(f"Symbols with gaps: {len(gaps)}")
        for sym, (f, t) in list(gaps.items())[:20]:
            latest_str = str(latest[sym]) if latest[sym] else "no data"
            print(f"  {sym}: {latest_str} → fetch {f} to {t}")
        if len(gaps) > 20:
            print(f"  ... and {len(gaps) - 20} more")
        return

    if not gaps:
        log.info("all_data_current", message="No gaps detected — all symbols up to date")
        return

    # Process each symbol with gaps
    total_rows = 0
    done = 0
    errors: list[str] = []
    start = time.time()
    last_call = 0.0

    for sym, (from_dt, to_dt) in gaps.items():
        # Rate limiting — 3 req/s max (Kite limit), add jitter
        now = time.monotonic()
        wait = random.uniform(0.35, 0.50) - (now - last_call)
        if wait > 0:
            time.sleep(wait)
        last_call = time.monotonic()

        inst_token = token_map[sym]
        sym_rows = 0

        # Split into 59-day chunks if range > CHUNK_DAYS
        d = from_dt
        while d <= to_dt:
            chunk_end = min(d + timedelta(days=CHUNK_DAYS - 1), to_dt)
            try:
                candles = fetch_candles(kite, inst_token, d, chunk_end)
                rows = write_to_questdb(sym, candles)
                sym_rows += rows
            except RuntimeError as exc:
                if "ACCESS_TOKEN_EXPIRED" in str(exc):
                    log.error(
                        "access_token_expired",
                        done=done,
                        remaining=len(gaps) - done,
                        hint="Run: python scripts/backfill_1min_kite.py --auth",
                    )
                    sys.exit(2)
                log.warning("fetch_failed", symbol=sym, from_dt=d, error=str(exc))
                errors.append(sym)
                break
            except Exception as exc:
                log.warning("fetch_failed", symbol=sym, from_dt=d, error=str(exc))
                errors.append(sym)
                break
            d = chunk_end + timedelta(days=1)

        total_rows += sym_rows
        done += 1
        elapsed = time.time() - start
        rate = done / elapsed
        eta = (len(gaps) - done) / rate if rate > 0 else 0

        if done % 50 == 0 or done == len(gaps):
            log.info(
                "refresh_progress",
                done=done,
                total=len(gaps),
                pct=f"{done/len(gaps)*100:.1f}%",
                rows=total_rows,
                errors=len(errors),
                eta_s=int(eta),
            )

    elapsed = time.time() - start
    log.info(
        "refresh_complete",
        symbols_processed=done,
        total_rows=total_rows,
        errors=len(errors),
        elapsed_s=int(elapsed),
    )
    if errors:
        log.warning("refresh_errors", symbols=errors[:20])
    sys.exit(1 if errors else 0)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Daily 1-min OHLCV refresh + gap backfill",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--gap-days",
        type=int,
        default=GAP_LOOKBACK_DAYS,
        help=f"Days to scan for gaps (default: {GAP_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show detected gaps without fetching any data",
    )
    args = parser.parse_args()
    run(gap_days=args.gap_days, dry_run=args.dry_run)
