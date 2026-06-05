"""
Ingest icharts OptionsData CSVs into QuestDB ohlcv_1min table via ILP.

CSVs in data/raw/options/ have format: ts,open,high,low,close,volume
Symbol name = filename stem before '_R1'  (e.g. NIFTY26JUN0224000CE_R1.csv → NIFTY26JUN0224000CE)

Usage:
    cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
    python backend/scripts/icharts_ingest.py                    # ingest all pending CSVs
    python backend/scripts/icharts_ingest.py --symbol NIFTY26JUN0224000CE
    python backend/scripts/icharts_ingest.py --dry-run          # count rows without sending
"""

import argparse
import csv
import json
import logging
import socket
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT      = Path(__file__).parent.parent.parent
OPTIONS_DIR    = REPO_ROOT / "data" / "raw" / "options"
PROGRESS_FILE  = REPO_ROOT / "data" / ".ingest_progress.json"
LOG_DIR        = REPO_ROOT / "logs"
QDB_HOST       = "localhost"
QDB_ILP_PORT   = 9009
TABLE          = "ohlcv_1min"
BATCH_LINES    = 5000
IST            = timezone(timedelta(hours=5, minutes=30))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "icharts_ingest.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("icharts_ingest")


def load_progress() -> set[str]:
    if PROGRESS_FILE.exists():
        return set(json.loads(PROGRESS_FILE.read_text()))
    return set()


def save_progress(done: set[str]):
    PROGRESS_FILE.write_text(json.dumps(sorted(done)))


def ts_to_ns(ts_str: str) -> int:
    """ISO8601 +05:30 timestamp (space or T separator) → nanoseconds since Unix epoch (UTC)."""
    s = ts_str.strip().replace(" ", "T")
    if s.endswith("+05:30"):
        dt = datetime.fromisoformat(s[:-6]).replace(tzinfo=IST)
    else:
        dt = datetime.fromisoformat(s)
    return int(dt.timestamp() * 1_000_000_000)


def csv_to_ilp(csv_path: Path, symbol: str) -> list[str]:
    lines = []
    bad = 0
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                # Support both 'ts' (new format) and 'datetime' (legacy pandas output)
                ts_raw = row.get("ts") or row.get("datetime", "")
                ns  = ts_to_ns(ts_raw)
                o   = float(row["open"])
                h   = float(row["high"])
                l   = float(row["low"])
                c   = float(row["close"])
                v   = int(float(row["volume"]))
                lines.append(
                    f"{TABLE},symbol={symbol} "
                    f"open={o},high={h},low={l},close={c},volume={v}i "
                    f"{ns}"
                )
            except (ValueError, KeyError) as e:
                bad += 1
                log.debug("bad row %s: %s", csv_path.name, e)
    if bad:
        log.warning("%s: skipped %d bad rows", csv_path.name, bad)
    return lines


def send_batch(sock: socket.socket, lines: list[str]):
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    view = memoryview(payload)
    sent = 0
    while sent < len(payload):
        n = sock.send(view[sent:])
        if n == 0:
            raise RuntimeError("QuestDB socket closed")
        sent += n


def ingest_file(sock: socket.socket, csv_path: Path, symbol: str) -> int:
    lines = csv_to_ilp(csv_path, symbol)
    if not lines:
        return 0
    batch = []
    sent = 0
    for line in lines:
        batch.append(line)
        if len(batch) >= BATCH_LINES:
            send_batch(sock, batch)
            sent += len(batch)
            batch = []
    if batch:
        send_batch(sock, batch)
        sent += len(batch)
    return sent


def symbol_from_path(p: Path) -> str:
    """NIFTY26JUN0224000CE_R1.csv → NIFTY26JUN0224000CE"""
    stem = p.stem  # e.g. NIFTY26JUN0224000CE_R1
    return stem.rsplit("_R", 1)[0]


def run(filter_symbol: str | None = None, dry_run: bool = False):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    csvs = sorted(OPTIONS_DIR.glob("**/*_R1.csv"))
    if not csvs:
        log.error(f"No CSVs found in {OPTIONS_DIR}")
        return

    done = load_progress()
    pending = [p for p in csvs if p.name not in done]
    if filter_symbol:
        pending = [p for p in pending if symbol_from_path(p) == filter_symbol]

    log.info(f"Total CSVs: {len(csvs)}  Done: {len(done)}  Pending: {len(pending)}")

    if dry_run:
        total_rows = 0
        for p in pending[:5]:  # sample 5 files
            sym = symbol_from_path(p)
            lines = csv_to_ilp(p, sym)
            total_rows += len(lines)
        avg = total_rows / min(5, len(pending)) if pending else 0
        est = int(avg * len(pending))
        log.info(f"DRY RUN: ~{est:,} rows across {len(pending)} files (sample avg {avg:.0f} rows/file)")
        return

    log.info(f"Connecting to QuestDB {QDB_HOST}:{QDB_ILP_PORT}")
    try:
        sock = socket.create_connection((QDB_HOST, QDB_ILP_PORT), timeout=60)
    except ConnectionRefusedError:
        log.error("QuestDB not reachable. Is it running?")
        return

    total_rows = 0
    try:
        for i, csv_path in enumerate(pending):
            sym = symbol_from_path(csv_path)
            try:
                rows = ingest_file(sock, csv_path, sym)
                total_rows += rows
                done.add(csv_path.name)
                log.info(f"[{i+1}/{len(pending)}] {sym}: {rows} rows ingested")
            except Exception as e:
                log.error(f"FAILED {sym}: {e}")
                # reconnect on socket error
                try:
                    sock.close()
                except Exception:
                    pass
                time.sleep(2)
                sock = socket.create_connection((QDB_HOST, QDB_ILP_PORT), timeout=60)

            # Save progress every 100 files
            if (i + 1) % 100 == 0:
                save_progress(done)
                log.info(f"Progress saved ({len(done)} files done)")
    finally:
        sock.close()
        save_progress(done)

    log.info(f"Done. Total rows ingested: {total_rows:,} across {len(pending)} files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="Ingest single symbol only")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(filter_symbol=args.symbol, dry_run=args.dry_run)
