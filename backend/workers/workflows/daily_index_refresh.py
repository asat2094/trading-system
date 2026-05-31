"""Workflow: daily 1-min OHLCV refresh for all index symbols.

Same catch-up and idempotency logic as DailyRefreshWorkflow, but targets
NSE/BSE index symbols (NIFTY family, SENSEX, etc.) instead of the equity
trading universe.

Triggered by the same Temporal Schedule mechanism — register via:
    cd backend && PYTHONPATH=. .venv/bin/python scripts/register_schedules.py
"""
import asyncio
from datetime import date, timedelta, timezone
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.logging import get_logger
    from core.config import settings

# IST fixed offset — builtin, never proxied by Temporal sandbox.
_IST = timezone(timedelta(hours=5, minutes=30))


@workflow.defn
class DailyIndexRefreshWorkflow:
    @workflow.run
    async def run(
        self,
        gap_days: int | None = None,
        concurrency: int | None = None,
    ) -> dict:
        log = get_logger(__name__)

        _gap_days    = gap_days    if gap_days    is not None else settings.DAILY_REFRESH_GAP_DAYS
        _concurrency = concurrency if concurrency is not None else settings.DAILY_REFRESH_CONCURRENCY

        # ── Guard 1: weekday in IST? ─────────────────────────────────────────
        today_ist: date = workflow.now().astimezone(_IST).date()

        if today_ist.weekday() >= 5:
            log.info("daily_index_refresh_skipped_weekend", date=str(today_ist))
            return {"skipped": True, "reason": "weekend"}

        # ── Guard 2: already ran today? ──────────────────────────────────────
        latest = await workflow.execute_activity(
            "get_latest_data_date",
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        latest_date: str | None = latest.get("latest_date")

        if latest_date == str(today_ist):
            log.info("daily_index_refresh_already_done", date=latest_date)
            return {"skipped": True, "reason": "already_ran_today", "date": latest_date}

        # ── Load index universe ──────────────────────────────────────────────
        universe = await workflow.execute_activity(
            "get_index_universe",
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        symbols: list[str] = universe.get("symbols", [])

        from_date = (today_ist - timedelta(days=_gap_days)).isoformat()
        to_date   = today_ist.isoformat()

        log.info(
            "daily_index_refresh_start",
            date=str(today_ist),
            symbols=len(symbols),
            from_date=from_date,
            to_date=to_date,
            gap_days=_gap_days,
            concurrency=_concurrency,
            last_data=latest_date,
        )

        # ── Fan out ──────────────────────────────────────────────────────────
        sem = asyncio.Semaphore(_concurrency)
        results = {"done": 0, "skipped": 0, "failed": 0, "total_rows": 0}

        async def fetch_one(sym: str) -> None:
            async with sem:
                try:
                    r = await workflow.execute_activity(
                        "fetch_kitemcp_index_1min",
                        args=[sym, from_date, to_date, True],
                        start_to_close_timeout=timedelta(hours=1),
                        retry_policy=RetryPolicy(
                            maximum_attempts=2,
                            initial_interval=timedelta(seconds=30),
                            backoff_coefficient=2.0,
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
                    log.warning("daily_index_refresh_symbol_failed",
                                symbol=sym, error=str(exc))
                    results["failed"] += 1

        await asyncio.gather(*[fetch_one(sym) for sym in symbols])

        log.info("daily_index_refresh_complete", date=str(today_ist), **results)
        return {"date": str(today_ist), **results}
