"""1-minute OHLCV backfill via ICICI Direct Breeze API.

Breeze gives ~3 years of 1-minute historical data for all NSE stocks.
Free with ICICI Direct account.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ONE-TIME SETUP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Login to https://api.icicidirect.com/
2. Go to "Apps" → "Create App" → note API Key + API Secret
3. Add to .env:
       BREEZE_API_KEY=your_api_key
       BREEZE_API_SECRET=your_api_secret

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DAILY SESSION TOKEN (required each day)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Breeze session tokens expire daily. Before running this script each day:

  1. Open in browser:
     https://api.icicidirect.com/apiuser/login?AppKey=YOUR_API_KEY
  2. Login with ICICI Direct credentials + OTP
  3. You'll be redirected to a URL like:
     https://yourapp.com/?apisession=SESSION_TOKEN_HERE
  4. Copy the session token from the URL

  Then either:
    a) Set env var:   export BREEZE_SESSION_TOKEN=abc123xyz
    b) Pass directly: python backfill_1min_breeze.py --session abc123xyz

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    cd backend
    PYTHONPATH=. python scripts/backfill_1min_breeze.py --session SESSION_TOKEN
    # or for specific date range:
    PYTHONPATH=. python scripts/backfill_1min_breeze.py --session TOKEN --days 1095
    # resume after interruption (reads checkpoint file):
    PYTHONPATH=. python scripts/backfill_1min_breeze.py --session TOKEN

Rate limits: ~1000 req/hour. 2387 symbols × ~37 chunks (3yr) = ~88k calls total.
At 1000/hr = ~88 hours. Run over multiple days; script checkpoints progress.
"""
import asyncio
import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

CHECKPOINT_FILE = Path(__file__).parent / ".breeze_1min_checkpoint.json"
CHUNK_DAYS = 29          # Breeze allows ~30-day windows per call
RATE_LIMIT_PER_HR = 900
DELAY = 3600 / RATE_LIMIT_PER_HR   # ~4s between calls


def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {"completed": [], "failed": []}


def save_checkpoint(cp: dict) -> None:
    CHECKPOINT_FILE.write_text(json.dumps(cp, indent=2))


def get_breeze_session(session_token: str):
    from breeze_connect import BreezeConnect

    api_key = os.environ.get("BREEZE_API_KEY", "")
    api_secret = os.environ.get("BREEZE_API_SECRET", "")

    if not api_key or not api_secret:
        print(
            "\nBREEZE credentials not configured. Add to .env:\n"
            "  BREEZE_API_KEY=your_api_key\n"
            "  BREEZE_API_SECRET=your_api_secret\n\n"
            "Get from: https://api.icicidirect.com/\n"
        )
        sys.exit(1)

    if not session_token:
        print(
            "\nSession token required. Get it by:\n"
            f"  1. Open: https://api.icicidirect.com/apiuser/login?AppKey={api_key}\n"
            "  2. Login with ICICI Direct credentials + OTP\n"
            "  3. Copy SESSION_TOKEN from redirected URL\n"
            "  4. Pass as: --session SESSION_TOKEN\n"
        )
        sys.exit(1)

    breeze = BreezeConnect(api_key=api_key)
    breeze.generate_session(api_secret=api_secret, session_token=session_token)
    print("Breeze session active")
    return breeze


def fetch_chunk(breeze, symbol: str, from_dt: str, to_dt: str) -> list:
    """Fetch one 29-day chunk of 1-min OHLCV. Returns list of dicts."""
    try:
        resp = breeze.get_historical_data_v2(
            interval="1minute",
            from_date=f"{from_dt}T09:15:00.000Z",
            to_date=f"{to_dt}T15:30:00.000Z",
            stock_code=symbol,
            exchange_code="NSE",
            product_type="cash",
        )
        if resp and resp.get("Status") == 200:
            return resp.get("Success") or []
    except Exception as exc:
        # Suppress per-chunk noise; caller logs failures
        _ = exc
    return []


async def backfill_1min(session_token: str, days_back: int = 1095,
                        max_workers: int = 3) -> None:
    import structlog
    import pandas as pd
    from core.logging import setup_logging
    from core.sdk import MarketData
    from core.storage import get_storage

    setup_logging()
    log = structlog.get_logger(__name__)

    breeze = get_breeze_session(session_token)

    md = MarketData()
    symbols = await md.universe()
    if not symbols:
        log.error("no_symbols", hint="Run 'make seed' first")
        sys.exit(1)

    storage = get_storage()
    cp = load_checkpoint()
    completed_set = set(cp["completed"])

    today = date.today()
    start_date = today - timedelta(days=days_back)
    chunks: list[tuple[str, str]] = []
    d = start_date
    while d < today:
        chunk_end = min(d + timedelta(days=CHUNK_DAYS - 1), today)
        chunks.append((d.isoformat(), chunk_end.isoformat()))
        d = chunk_end + timedelta(days=1)

    work = [
        (sym, fd, td)
        for sym in symbols
        for fd, td in chunks
        if f"{sym}:{fd}" not in completed_set
    ]

    log.info("backfill_1min_breeze_start",
             symbols=len(symbols),
             chunks_per_sym=len(chunks),
             total_calls=len(work),
             eta_hours=round(len(work) / RATE_LIMIT_PER_HR, 1),
             from_date=start_date.isoformat())

    total_rows = 0
    done = 0
    failed: list[str] = []
    last_call_ts = 0.0
    sem = asyncio.Semaphore(max_workers)

    async def process(sym: str, from_dt: str, to_dt: str) -> None:
        nonlocal total_rows, done, last_call_ts

        async with sem:
            now = time.monotonic()
            wait = DELAY - (now - last_call_ts)
            if wait > 0:
                await asyncio.sleep(wait)
            last_call_ts = time.monotonic()

            try:
                loop = asyncio.get_event_loop()
                candles = await loop.run_in_executor(
                    None, fetch_chunk, breeze, sym, from_dt, to_dt
                )

                if candles:
                    df = pd.DataFrame(candles)
                    # Breeze returns: datetime, open, high, low, close, volume, open_interest
                    rename = {
                        "datetime": "ts",
                        "open": "open", "high": "high",
                        "low": "low", "close": "close",
                        "volume": "volume",
                    }
                    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
                    if "ts" not in df.columns:
                        raise ValueError(f"no ts col, got: {df.columns.tolist()}")
                    df["symbol"] = sym
                    df["ts"] = pd.to_datetime(df["ts"])
                    for col in ["open", "high", "low", "close", "volume"]:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors="coerce")
                    df = df[["ts", "symbol", "open", "high", "low", "close", "volume"]].dropna(
                        subset=["open", "close"]
                    )
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
            if done % 500 == 0 or done == len(work):
                save_checkpoint({"completed": cp["completed"], "failed": failed})
                log.info("backfill_1min_progress",
                         done=done, total=len(work),
                         pct=f"{done / len(work) * 100:.1f}%",
                         rows=total_rows, failed=len(failed))

    await asyncio.gather(*[process(s, f, t) for s, f, t in work])
    save_checkpoint({"completed": cp["completed"], "failed": failed})
    log.info("backfill_1min_complete",
             rows=total_rows, failed=len(failed),
             checkpoint=str(CHECKPOINT_FILE))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="1-min NSE backfill via ICICI Direct Breeze API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--session", default=os.environ.get("BREEZE_SESSION_TOKEN", ""),
                        help="Breeze session token (get daily from browser login)")
    parser.add_argument("--days", type=int, default=1095,
                        help="Days of history (default: 1095 = 3yr, max ~1095 for 1-min)")
    parser.add_argument("--workers", type=int, default=3,
                        help="Parallel workers (default: 3, keep low for rate limits)")
    args = parser.parse_args()
    asyncio.run(backfill_1min(
        session_token=args.session,
        days_back=args.days,
        max_workers=args.workers,
    ))
