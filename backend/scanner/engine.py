from __future__ import annotations
import asyncio
import concurrent.futures
import pandas as pd
from datetime import date, timedelta
from core.logging import get_logger
from scanner.dsl import build_dsl, SCANNER_DSL_VERSION

log = get_logger(__name__)


class Scanner:
    def __init__(self):
        self._source: dict = {}
        self._filters: list[dict] = []
        self._analysis: dict = {}
        self._indicators: list[str] = []
        self._sort: dict = {}
        self._conditions: list = []

    def from_source(self, source: str, **params) -> "Scanner":
        self._source = {"name": source, **params}
        return self

    def filter(self, **conditions) -> "Scanner":
        for field, value in conditions.items():
            if "__" in field:
                attr, op = field.rsplit("__", 1)
                self._filters.append({"field": attr, "op": op, "value": value})
            else:
                self._filters.append({"field": field, "op": "eq", "value": value})
        return self

    def add_analysis(self, **params) -> "Scanner":
        self._analysis = params
        return self

    def add_indicators(self, indicators: list[str]) -> "Scanner":
        self._indicators = indicators
        return self

    def sort_by(self, field: str, descending: bool = True) -> "Scanner":
        self._sort = {"field": field, "descending": descending}
        return self

    def add_condition(self, fn) -> "Scanner":
        self._conditions.append(fn)
        return self

    def to_dsl(self) -> dict:
        return build_dsl(self)

    async def _fetch_ohlcv(self, symbol: str) -> pd.DataFrame:
        from core.sdk import MarketData
        md = MarketData()
        to_dt = date.today().isoformat()
        from_dt = (date.today() - timedelta(days=60)).isoformat()
        return await md.ohlcv(symbol, "1d", from_dt, to_dt)

    def _run_sync(self, coro):
        try:
            loop = asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        except RuntimeError:
            return asyncio.run(coro)

    def run(self, universe: list[str], max_symbols: int | None = None) -> list[dict]:
        symbols = universe[:max_symbols] if max_symbols is not None else universe
        total = len(self._conditions)
        results = []
        for symbol in symbols:
            if total == 0:
                results.append({"symbol": symbol, "passed": True, "conditions_met": 0, "total_conditions": 0})
            else:
                try:
                    df = self._run_sync(self._fetch_ohlcv(symbol))
                except Exception as exc:
                    log.warning("scanner_ohlcv_fetch_failed", symbol=symbol, error=str(exc))
                    continue
                met = sum(1 for fn in self._conditions if fn(df))
                if met == total:
                    results.append({"symbol": symbol, "passed": True, "conditions_met": met, "total_conditions": total})
        log.info("scanner_run", symbol_count=len(symbols), result_count=len(results))
        return results

    def _fetch_symbols(self) -> list[str]:
        source = self._source.get("name", "nse_universe")
        if source == "nse_universe":
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self._fetch_universe())
                    return future.result()
            except RuntimeError:
                return asyncio.run(self._fetch_universe())
        raise ValueError(f"Unknown source: {source!r}")

    async def _fetch_universe(self) -> list[str]:
        from core.sdk import MarketData
        md = MarketData()
        return await md.universe()

    def _apply_filters(self, symbols: list[str]) -> list[str]:
        return symbols

    def _compute_results(self, symbols: list[str]) -> pd.DataFrame:
        log.info("scanner_run", symbol_count=len(symbols), indicators=self._indicators)
        return pd.DataFrame({"symbol": symbols})
