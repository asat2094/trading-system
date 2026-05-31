"""Workflow: backfill 1-min OHLCV via Kite MCP for a list of symbols.

Triggered on-demand via CLI or Temporal UI.
Automatically skips dates already in QuestDB.
"""
import asyncio
from datetime import date, timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.logging import get_logger


@workflow.defn
class Kite1MinBackfillWorkflow:
    """
    Backfill 1-min OHLCV from Kite MCP for given symbols + date range.

    Input:
        symbols:    list of NSE symbols (empty = full Nifty500 + FnO universe)
        from_date:  YYYY-MM-DD  (default: 2024-01-01)
        to_date:    YYYY-MM-DD  (default: today)
        concurrency: how many symbols to fetch in parallel (default: 3)
    """

    @workflow.run
    async def run(
        self,
        symbols: list[str],
        from_date: str = "2024-01-01",
        to_date: str = "",
        concurrency: int = 3,
    ) -> dict:
        log = get_logger(__name__)

        if not to_date:
            to_date = date.today().isoformat()

        if not symbols:
            # Load universe inside workflow via activity (can't import at workflow level)
            universe = await workflow.execute_activity(
                "get_trading_universe",
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            symbols = universe.get("symbols", [])

        log.info("kite1min_backfill_start",
                 symbols=len(symbols), from_date=from_date, to_date=to_date,
                 concurrency=concurrency)

        sem = asyncio.Semaphore(concurrency)
        results = {"done": 0, "skipped": 0, "failed": 0, "total_rows": 0}

        async def fetch_one(sym: str):
            async with sem:
                try:
                    r = await workflow.execute_activity(
                        "fetch_kitemcp_1min",
                        args=[sym, from_date, to_date, True],
                        start_to_close_timeout=timedelta(hours=2),
                        retry_policy=RetryPolicy(
                            maximum_attempts=2,
                            initial_interval=timedelta(seconds=30),
                        ),
                    )
                    if r.get("skipped"):
                        results["skipped"] += 1
                    elif r.get("error"):
                        results["failed"] += 1
                    else:
                        results["done"] += 1
                        results["total_rows"] += r.get("rows", 0)
                except Exception as exc:
                    log.warning("kite1min_symbol_failed", symbol=sym, error=str(exc))
                    results["failed"] += 1

        await asyncio.gather(*[fetch_one(sym) for sym in symbols])

        log.info("kite1min_backfill_complete", **results)
        return results
