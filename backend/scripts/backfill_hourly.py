"""Hourly OHLCV backfill — 2 years for all NSE stocks via yfinance (free, no auth).

yfinance 60-min interval max lookback: 730 days.

Usage:
    cd backend && PYTHONPATH=. python scripts/backfill_hourly.py [--workers 15]
"""
import asyncio
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)


async def backfill_hourly(max_workers: int = 15) -> None:
    import structlog
    from core.logging import setup_logging
    setup_logging()
    log = structlog.get_logger(__name__)

    from core.sdk import MarketData
    from core.storage import get_storage
    import yfinance as yf
    import pandas as pd

    md = MarketData()
    symbols = await md.universe()
    if not symbols:
        log.error("backfill_no_symbols", hint="Run 'make seed' first")
        sys.exit(1)

    storage = get_storage()
    to_dt = date.today().isoformat()
    from_dt = (date.today() - timedelta(days=729)).isoformat()   # 730d max for 60m

    log.info("backfill_hourly_start",
             symbols=len(symbols), from_dt=from_dt, to_dt=to_dt, workers=max_workers)

    sem = asyncio.Semaphore(max_workers)
    total_rows = 0
    done = 0
    failed = []

    def fetch_one_sync(sym: str) -> pd.DataFrame:
        import time
        for attempt in range(3):
            try:
                ticker = f"{sym}.NS"
                raw = yf.download(ticker, start=from_dt, end=to_dt,
                                  interval="60m", progress=False, auto_adjust=True)
                if raw.empty:
                    return pd.DataFrame()
                # yfinance returns MultiIndex columns: (Price, Ticker)
                # Flatten: keep first level, lowercase
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = [c[0].lower() for c in raw.columns]
                else:
                    raw.columns = [c.lower() for c in raw.columns]
                raw = raw.reset_index()
                # Index column is 'Datetime' (tz-aware UTC)
                ts_col = next((c for c in raw.columns if "datetime" in c.lower() or "date" in c.lower()), None)
                if ts_col is None:
                    return pd.DataFrame()
                raw = raw.rename(columns={ts_col: "ts"})
                raw["symbol"] = sym
                raw["ts"] = pd.to_datetime(raw["ts"]).dt.tz_localize(None)
                return raw[["ts", "symbol", "open", "high", "low", "close", "volume"]].dropna(subset=["open", "close"])
            except Exception:
                if attempt < 2:
                    time.sleep(1)
        return pd.DataFrame()

    async def process(sym: str) -> None:
        nonlocal total_rows, done
        async with sem:
            try:
                loop = asyncio.get_event_loop()
                df = await loop.run_in_executor(None, fetch_one_sync, sym)
                if not df.empty:
                    path = f"timeframe=1h/symbol={sym}/bf_{sym}_1h.parquet"
                    storage.write_parquet(df, path)
                    total_rows += len(df)
            except Exception as exc:
                log.warning("backfill_hourly_failed", symbol=sym, error=str(exc))
                failed.append(sym)
            finally:
                done += 1
                if done % 100 == 0 or done == len(symbols):
                    log.info("backfill_hourly_progress",
                             done=done, total=len(symbols),
                             pct=f"{done/len(symbols)*100:.1f}%",
                             rows=total_rows, failed=len(failed))

    await asyncio.gather(*[process(sym) for sym in symbols])
    log.info("backfill_hourly_complete", symbols=len(symbols),
             rows=total_rows, failed=len(failed), failed_symbols=failed[:10])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill 2yr hourly OHLCV for all NSE stocks")
    parser.add_argument("--workers", type=int, default=15)
    args = parser.parse_args()
    asyncio.run(backfill_hourly(max_workers=args.workers))
