# backend/scanner/evaluator.py
"""
Core condition evaluation engine.
ConditionNode — tree structure (composite or leaf)
ConditionResult — evaluation output
DataContext — lazy per-(symbol, tf) OHLCV cache
ConditionEvaluator — evaluates a ConditionNode against a DataContext
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from core.logging import get_logger

log = get_logger(__name__)

SCORE_RANGE_FACTOR = 0.5


# ── ConditionNode ─────────────────────────────────────────────────────────────

@dataclass
class ConditionNode:
    # ── Composite ──────────────────────────────────────────────────────────────
    logic: Literal["AND", "OR"] | None = None
    children: list[ConditionNode] = field(default_factory=list)

    # ── Leaf: indicator ────────────────────────────────────────────────────────
    indicator: str | None = None
    operator: str | None = None
    value: float | str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    # ── Leaf: crossover ────────────────────────────────────────────────────────
    crossover: Literal["above", "below"] | None = None
    indicator_a: str | None = None
    indicator_b: str | None = None
    params_a: dict[str, Any] = field(default_factory=dict)
    params_b: dict[str, Any] = field(default_factory=dict)

    # ── Leaf: candlestick ──────────────────────────────────────────────────────
    candlestick: str | None = None

    # ── Leaf: chart_pattern ────────────────────────────────────────────────────
    chart_pattern: str | None = None
    min_confidence: float = 0.5

    # ── Leaf: volume ───────────────────────────────────────────────────────────
    volume_ratio: float | None = None
    volume_period: int = 20

    # ── Leaf: trend ────────────────────────────────────────────────────────────
    trend: str | None = None
    trend_window: int = 20

    # ── Shared ─────────────────────────────────────────────────────────────────
    timeframe: str | None = None  # None = use scan's default_timeframe

    @classmethod
    def from_dict(cls, d: dict) -> ConditionNode:
        if "logic" in d:
            return cls(
                logic=d["logic"],
                children=[cls.from_dict(c) for c in d.get("conditions", [])],
            )
        node_type = d.get("type", "")
        if node_type == "indicator":
            return cls(
                indicator=d["indicator"], operator=d["operator"], value=d["value"],
                params=d.get("params", {}), timeframe=d.get("timeframe"),
            )
        if node_type == "crossover":
            return cls(
                crossover=d["crossover"],
                indicator_a=d["indicator_a"], indicator_b=d["indicator_b"],
                params_a=d.get("params_a", {}), params_b=d.get("params_b", {}),
                timeframe=d.get("timeframe"),
            )
        if node_type == "candlestick":
            return cls(candlestick=d["pattern"], timeframe=d.get("timeframe"))
        if node_type == "chart_pattern":
            return cls(
                chart_pattern=d["pattern"],
                min_confidence=d.get("min_confidence", 0.5),
                timeframe=d.get("timeframe"),
            )
        if node_type == "volume":
            return cls(
                volume_ratio=float(d["value"]),
                volume_period=d.get("period", 20),
                timeframe=d.get("timeframe"),
            )
        if node_type == "trend":
            return cls(
                trend=d["value"],
                trend_window=d.get("period", 20),
                timeframe=d.get("timeframe"),
            )
        raise ValueError(f"Unknown condition type: {node_type!r}")


# ── ConditionResult ───────────────────────────────────────────────────────────

@dataclass
class ConditionResult:
    passed: bool
    score: float        # 0.0–1.0
    details: dict
    node_type: str


# ── DataContext ───────────────────────────────────────────────────────────────

class DataContext:
    """Lazy per-(symbol, timeframe) OHLCV cache. One instance per symbol per scan."""

    def __init__(self, symbol: str, default_tf: str, fetch_fn):
        self._symbol = symbol
        self._default_tf = default_tf
        self._fetch_fn = fetch_fn   # async (symbol: str, tf: str) -> pd.DataFrame
        self._cache: dict[str, pd.DataFrame] = {}

    async def get(self, tf: str | None = None) -> pd.DataFrame:
        resolved = tf or self._default_tf
        if resolved not in self._cache:
            self._cache[resolved] = await self._fetch_fn(self._symbol, resolved)
        return self._cache[resolved]


# ── ConditionEvaluator ────────────────────────────────────────────────────────

class ConditionEvaluator:
    """Evaluates a ConditionNode tree against a DataContext. Pure logic — no I/O."""

    async def evaluate(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
        if node.logic:
            return await self._eval_composite(node, ctx)
        if node.crossover:
            return await self._eval_crossover(node, ctx)
        if node.indicator:
            return await self._eval_indicator(node, ctx)
        if node.candlestick:
            return await self._eval_candlestick(node, ctx)
        if node.chart_pattern:
            return await self._eval_chart_pattern(node, ctx)
        if node.volume_ratio is not None:
            return await self._eval_volume(node, ctx)
        if node.trend:
            return await self._eval_trend(node, ctx)
        raise ValueError("Invalid ConditionNode: no leaf type set")

    # ── composite ─────────────────────────────────────────────────────────────

    async def _eval_composite(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
        child_results = [await self.evaluate(child, ctx) for child in node.children]

        if node.logic == "AND":
            passed = all(r.passed for r in child_results)
            score = (sum(r.score for r in child_results) / len(child_results)) if passed else 0.0
        else:  # OR
            passed = any(r.passed for r in child_results)
            score = max(r.score for r in child_results) if passed else 0.0

        return ConditionResult(
            passed=passed,
            score=round(score, 4),
            details={
                "children": [
                    {"passed": r.passed, "score": r.score, "node_type": r.node_type, **r.details}
                    for r in child_results
                ]
            },
            node_type=node.logic,
        )

    # ── indicator ─────────────────────────────────────────────────────────────

    async def _eval_indicator(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
        df = await ctx.get(node.timeframe)
        if df.empty:
            return ConditionResult(passed=False, score=0.0,
                                   details={"error": "no_data"}, node_type="indicator")

        from core.sdk import get_indicator_by_name
        try:
            fn = get_indicator_by_name(node.indicator)
        except KeyError as e:
            return ConditionResult(passed=False, score=0.0,
                                   details={"error": str(e)}, node_type="indicator")

        try:
            result = fn(df, **node.params)
        except TypeError as e:
            return ConditionResult(passed=False, score=0.0,
                                   details={"error": f"bad_params: {e}"}, node_type="indicator")

        if result is None or (hasattr(result, "empty") and result.empty):
            return ConditionResult(passed=False, score=0.0,
                                   details={"error": "indicator_empty"}, node_type="indicator")

        # Check that the series/df has at least one non-NaN value after dropna
        if isinstance(result, pd.Series):
            if result.dropna().empty:
                return ConditionResult(passed=False, score=0.0,
                                       details={"error": "indicator_all_nan"}, node_type="indicator")
        elif isinstance(result, pd.DataFrame):
            if result.dropna(how="all").empty:
                return ConditionResult(passed=False, score=0.0,
                                       details={"error": "indicator_all_nan"}, node_type="indicator")

        if node.operator in ("cross_above", "cross_below"):
            return await self._eval_indicator_cross(node, result)

        value = self._extract_scalar(result, node.indicator)
        passed, score = self._apply_operator(value, node.operator, float(node.value))
        return ConditionResult(
            passed=passed,
            score=score,
            details={f"{node.indicator}_value": round(value, 4)},
            node_type="indicator",
        )

    async def _eval_indicator_cross(self, node: ConditionNode, series_or_df) -> ConditionResult:
        if isinstance(series_or_df, pd.DataFrame):
            series = series_or_df.iloc[:, 0].dropna()
        else:
            series = series_or_df.dropna()
        if len(series) < 2:
            return ConditionResult(passed=False, score=0.0,
                                   details={"error": "need_2_bars"}, node_type="indicator")
        prev, curr = float(series.iloc[-2]), float(series.iloc[-1])
        threshold = float(node.value)
        if node.operator == "cross_above":
            passed = prev < threshold and curr >= threshold
        else:
            passed = prev > threshold and curr <= threshold
        return ConditionResult(
            passed=passed,
            score=1.0 if passed else 0.0,
            details={
                f"{node.indicator}_prev": round(prev, 4),
                f"{node.indicator}_curr": round(curr, 4),
            },
            node_type="indicator",
        )

    def _extract_scalar(self, result, indicator_name: str) -> float:
        """Extract primary scalar from indicator output."""
        if isinstance(result, pd.Series):
            return float(result.dropna().iloc[-1])

        if isinstance(result, pd.DataFrame):
            PRIMARY_PREFIXES = {
                "macd":            "MACD_",
                "bollinger_bands": "BBM_",
                "stochastic":      "STOCHk_",
                "supertrend":      "SUPERT_",
                "ichimoku":        "ISA_",
            }
            prefix = PRIMARY_PREFIXES.get(indicator_name)
            if prefix:
                matching = [c for c in result.columns if c.startswith(prefix)]
                if matching:
                    return float(result[matching[0]].dropna().iloc[-1])
            return float(result.iloc[:, 0].dropna().iloc[-1])

        return float(result)

    def _apply_operator(self, value: float, operator: str, threshold: float) -> tuple[bool, float]:
        if operator == "lt":
            passed = value < threshold
            score = max(0.0, min(1.0, (threshold - value) / (threshold * SCORE_RANGE_FACTOR))) if passed else 0.0
        elif operator == "gt":
            passed = value > threshold
            score = max(0.0, min(1.0, (value - threshold) / (threshold * SCORE_RANGE_FACTOR))) if passed else 0.0
        elif operator == "lte":
            passed = value <= threshold
            score = max(0.0, min(1.0, (threshold - value) / (threshold * SCORE_RANGE_FACTOR))) if passed else 0.0
        elif operator == "gte":
            passed = value >= threshold
            score = max(0.0, min(1.0, (value - threshold) / (threshold * SCORE_RANGE_FACTOR))) if passed else 0.0
        elif operator == "eq":
            passed = abs(value - threshold) < (threshold * 0.01)
            score = 1.0 if passed else 0.0
        else:
            raise ValueError(f"Unknown operator: {operator!r}")
        return passed, round(score, 4)

    # ── crossover ─────────────────────────────────────────────────────────────

    async def _eval_crossover(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
        df = await ctx.get(node.timeframe)
        if df.empty or len(df) < 2:
            return ConditionResult(passed=False, score=0.0,
                                   details={"error": "no_data"}, node_type="crossover")

        from core.sdk import get_indicator_by_name
        try:
            fn_a = get_indicator_by_name(node.indicator_a)
            fn_b = get_indicator_by_name(node.indicator_b)
        except KeyError as e:
            return ConditionResult(passed=False, score=0.0,
                                   details={"error": str(e)}, node_type="crossover")

        try:
            result_a = fn_a(df, **node.params_a)
            result_b = fn_b(df, **node.params_b)
        except TypeError as e:
            return ConditionResult(passed=False, score=0.0,
                                   details={"error": f"bad_params: {e}"}, node_type="crossover")

        series_a = result_a if isinstance(result_a, pd.Series) else result_a.iloc[:, 0]
        series_b = result_b if isinstance(result_b, pd.Series) else result_b.iloc[:, 0]

        combined = pd.DataFrame({"a": series_a, "b": series_b}).dropna()
        if len(combined) < 2:
            return ConditionResult(passed=False, score=0.0,
                                   details={"error": "insufficient_data"}, node_type="crossover")

        prev_a, curr_a = combined["a"].iloc[-2], combined["a"].iloc[-1]
        prev_b, curr_b = combined["b"].iloc[-2], combined["b"].iloc[-1]

        if node.crossover == "above":
            passed = prev_a <= prev_b and curr_a > curr_b
        else:
            passed = prev_a >= prev_b and curr_a < curr_b

        return ConditionResult(
            passed=passed,
            score=1.0 if passed else 0.0,
            details={
                f"{node.indicator_a}_curr": round(float(curr_a), 4),
                f"{node.indicator_b}_curr": round(float(curr_b), 4),
                "gap": round(float(abs(curr_a - curr_b)), 4),
            },
            node_type="crossover",
        )

    # ── candlestick ───────────────────────────────────────────────────────────

    async def _eval_candlestick(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
        df = await ctx.get(node.timeframe)
        if len(df) < 3:
            return ConditionResult(passed=False, score=0.0,
                                   details={}, node_type="candlestick")

        from core.sdk import Patterns
        try:
            result = Patterns.detect_candlestick(df.tail(3), node.candlestick)
        except ValueError as e:
            return ConditionResult(passed=False, score=0.0,
                                   details={"error": str(e)}, node_type="candlestick")

        if result is None:
            return ConditionResult(passed=False, score=0.0,
                                   details={"pattern": node.candlestick}, node_type="candlestick")
        return ConditionResult(
            passed=True,
            score=result["confidence"],
            details={"pattern": node.candlestick, "confidence": result["confidence"]},
            node_type="candlestick",
        )

    # ── chart_pattern ─────────────────────────────────────────────────────────

    async def _eval_chart_pattern(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
        df = await ctx.get(node.timeframe)
        if len(df) < 20:
            return ConditionResult(passed=False, score=0.0,
                                   details={}, node_type="chart_pattern")

        from core.sdk import Patterns
        results = Patterns.detect(df, [node.chart_pattern])
        if not results:
            return ConditionResult(passed=False, score=0.0,
                                   details={"pattern": node.chart_pattern}, node_type="chart_pattern")

        best = max(results, key=lambda r: r["confidence"])
        passed = best["confidence"] >= node.min_confidence
        return ConditionResult(
            passed=passed,
            score=best["confidence"] if passed else 0.0,
            details=best,
            node_type="chart_pattern",
        )

    # ── volume ────────────────────────────────────────────────────────────────

    async def _eval_volume(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
        df = await ctx.get(node.timeframe)
        if len(df) < node.volume_period + 1:
            return ConditionResult(passed=False, score=0.0,
                                   details={}, node_type="volume")

        last_volume = df["volume"].iloc[-1]
        avg_volume = df["volume"].iloc[-(node.volume_period + 1):-1].mean()
        if avg_volume == 0:
            return ConditionResult(passed=False, score=0.0,
                                   details={"error": "zero_avg_volume"}, node_type="volume")

        ratio = last_volume / avg_volume
        passed = ratio >= node.volume_ratio
        score = min(1.0, (ratio - node.volume_ratio) / node.volume_ratio) if passed else 0.0
        return ConditionResult(
            passed=passed,
            score=round(score, 4),
            details={"volume_ratio": round(ratio, 2), "required": node.volume_ratio},
            node_type="volume",
        )

    # ── trend ─────────────────────────────────────────────────────────────────

    async def _eval_trend(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
        df = await ctx.get(node.timeframe)
        from core.sdk import Patterns
        result = Patterns.trend(df, window=node.trend_window)
        passed = result.direction == node.trend
        score = result.strength if passed else 0.0
        return ConditionResult(
            passed=passed,
            score=round(score, 4),
            details={
                "direction": result.direction,
                "strength": result.strength,
                "r_squared": result.r_squared,
            },
            node_type="trend",
        )
