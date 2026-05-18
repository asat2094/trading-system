"""1-minute OHLCV backfill via Angel One SmartAPI (free account, ~5yr depth).

Setup (one-time):
    1. Create free Angel One demat account: https://www.angelone.in/open-demat-account
    2. Create API key: https://smartapi.angelbroking.com/
    3. Enable TOTP in Angel One app (Settings → Security → Enable TOTP)
    4. Add to .env:
         ANGELONE_API_KEY=your_api_key
         ANGELONE_CLIENT_ID=your_client_id
         ANGELONE_PASSWORD=your_password
         ANGELONE_TOTP_SECRET=your_totp_secret   # from QR code during TOTP setup

Usage:
    cd backend && PYTHONPATH=. python scripts/backfill_1min_angelone.py [--workers 5] [--days 365]

Rate limits:
    - 1000 requests/hour (free tier)
    - Each request: 30-day window max for 1-min
    - 5-year depth: ~60 chunks per symbol → 2387 symbols × 60 = ~143k calls total
    - At 1000/hr: ~143 hours → run over multiple days with checkpointing

The script checkpoints progress to a JSON file so it can be resumed.
"""
import asyncio
import argparse
import json
import os
import sys
import time
from datetime import date, timedelta, datetime
from pathlib import Path

env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

CHECKPOINT_FILE = Path(__file__).parent / ".angelone_1min_checkpoint.json"
CHUNK_DAYS = 28          # 28-day chunks (stay under 30-day limit)
RATE_LIMIT_PER_HR = 900  # conservative (limit is 1000)
MIN_DELAY = 3600 / RATE_LIMIT_PER_HR  # seconds between calls


def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {"completed": [], "failed": []}


def save_checkpoint(cp: dict) -> None:
    CHECKPOINT_FILE.write_text(json.dumps(cp, indent=2))


def get_angelone_session():
    """Create authenticated Angel One session."""
    import pyotp
    from SmartApi import SmartConnect

    api_key = os.environ.get("ANGELONE_API_KEY", "")
    client_id = os.environ.get("ANGELONE_CLIENT_ID", "")
    password = os.environ.get("ANGELONE_PASSWORD", "")
    totp_secret = os.environ.get("ANGELONE_TOTP_SECRET", "")

    if not all([api_key, client_id, password, totp_secret]):
        print(
            "\nAngel One credentials not configured. Add to .env:\n"
            "  ANGELONE_API_KEY=<from smartapi.angelbroking.com>\n"
            "  ANGELONE_CLIENT_ID=<your Angel One client ID>\n"
            "  ANGELONE_PASSWORD=<your Angel One password>\n"
            "  ANGELONE_TOTP_SECRET=<TOTP secret from QR code>\n\n"
            "Create free account: https://www.angelone.in/open-demat-account\n"
            "Create API key: https://smartapi.angelbroking.com/\n"
        )
        sys.exit(1)

    obj = SmartConnect(api_key=api_key)
    totp = pyotp.TOTP(totp_secret).now()
    data = obj.generateSession(client_id, password, totp)
    if data["status"] is False:
        print(f"Login failed: {data}")
        sys.exit(1)
    print(f"Logged in as {client_id}")
    return obj


def get_token_map(obj) -> dict[str, str]:
    """Build symbol → token map from Angel One instrument list."""
    import requests
    r = requests.get(
        "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json",
        timeout=30
    )
    instruments = r.json()
    token_map = {}
    for inst in instruments:
        if inst.get("exch_seg") == "NSE" and inst.get("instrumenttype") == "":
            sym = inst["symbol"].replace("-EQ", "").strip()
            token_map[sym] = inst["token"]
    print(f"Loaded {len(token_map)} NSE EQ tokens")
    return token_map


def fetch_1min_chunk(obj, token: str, from_dt: str, to_dt: str) -> list:
    """Fetch one 28-day chunk of 1-min data. Returns list of candles."""
    try:
        resp = obj.getCandleData({
            "exchange": "NSE",
            "symboltoken": token,
            "interval": "ONE_MINUTE",
            "fromdate": f"{from_dt} 09:15",
            "todate": f"{to_dt} 15:30",
        })
        if resp and resp.get("status") and resp.get("data"):
            return resp["data"]
    except Exception as exc:
        print(f"  fetch error: {exc}")
    return []


async def backfill_1min(days_back: int = 365, max_workers: int = 3) -> None:
    import structlog
    import pandas as pd
    from core.logging import setup_logging
    from core.sdk import MarketData
    from core.storage import get_storage

    setup_logging()
    log = structlog.get_logger(__name__)

    obj = get_angelone_session()
    token_map = get_token_map(obj)

    md = MarketData()
    symbols = await md.universe()
    if not symbols:
        log.error("no_symbols", hint="Run 'make seed' first")
        sys.exit(1)

    storage = get_storage()
    cp = load_checkpoint()
    completed_set = set(cp["completed"])

    # Build work queue: symbol × date-chunk pairs
    today = date.today()
    start_date = today - timedelta(days=days_back)
    chunks = []
    d = start_date
    while d < today:
        chunk_end = min(d + timedelta(days=CHUNK_DAYS), today)
        chunks.append((d.isoformat(), chunk_end.isoformat()))
        d = chunk_end + timedelta(days=1)

    work = [(sym, from_dt, to_dt) for sym in symbols
            for from_dt, to_dt in chunks
            if f"{sym}:{from_dt}" not in completed_set
            and sym in token_map]

    log.info("backfill_1min_start",
             symbols=len(symbols), chunks_per_sym=len(chunks),
             total_calls=len(work), days_back=days_back,
             eta_hours=round(len(work) / RATE_LIMIT_PER_HR, 1))

    total_rows = 0
    done = 0
    failed = []
    last_call = 0.0

    sem = asyncio.Semaphore(max_workers)

    async def process(sym: str, from_dt: str, to_dt: str) -> None:
        nonlocal total_rows, done, last_call

        async with sem:
            # Rate limit
            now = time.monotonic()
            wait = MIN_DELAY - (now - last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            last_call = time.monotonic()

            try:
                token = token_map[sym]
                loop = asyncio.get_event_loop()
                candles = await loop.run_in_executor(
                    None, fetch_1min_chunk, obj, token, from_dt, to_dt
                )

                if candles:
                    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])
                    df["ts"] = pd.to_datetime(df["ts"])
                    df["symbol"] = sym
                    for col in ["open", "high", "low", "close", "volume"]:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                    df = df.dropna(subset=["open", "close"])
                    if not df.empty:
                        month = df["ts"].iloc[0].strftime("%Y-%m")
                        path = f"timeframe=1min/symbol={sym}/month={month}/{sym}_{from_dt}.parquet"
                        storage.write_parquet(df, path)
                        total_rows += len(df)

                cp["completed"].append(f"{sym}:{from_dt}")
            except Exception as exc:
                log.warning("chunk_failed", symbol=sym, from_dt=from_dt, error=str(exc))
                failed.append(f"{sym}:{from_dt}")

            done += 1
            if done % 200 == 0 or done == len(work):
                save_checkpoint({"completed": cp["completed"], "failed": failed})
                log.info("backfill_1min_progress",
                         done=done, total=len(work),
                         pct=f"{done/len(work)*100:.1f}%",
                         rows=total_rows, failed=len(failed))

    await asyncio.gather(*[process(sym, fd, td) for sym, fd, td in work])

    save_checkpoint({"completed": cp["completed"], "failed": failed})
    log.info("backfill_1min_complete", rows=total_rows,
             failed=len(failed), checkpoint=str(CHECKPOINT_FILE))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="1-min backfill via Angel One SmartAPI")
    parser.add_argument("--days", type=int, default=365,
                        help="Days of history (default: 365, max ~1825 for 5yr)")
    parser.add_argument("--workers", type=int, default=3,
                        help="Parallel workers — keep low to respect rate limits (default: 3)")
    args = parser.parse_args()
    asyncio.run(backfill_1min(days_back=args.days, max_workers=args.workers))
