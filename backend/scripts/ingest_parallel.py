"""Parallel CSV ingestion using ThreadPoolExecutor — no Temporal overhead.

Usage:
    PYTHONPATH=. python scripts/ingest_parallel.py
    PYTHONPATH=. python scripts/ingest_parallel.py --workers 3
    PYTHONPATH=. python scripts/ingest_parallel.py --symbol RELIANCE
"""
import argparse
import csv
import errno
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

_DEFAULT_RAWDATA_DIR = Path(__file__).parent.parent.parent / "rawdata" / "1min"
QDB_HOST     = "localhost"
QDB_ILP_PORT = 9009
TABLE        = "ohlcv_1min"
BATCH_LINES  = 1000
IST_OFFSET   = timedelta(hours=5, minutes=30)


def ts_to_ns(ts_str: str) -> int:
    s = ts_str.replace(" ", "T")
    if s.endswith("+05:30"):
        s = s[:-6]
        dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc) - IST_OFFSET
    elif s.endswith("Z") or s.endswith("+00:00"):
        dt = datetime.fromisoformat(s.rstrip("Z").rstrip("+00:00")).replace(tzinfo=timezone.utc)
    else:
        dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc) - IST_OFFSET
    return int(dt.timestamp() * 1_000_000_000)


def csv_to_ilp_lines(symbol: str, csv_path: Path) -> list[str]:
    lines = []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                ts_ns = ts_to_ns(row["ts"])
                o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
                v = int(float(row["volume"]))
                lines.append(f"{TABLE},symbol={symbol} open={o},high={h},low={l},close={c},volume={v}i {ts_ns}")
            except (ValueError, KeyError):
                pass
    return lines


def send_batch(sock: socket.socket, lines: list[str]):
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


def ingest_symbol(symbol: str, rawdata_dir: Path = None) -> tuple[str, int, int]:
    """Returns (symbol, files_done, rows_done)."""
    if rawdata_dir is None:
        rawdata_dir = _DEFAULT_RAWDATA_DIR
    sym_dir = rawdata_dir / symbol
    csv_files = sorted(sym_dir.glob(f"{symbol}_*.csv"))
    if not csv_files:
        return symbol, 0, 0

    sock = socket.create_connection((QDB_HOST, QDB_ILP_PORT), timeout=30)
    sock.settimeout(300)
    total_rows = 0
    try:
        batch: list[str] = []
        for csv_path in csv_files:
            lines = csv_to_ilp_lines(symbol, csv_path)
            total_rows += len(lines)
            batch.extend(lines)
            while len(batch) >= BATCH_LINES:
                send_batch(sock, batch[:BATCH_LINES])
                batch = batch[BATCH_LINES:]
        while batch:
            send_batch(sock, batch[:BATCH_LINES])
            batch = batch[BATCH_LINES:]
    finally:
        sock.close()

    return symbol, len(csv_files), total_rows


def main():
    global BATCH_LINES
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--symbol", nargs="+", help="One or more symbols")
    parser.add_argument("--dir", default=None, help="Raw data directory (default: rawdata/1min)")
    parser.add_argument("--batch", type=int, default=BATCH_LINES, help="ILP batch size (default: 1000)")
    args = parser.parse_args()

    BATCH_LINES = args.batch
    rawdata_dir = Path(args.dir) if args.dir else _DEFAULT_RAWDATA_DIR

    if args.symbol:
        symbols = args.symbol
    else:
        symbols = sorted(p.name for p in rawdata_dir.iterdir() if p.is_dir())

    print(f"Ingesting {len(symbols)} symbols  workers={args.workers}  batch={BATCH_LINES}")

    done = 0
    total_rows = 0
    errors = []
    start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(ingest_symbol, sym, rawdata_dir): sym for sym in symbols}
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                _, files, rows = fut.result()
                done += 1
                total_rows += rows
                elapsed = time.time() - start
                rate = done / elapsed
                eta = (len(symbols) - done) / rate if rate > 0 else 0
                print(f"[{done}/{len(symbols)}] {sym}: {files}f {rows:,}r | "
                      f"total={total_rows:,} eta={eta:.0f}s", flush=True)
            except Exception as exc:
                errors.append((sym, str(exc)))
                print(f"  ERROR {sym}: {exc}", flush=True)

    elapsed = time.time() - start
    print(f"\nDone: {done}/{len(symbols)} symbols  {total_rows:,} rows  {elapsed:.0f}s")
    if errors:
        print(f"Errors ({len(errors)}):")
        for sym, err in errors:
            print(f"  {sym}: {err}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
