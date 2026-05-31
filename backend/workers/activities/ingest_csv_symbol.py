"""Activity: ingest all CSV files for one symbol into QuestDB via ILP."""
import csv
import errno
import socket
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from temporalio import activity
from core.logging import get_logger

log = get_logger(__name__)

RAWDATA_DIR   = Path(__file__).parent.parent.parent.parent / "rawdata" / "1min"
QDB_HOST      = "localhost"
QDB_ILP_PORT  = 9009
TABLE         = "ohlcv_1min"
BATCH_LINES   = 2000
IST_OFFSET    = timedelta(hours=5, minutes=30)


def _ts_to_ns(ts_str: str) -> int:
    s = ts_str.replace(" ", "T")
    if s.endswith("+05:30"):
        s = s[:-6]
        dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc) - IST_OFFSET
    elif s.endswith("Z") or s.endswith("+00:00"):
        dt = datetime.fromisoformat(s.rstrip("Z").rstrip("+00:00")).replace(tzinfo=timezone.utc)
    else:
        dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc) - IST_OFFSET
    return int(dt.timestamp() * 1_000_000_000)


def _csv_to_ilp_lines(symbol: str, csv_path: Path) -> list[str]:
    lines = []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                ts_ns = _ts_to_ns(row["ts"])
                o = float(row["open"])
                h = float(row["high"])
                l = float(row["low"])
                c = float(row["close"])
                v = int(float(row["volume"]))
                lines.append(
                    f"{TABLE},symbol={symbol} "
                    f"open={o},high={h},low={l},close={c},volume={v}i "
                    f"{ts_ns}"
                )
            except (ValueError, KeyError):
                pass
    return lines


def _send_ilp_batch(sock: socket.socket, lines: list[str], max_retries: int = 5):
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    view = memoryview(payload)
    sent = 0
    while sent < len(payload):
        try:
            n = sock.send(view[sent:])
            if n == 0:
                raise RuntimeError("QuestDB ILP socket closed")
            sent += n
        except OSError as exc:
            if exc.errno in (errno.ENOBUFS, errno.EAGAIN, errno.EWOULDBLOCK):
                # Send buffer full — back off and retry
                max_retries -= 1
                if max_retries <= 0:
                    raise
                time.sleep(0.5)
                continue
            raise


@activity.defn(name="ingest_csv_symbol")
def activity_fn(symbol: str) -> dict:
    """Ingest all CSV files for `symbol` from rawdata/1min into QuestDB.

    Returns {"files_ingested": int, "files_skipped": int, "rows_ingested": int}.
    All files are always ingested (no per-file skip logic here — QuestDB DEDUP handles
    idempotency via UPSERT KEYS(ts, symbol)).
    """
    sym_dir = RAWDATA_DIR / symbol
    if not sym_dir.exists():
        log.warning("ingest_csv_symbol_no_dir", symbol=symbol)
        return {"files_ingested": 0, "files_skipped": 0, "rows_ingested": 0}

    csv_files = sorted(sym_dir.glob(f"{symbol}_*.csv"))
    if not csv_files:
        return {"files_ingested": 0, "files_skipped": 0, "rows_ingested": 0}

    log.info("ingest_csv_symbol_start", symbol=symbol, files=len(csv_files))

    try:
        sock = socket.create_connection((QDB_HOST, QDB_ILP_PORT), timeout=60)
        sock.settimeout(120)
    except OSError as exc:
        raise RuntimeError(f"Cannot connect to QuestDB ILP {QDB_HOST}:{QDB_ILP_PORT}: {exc}") from exc

    try:
        total_rows = 0
        batch: list[str] = []

        for csv_path in csv_files:
            lines = _csv_to_ilp_lines(symbol, csv_path)
            total_rows += len(lines)
            batch.extend(lines)

            while len(batch) >= BATCH_LINES:
                _send_ilp_batch(sock, batch[:BATCH_LINES])
                batch = batch[BATCH_LINES:]

        # flush remainder
        while batch:
            _send_ilp_batch(sock, batch[:BATCH_LINES])
            batch = batch[BATCH_LINES:]

    finally:
        sock.close()

    log.info("ingest_csv_symbol_done", symbol=symbol,
             files=len(csv_files), rows=total_rows)
    return {"files_ingested": len(csv_files), "files_skipped": 0, "rows_ingested": total_rows}
