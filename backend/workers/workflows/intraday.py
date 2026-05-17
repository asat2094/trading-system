import asyncio
from datetime import datetime, timedelta
import pytz
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.logging import get_logger

IST = pytz.timezone("Asia/Kolkata")


@workflow.defn
class Intraday1MinCollectorWorkflow:
    @workflow.run
    async def run(self, symbols: list[str]) -> None:
        log = get_logger(__name__)

        while True:
            now_ist = datetime.now(IST)
            market_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)

            if now_ist >= market_close:
                log.info("intraday_collector_market_closed")
                break

            log.info("intraday_tick_start", symbol_count=len(symbols))

            tasks = [
                workflow.execute_activity(
                    "fetch_shoonya_intraday",
                    args=[sym, now_ist.strftime("%Y-%m-%d")],
                    start_to_close_timeout=timedelta(seconds=50),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                for sym in symbols
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            errors = [r for r in results if isinstance(r, Exception)]
            if errors:
                log.warning("intraday_tick_partial_failure", errors=len(errors))

            await asyncio.sleep(60)
