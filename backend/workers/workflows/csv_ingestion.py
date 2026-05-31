"""Workflow: ingest all rawdata/1min CSV files into QuestDB in parallel.

Triggered on-demand. Each symbol is processed by a separate activity.
QuestDB DEDUP (UPSERT KEYS) makes re-runs idempotent.
"""
import asyncio
from datetime import timedelta
from pathlib import Path

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.logging import get_logger

RAWDATA_DIR = Path(__file__).parent.parent.parent.parent / "rawdata" / "1min"


@workflow.defn
class CsvIngestionWorkflow:
    """
    Ingest all rawdata/1min CSVs into QuestDB.

    Input:
        symbols:     list of NSE symbols (empty = all dirs in rawdata/1min)
        concurrency: parallel activity cap (default: 10)
    """

    @workflow.run
    async def run(
        self,
        symbols: list[str] | None = None,
        concurrency: int = 10,
    ) -> dict:
        log = get_logger(__name__)

        if not symbols:
            # Discover symbol dirs at workflow start (path read is safe here via
            # imports_passed_through — the Path was constructed at module level)
            symbols = sorted(p.name for p in RAWDATA_DIR.iterdir() if p.is_dir())

        log.info("csv_ingestion_start", symbols=len(symbols), concurrency=concurrency)

        sem = asyncio.Semaphore(concurrency)
        results = {
            "done": 0,
            "failed": 0,
            "total_files": 0,
            "total_rows": 0,
        }

        async def ingest_one(sym: str):
            async with sem:
                try:
                    r = await workflow.execute_activity(
                        "ingest_csv_symbol",
                        args=[sym],
                        start_to_close_timeout=timedelta(minutes=30),
                        retry_policy=RetryPolicy(
                            maximum_attempts=2,
                            initial_interval=timedelta(seconds=10),
                        ),
                    )
                    results["done"] += 1
                    results["total_files"] += r.get("files_ingested", 0)
                    results["total_rows"] += r.get("rows_ingested", 0)
                except Exception as exc:
                    log.warning("csv_ingestion_symbol_failed", symbol=sym, error=str(exc))
                    results["failed"] += 1

        await asyncio.gather(*[ingest_one(sym) for sym in symbols])

        log.info("csv_ingestion_complete", **results)
        return results
