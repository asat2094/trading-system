# backend/scanner/engine.py
from __future__ import annotations

import asyncio
import concurrent.futures
from dataclasses import dataclass
from datetime import datetime, timedelta, date

import pandas as pd

from core.logging import get_logger
from scanner.dsl import build_dsl, SCANNER_DSL_VERSION

log = get_logger(__name__)

SCANNER_MAX_CONCURRENT = 20

TF_LOOKBACK_CAP = {
    "1min":  5,
    "3min":  10,
    "5min":  15,
    "15min": 30,
    "30min": 60,
    "1h":    120,
    "1d":    None,  # Will be set by lookback_days parameter
    "1w":    None,
    "1M":    None,
}


# ── ScanResult ────────────────────────────────────────────────────────────────

@dataclass
class ScanResult:
    symbol: str
    overall_score: float
    matched_signals: list[str]
    signal_details: dict           # signal_name -> SignalResult dataclass
    custom_passed: bool


# ── Scanner ───────────────────────────────────────────────────────────────────

class Scanner:
    """Async scanner. Run via run_async(). Legacy builder API preserved for backwards compat."""

    def __init__(self):
        self._source: dict = {}
        self._filters: list[dict] = []
        self._analysis: dict = {}
        self._indicators: list[str] = []
        self._sort: dict = {}
        self._conditions: list = []

    # ── legacy builder API ────────────────────────────────────────────────────

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

    def _fetch_symbols(self) -> list[str]:
        source = self._source.get("name", "nse_universe")
        if source == "nse_universe":
            try:
                loop = asyncio.get_running_loop()
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

    # ── new async core ────────────────────────────────────────────────────────

    def _make_fetch_fn(self, lookback_days: int):
        """Returns async (symbol, tf) -> DataFrame with timeframe-aware lookback."""
        from core.sdk import MarketData
        md = MarketData()

        # Create a copy with lookback_days substituted for daily/weekly/monthly timeframes
        tf_lookback = TF_LOOKBACK_CAP.copy()
        tf_lookback["1d"] = lookback_days
        tf_lookback["1w"] = lookback_days
        tf_lookback["1M"] = lookback_days

        async def fetch(symbol: str, tf: str):
            cap = tf_lookback.get(tf, lookback_days)
            effective_days = min(lookback_days, cap)
            to_dt = datetime.now()
            from_dt = to_dt - timedelta(days=effective_days)
            return await md.ohlcv(symbol, tf, from_dt, to_dt)

        return fetch

    def _apply_match_mode(
        self,
        mode: str,
        matched: list[str],
        signal_results: dict,
        custom_passed: bool,
        custom_tree,
    ) -> bool:
        if mode == "any_signal":
            return len(matched) > 0
        elif mode == "all_signals":
            return all(sr.passed for sr in signal_results.values())
        elif mode == "custom_only":
            return custom_passed
        elif mode == "signals_and_custom":
            signals_ok = len(matched) > 0 if signal_results else True
            return signals_ok and custom_passed
        return False

    async def run_async(
        self,
        universe: list[str],
        signals: list[str],
        custom_conditions: dict | None,
        default_timeframe: str,
        match_mode: str,
        max_symbols: int,
        lookback_days: int = 200,
    ) -> list[ScanResult]:
        """Core async scan with semaphore-controlled concurrency."""
        from scanner.signals.loader import load_signals
        from scanner.signals.evaluator import SignalEvaluator, SignalResult
        from scanner.evaluator import ConditionEvaluator, DataContext, ConditionNode

        all_signals = {s.name: s for s in load_signals()}
        requested_signals = [all_signals[n] for n in signals if n in all_signals]

        unknown = set(signals) - set(all_signals)
        if unknown:
            log.warning("scanner_unknown_signals", names=list(unknown))

        sig_eval = SignalEvaluator()
        cond_eval = ConditionEvaluator()

        custom_tree = None
        if custom_conditions:
            custom_tree = ConditionNode.from_dict(custom_conditions)

        symbols = universe[:max_symbols]
        results: list[ScanResult] = []
        semaphore = asyncio.Semaphore(SCANNER_MAX_CONCURRENT)

        async def eval_symbol(symbol: str) -> ScanResult | None:
            async with semaphore:
                ctx = DataContext(
                    symbol=symbol,
                    default_tf=default_timeframe,
                    fetch_fn=self._make_fetch_fn(lookback_days),
                )
                signal_results: dict = {}
                for sig in requested_signals:
                    try:
                        sr = await sig_eval.evaluate(sig, ctx, cond_eval)
                        signal_results[sig.name] = sr
                    except Exception as exc:
                        log.warning("signal_eval_failed", signal=sig.name,
                                    symbol=symbol, error=str(exc))
                        signal_results[sig.name] = SignalResult(
                            signal_name=sig.name, passed=False, score=0.0,
                            conditions_passed=0, conditions_total=len(sig.conditions),
                            details={"error": str(exc)}, display=sig.display,
                        )

                custom_passed = True
                if custom_tree:
                    try:
                        cr = await cond_eval.evaluate(custom_tree, ctx)
                        custom_passed = cr.passed
                    except Exception as exc:
                        log.warning("custom_eval_failed", symbol=symbol, error=str(exc))
                        custom_passed = False

                matched = [n for n, sr in signal_results.items() if sr.passed]
                passes = self._apply_match_mode(
                    match_mode, matched, signal_results, custom_passed, custom_tree
                )
                if not passes:
                    return None

                overall_score = (
                    sum(sr.score for sr in signal_results.values() if sr.passed) / max(len(matched), 1)
                    if matched else 0.0
                )
                return ScanResult(
                    symbol=symbol,
                    overall_score=round(overall_score, 4),
                    matched_signals=matched,
                    signal_details={n: sr for n, sr in signal_results.items()},
                    custom_passed=custom_passed,
                )

        tasks = [eval_symbol(sym) for sym in symbols]
        raw = await asyncio.gather(*tasks, return_exceptions=True)
        for item in raw:
            if isinstance(item, Exception):
                log.warning("scanner_symbol_failed", error=str(item))
            elif item is not None:
                results.append(item)

        log.info("scanner_run_complete", total=len(symbols), matched=len(results))
        return results

    # ── legacy sync run (kept for unit test compat) ───────────────────────────

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
        """Legacy sync API kept for backwards compatibility. Use run_async instead."""
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
