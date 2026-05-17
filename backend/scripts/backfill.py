"""Historical data backfill — fetches N years of daily OHLCV from yfinance for all NSE stocks.

Usage:
    cd backend && PYTHONPATH=. python scripts/backfill.py [--years 2] [--workers 10]

This script:
1. Reads NSE stock universe from DB (run `make seed` first)
2. Fetches daily OHLCV for each symbol via yfinance
3. Writes to Parquet storage
4. Shows progress bar

Takes ~30-60 minutes for full NSE (~1800 EQ symbols, 2 years).
"""
import asyncio
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

# Load .env
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)


async def backfill(years: int = 2, max_workers: int = 10) -> None:
    import structlog
    from core.logging import setup_logging
    setup_logging()
    log = structlog.get_logger(__name__)

    from core.sdk import MarketData
    from core.storage import get_storage
    from data.sources.yfinance_source import fetch_daily_ohlcv

    md = MarketData()
    symbols = await md.universe()
    if not symbols:
        log.error("backfill_no_symbols", hint="Run 'make seed' first to populate stocks table")
        sys.exit(1)

    storage = get_storage()
    to_dt = date.today().isoformat()
    from_dt = (date.today() - timedelta(days=365 * years)).isoformat()

    log.info("backfill_start",
             symbols=len(symbols), from_dt=from_dt, to_dt=to_dt, workers=max_workers)

    sem = asyncio.Semaphore(max_workers)
    total_rows = 0
    done = 0
    failed_symbols = []

    async def fetch_one(sym: str) -> None:
        nonlocal total_rows, done
        async with sem:
            try:
                loop = asyncio.get_event_loop()
                df = await loop.run_in_executor(
                    None, fetch_daily_ohlcv, f"{sym}.NS", from_dt, to_dt
                )
                if not df.empty:
                    year = df["ts"].iloc[0].strftime("%Y")
                    month = df["ts"].iloc[0].strftime("%m")
                    path = f"timeframe=1d/year={year}/month={month}/bf_{sym}.parquet"
                    storage.write_parquet(df, path)
                    total_rows += len(df)
            except Exception as exc:
                log.warning("backfill_symbol_failed", symbol=sym, error=str(exc))
                failed_symbols.append(sym)
            finally:
                done += 1
                if done % 50 == 0 or done == len(symbols):
                    pct = done / len(symbols) * 100
                    log.info("backfill_progress",
                             done=done, total=len(symbols), pct=f"{pct:.1f}%",
                             rows=total_rows, failed=len(failed_symbols))

    await asyncio.gather(*[fetch_one(sym) for sym in symbols])

    log.info("backfill_complete",
             symbols=len(symbols), rows=total_rows,
             failed=len(failed_symbols), failed_list=failed_symbols[:10])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill NSE historical OHLCV data")
    parser.add_argument("--years", type=int, default=2, help="Years of history (default: 2)")
    parser.add_argument("--workers", type=int, default=10, help="Parallel workers (default: 10)")
    args = parser.parse_args()
    asyncio.run(backfill(years=args.years, max_workers=args.workers))
