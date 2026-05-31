"""Ingest rawdata/1min CSV files into QuestDB via ILP (InfluxDB Line Protocol).

Reads {symbol}/{symbol}_{date}.csv files, sends to QuestDB port 9009.
Tracks progress per-symbol so it can be resumed.

Usage:
    cd backend
    PYTHONPATH=. python scripts/ingest_csvs_to_questdb.py
    PYTHONPATH=. python scripts/ingest_csvs_to_questdb.py --resume
    PYTHONPATH=. python scripts/ingest_csvs_to_questdb.py --symbol CDSL   # single symbol

ILP doc: QuestDB receives line protocol on TCP port 9009.
Format:  table,tag=val field1=v1,field2=v2 ts_nanoseconds

Logs to: logs/ingest_questdb.log  (+ stdout)
"""
import argparse
import csv
import logging
import socket
import sys
import time
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

RAWDATA_DIR        = Path(__file__).parent.parent.parent / "rawdata" / "1min"
PROGRESS_FILE      = Path(__file__).parent / ".ingest_file_progress.json"   # file-level keys
LEGACY_PROGRESS    = Path(__file__).parent / ".ingest_progress.json"        # old symbol-level
LOG_DIR            = Path(__file__).parent.parent.parent / "logs"
QDB_HOST      = "localhost"
QDB_ILP_PORT  = 9009
TABLE         = "ohlcv_1min"
BATCH_LINES   = 5000          # lines per TCP send
IST_OFFSET    = timedelta(hours=5, minutes=30)


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / "ingest_questdb.log"

    fmt = "%(asctime)s %(levelname)-5s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logger = logging.getLogger("ingest")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # File handler — full DEBUG, append so reruns accumulate
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(fmt, datefmt))

    # Stream handler — INFO+ to stdout, unbuffered via flush
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter(fmt, datefmt))
    sh.stream = open(sys.stdout.fileno(), mode="w", buffering=1, closefd=False)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def ts_to_ns(ts_str: str) -> int:
    """Parse ISO8601 timestamp (possibly with +05:30) → nanoseconds since epoch (UTC)."""
    # Handle both formats: '2024-01-01T09:15:00+05:30' and '2024-01-01 09:15:00+05:30'
    s = ts_str.replace(" ", "T")
    # Python 3.9 fromisoformat doesn't support +05:30 offset on all platforms
    # Parse manually
    if s.endswith("+05:30"):
        s = s[:-6]
        dt = datetime.fromisoformat(s)
        dt = dt.replace(tzinfo=timezone.utc) - IST_OFFSET
    elif s.endswith("Z") or s.endswith("+00:00"):
        dt = datetime.fromisoformat(s.rstrip("Z").rstrip("+00:00"))
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        # Assume IST if no offset
        dt = datetime.fromisoformat(s)
        dt = dt.replace(tzinfo=timezone.utc) - IST_OFFSET
    return int(dt.timestamp() * 1_000_000_000)


def csv_to_ilp_lines(symbol: str, csv_path: Path,
                     logger: logging.Logger) -> list[str]:
    """Convert a CSV file to ILP line-protocol strings."""
    lines = []
    bad_rows = 0
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts_ns = ts_to_ns(row["ts"])
                o = float(row["open"])
                h = float(row["high"])
                l = float(row["low"])
                c = float(row["close"])
                v = int(float(row["volume"]))
                line = (
                    f"{TABLE},symbol={symbol} "
                    f"open={o},high={h},low={l},close={c},volume={v}i "
                    f"{ts_ns}"
                )
                lines.append(line)
            except (ValueError, KeyError) as e:
                bad_rows += 1
                logger.debug("bad row in %s: %s — %s", csv_path.name, row, e)
    if bad_rows:
        logger.warning("%s: skipped %d malformed rows", csv_path.name, bad_rows)
    return lines


def send_ilp_batch(sock: socket.socket, lines: list[str]):
    """Send a batch of ILP lines over TCP."""
    payload = "\n".join(lines) + "\n"
    total = payload.encode("utf-8")
    view = memoryview(total)
    sent = 0
    while sent < len(total):
        n = sock.send(view[sent:])
        if n == 0:
            raise RuntimeError("Socket closed")
        sent += n


def file_key(symbol: str, csv_path: Path) -> str:
    """'RELIANCE_2024-01-01.csv' → 'RELIANCE:2024-01-01'"""
    date_part = csv_path.stem[len(symbol) + 1:]   # strip 'SYMBOL_' prefix
    return f"{symbol}:{date_part}"


def load_progress() -> set[str]:
    """Load file-level done set. Migrates from legacy symbol-level file on first run."""
    if PROGRESS_FILE.exists():
        return set(json.loads(PROGRESS_FILE.read_text()))

    # ── Migrate from old symbol-level progress ──────────────────────────────
    if LEGACY_PROGRESS.exists():
        done_symbols: list[str] = json.loads(LEGACY_PROGRESS.read_text())
        keys: set[str] = set()
        for sym in done_symbols:
            sym_dir = RAWDATA_DIR / sym
            if sym_dir.exists():
                for csv_path in sym_dir.glob(f"{sym}_*.csv"):
                    keys.add(file_key(sym, csv_path))
        save_progress(keys)
        return keys

    return set()


def save_progress(done: set[str]):
    PROGRESS_FILE.write_text(json.dumps(sorted(done)))


def ingest_symbol(
    symbol: str,
    sock: socket.socket,
    logger: logging.Logger,
    done: set[str],
) -> tuple[int, int, int]:
    """Ingest CSV files for a symbol, skipping already-done files.

    Returns (files_ingested, files_skipped, rows_ingested).
    Updates `done` in-place as each file completes.
    """
    sym_dir = RAWDATA_DIR / symbol
    if not sym_dir.exists():
        logger.debug("%s: directory not found, skipping", symbol)
        return 0, 0, 0

    csv_files = sorted(sym_dir.glob(f"{symbol}_*.csv"))
    if not csv_files:
        logger.debug("%s: no CSV files found", symbol)
        return 0, 0, 0

    total_rows = 0
    files_done = 0
    files_skipped = 0
    batch: list[str] = []

    for csv_path in csv_files:
        key = file_key(symbol, csv_path)
        if key in done:
            files_skipped += 1
            logger.debug("%s: skipping %s (already ingested)", symbol, csv_path.name)
            continue

        lines = csv_to_ilp_lines(symbol, csv_path, logger)
        total_rows += len(lines)
        batch.extend(lines)
        logger.debug("%s: parsed %s — %d rows", symbol, csv_path.name, len(lines))

        while len(batch) >= BATCH_LINES:
            send_ilp_batch(sock, batch[:BATCH_LINES])
            batch = batch[BATCH_LINES:]

        done.add(key)      # mark file done immediately after send
        files_done += 1

    # Flush remaining
    while batch:
        send_ilp_batch(sock, batch[:BATCH_LINES])
        batch = batch[BATCH_LINES:]

    return files_done, files_skipped, total_rows


def get_all_symbols() -> list[str]:
    return sorted(p.name for p in RAWDATA_DIR.iterdir() if p.is_dir())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume",  action="store_true", help="Skip already-ingested symbols")
    parser.add_argument("--symbol",  help="Ingest only this symbol")
    parser.add_argument("--workers", type=int, default=1, help="(future) parallel workers")
    args = parser.parse_args()

    log = setup_logging()
    log.info("=" * 60)
    log.info("ingest_csvs_to_questdb starting  resume=%s  symbol=%s",
             args.resume, args.symbol or "ALL")

    symbols = [args.symbol] if args.symbol else get_all_symbols()
    # File-level done set — always loaded (skip at file granularity, not symbol)
    done: set[str] = load_progress() if args.resume else set()

    log.info("symbols=%d  done_files=%d  resume=%s",
             len(symbols), len(done), args.resume)

    if not symbols:
        log.info("No symbols found in %s", RAWDATA_DIR)
        return

    log.info("Connecting to QuestDB ILP  host=%s  port=%d", QDB_HOST, QDB_ILP_PORT)
    try:
        sock = socket.create_connection((QDB_HOST, QDB_ILP_PORT), timeout=60)
        sock.settimeout(60)
    except OSError as e:
        log.error("Cannot connect to QuestDB ILP: %s", e)
        sys.exit(1)
    log.info("Connected to QuestDB ILP")

    start_time    = time.time()
    grand_rows    = 0
    grand_files   = 0
    checkpoint_at = 50    # save progress + log summary every N symbols
    errors        = 0

    try:
        for i, sym in enumerate(symbols, 1):
            t0 = time.time()
            try:
                files_ok, files_skipped, rows = ingest_symbol(sym, sock, log, done)
            except Exception as e:
                log.error("[%d/%d] %s FAILED: %s", i, len(symbols), sym, e)
                errors += 1
                continue

            elapsed = time.time() - t0
            grand_rows  += rows
            grand_files += files_ok

            if rows > 0:
                rps = rows / elapsed if elapsed > 0 else 0
                log.info("[%4d/%d] %-20s  new=%3d  skipped=%3d  rows=%7s  "
                         "time=%.1fs  rows/s=%s",
                         i, len(symbols), sym, files_ok, files_skipped,
                         f"{rows:,}", elapsed, f"{rps:,.0f}")
            elif files_ok == 0 and files_skipped == 0:
                log.info("[%4d/%d] %-20s  (no data)", i, len(symbols), sym)
            else:
                log.info("[%4d/%d] %-20s  all %d files already ingested",
                         i, len(symbols), sym, files_skipped)

            if i % checkpoint_at == 0:
                save_progress(done)
                total_elapsed = time.time() - start_time
                cumulative_rps = grand_rows / total_elapsed if total_elapsed > 0 else 0
                log.info("── checkpoint  rows=%s  done_files=%d  errors=%d  "
                         "elapsed=%.0fs  avg_rows/s=%s",
                         f"{grand_rows:,}", len(done), errors,
                         total_elapsed, f"{cumulative_rps:,.0f}")

    except KeyboardInterrupt:
        log.warning("Interrupted by user — saving progress")
    except Exception as e:
        log.error("Unexpected error: %s", e, exc_info=True)
    finally:
        save_progress(done)
        sock.close()

    total_elapsed = time.time() - start_time
    rps = grand_rows / total_elapsed if total_elapsed > 0 else 0
    log.info("=" * 60)
    log.info("COMPLETE  rows=%s  new_files=%s  done_files=%d  "
             "symbols=%d  errors=%d  elapsed=%.1fs  avg_rows/s=%s",
             f"{grand_rows:,}", f"{grand_files:,}", len(done),
             len(symbols), errors,
             total_elapsed, f"{rps:,.0f}")


if __name__ == "__main__":
    main()
