from __future__ import annotations
import asyncio
import pandas as pd
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

    def to_dsl(self) -> dict:
        return build_dsl(self)

    def run(self, max_symbols: int = 500, timeout_s: int = 120) -> pd.DataFrame:
        symbols = self._fetch_symbols()
        symbols = symbols[:max_symbols]
        symbols = self._apply_filters(symbols)
        return self._compute_results(symbols)

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
