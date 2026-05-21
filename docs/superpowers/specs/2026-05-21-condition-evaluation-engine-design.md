# Condition Evaluation Engine — Design Spec

**Date:** 2026-05-21 (rev 2)
**Scope:** Sub-project 3a of the Technical Analysis Engine. Backtesting and Quant Models are separate specs that plug into this engine's interfaces.
**Goal:** Build a composable, multi-timeframe condition evaluation engine that powers the scanner, signal library, and (later) backtesting and quant model integration.

---

## 1. Problem Statement

The existing scanner (`scanner/engine.py`) is broken in three ways:

1. **YAML signals never evaluated.** Signal YAML defines conditions (`candlestick_pattern`, `volume_confirmation`, `trend_context`, `indicator`) but no evaluator exists — signals load but never run.
2. **API contract mismatch.** `POST /scanner/run` returns `{"results": [...]}` but frontend expects `{"symbols": [...], "results": [...]}`. Scanner shows zero results.
3. **No condition composition.** Conditions are Python closures added via `add_condition(fn)` — not serializable, not multi-timeframe, not usable from YAML or API.

This spec defines the condition evaluation engine that fixes all three and becomes the shared foundation for backtesting (#4) and quant models (#4+).

---

## 2. Architecture

### 2.1 Core Concept

One `ConditionNode` tree. One `ConditionEvaluator`. Everything else plugs in.

```
ConditionNode tree
      │
      ▼
ConditionEvaluator
  ├── DataContext  — lazy (symbol, timeframe) OHLCV cache
  ├── leaf evaluators  — one per condition type
  └── ConditionResult(passed, score, details)
```

- **Scanner** builds a ConditionNode tree from YAML signals + custom conditions, runs it over a universe of symbols.
- **Backtesting engine** (future) reuses the same ConditionNode tree, runs it at each historical bar.
- **Quant models** (future) add a `quant_model` leaf type; ConditionEvaluator dispatches to model runtime.

No component below `ConditionEvaluator` knows about "scanning" or "backtesting". They only know about DataFrames and ConditionNodes.

### 2.2 Cross-Module Boundary Rule

The older design spec (§5.4) mandates: `scanner/` calls `technical/` only through `core/sdk.py` interfaces. This spec **honours that**:

- `ConditionEvaluator` calls `Indicators.rsi(df)`, `Patterns.detect(df, [...])` etc. from `core/sdk.py`.
- It does NOT import from `technical/indicators/registry.py` or `technical/patterns/` directly.
- `core/sdk.py` already wraps the registry — use that wrapper.

One addition needed: `core/sdk.py` must expose `get_indicator_by_name(name) -> Callable` so the evaluator can dynamically look up indicators by string name. This is a thin passthrough to `technical/indicators/registry.get_indicator`.

### 2.3 New Files

```
backend/
  scanner/
    evaluator.py              # NEW — ConditionNode, ConditionEvaluator, DataContext, ConditionResult, ScanResult
    signals/
      evaluator.py            # NEW — SignalEvaluator wraps SignalConfig → ConditionNode tree
  technical/
    patterns/
      candlestick.py          # NEW — candlestick pattern detection (7 patterns)
```

### 2.4 Modified Files

```
backend/
  core/
    sdk.py                    # Add get_indicator_by_name(), add candlestick to Patterns
  scanner/
    engine.py                 # Rewrite run() to use ConditionEvaluator
    signals/
      models.py               # Add timeframe, period, min_confidence fields to SignalCondition
  technical/
    indicators/
      registry.py             # Register missing indicators (stochastic, cci, sma, obv, supertrend)
    patterns/
      detector.py             # Add candlestick patterns to _DETECTORS
  api/routers/
    scanner.py                # New request/response format + POST /scanner/evaluate
frontend/src/
  components/Screener/
    ConditionBuilder.tsx       # Hierarchical AND/OR builder with per-condition TF
    ResultsTable.tsx           # Show signal match chips + score breakdown
  api/
    scanner.ts                 # Updated request/response types
  store/
    filters.ts                 # ConditionNode tree state
```

---

## 3. Data Structures

### 3.1 ConditionNode

```python
# scanner/evaluator.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Any

@dataclass
class ConditionNode:
    # ── Composite node ──────────────────────────────────────────────────────
    logic: Literal["AND", "OR"] | None = None
    children: list[ConditionNode] = field(default_factory=list)

    # ── Leaf: indicator ─────────────────────────────────────────────────────
    # Covers: rsi, macd, ema, sma, vwap, atr, bollinger_bands, stochastic, cci, obv
    # operator: "lt" | "gt" | "lte" | "gte" | "eq" | "cross_above" | "cross_below"
    # cross_above/cross_below: compares last two bars (t-1 was below/above, t is above/below)
    indicator: str | None = None          # e.g. "rsi"
    operator: str | None = None
    value: float | str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    # params holds indicator-specific kwargs: {"period": 14}, {"fast": 12, "slow": 26},
    # {"period": 20, "std": 2.0}, etc. Passed directly to the indicator function.
    # This replaces a single `period` field — each indicator has different params.
    # Empty dict = use indicator defaults.

    # ── Leaf: crossover ──────────────────────────────────────────────────────
    # Two indicators compared against each other (e.g. EMA 20 crosses above EMA 50)
    crossover: Literal["above", "below"] | None = None
    indicator_a: str | None = None        # e.g. "ema"
    indicator_b: str | None = None        # e.g. "ema"
    params_a: dict[str, Any] = field(default_factory=dict)   # e.g. {"period": 20}
    params_b: dict[str, Any] = field(default_factory=dict)   # e.g. {"period": 50}

    # ── Leaf: candlestick pattern ────────────────────────────────────────────
    # Detects on last 1–3 bars
    candlestick: str | None = None        # e.g. "bearish_engulfing"

    # ── Leaf: chart pattern ──────────────────────────────────────────────────
    # Detects over full DataFrame window
    chart_pattern: str | None = None      # e.g. "double_bottom"
    min_confidence: float = 0.5           # minimum pattern confidence to pass

    # ── Leaf: volume ─────────────────────────────────────────────────────────
    # Compares last bar volume to N-bar rolling average
    volume_ratio: float | None = None     # e.g. 1.5 → last volume > 1.5× avg
    volume_period: int = 20

    # ── Leaf: trend ──────────────────────────────────────────────────────────
    # Uses technical.trend.analyze_trend()
    trend: str | None = None              # "up" | "down" | "sideways"
    trend_window: int = 20

    # ── Shared: timeframe override ───────────────────────────────────────────
    # None = use the scan's default_timeframe
    timeframe: str | None = None
```

Rules:
- Node is a **composite** if `logic` is set and `children` is non-empty.
- Node is a **leaf** if exactly one of `indicator`, `crossover`, `candlestick`, `chart_pattern`, `volume_ratio`, `trend` is set.
- A node that is neither is invalid — `ConditionEvaluator` validates before evaluation.

### 3.2 ConditionResult

```python
@dataclass
class ConditionResult:
    passed: bool
    score: float          # 0.0–1.0 — strength of signal, not just bool
    details: dict         # {"rsi_value": 24.5} | {"pattern": "double_bottom", "confidence": 0.82}
    node_type: str        # "indicator" | "crossover" | "candlestick" | "chart_pattern" | "volume" | "trend" | "AND" | "OR"
```

**Score semantics:**

Indicator `lt`: how far below threshold, normalized to `[0, 1]`.
- Formula: `score = clamp((threshold - value) / (threshold * SCORE_RANGE_FACTOR), 0, 1)` where `SCORE_RANGE_FACTOR = 0.5`.
- `RSI=25, threshold=30`: `(30-25) / (30*0.5) = 5/15 = 0.33`
- `RSI=15, threshold=30`: `(30-15) / 15 = 1.0`
- `RSI=29, threshold=30`: `(30-29) / 15 = 0.067`
- `RSI=31, threshold=30`: fails → 0.0

Indicator `gt`: mirror. `score = clamp((value - threshold) / (threshold * SCORE_RANGE_FACTOR), 0, 1)`.

Crossover: 1.0 if crossover detected (binary — either it crossed or it didn't).

Pattern: `confidence` from detector, already 0–1.

Volume: `clamp((actual_ratio - required_ratio) / required_ratio, 0, 1)` — how much the ratio exceeded the requirement. Exactly at threshold = 0.0 score. 2× the required ratio = 1.0.

Trend: `strength` from `TrendResult` if direction matches, else 0.0.

AND composite: `mean(child_scores)` if all children passed, else 0.0.
OR composite: `max(child_scores)`.

### 3.3 ScanResult

```python
@dataclass
class ScanResult:
    symbol: str
    overall_score: float              # 0.0–1.0 aggregate
    matched_signals: list[str]        # signal names that passed
    signal_details: dict[str, SignalResult]
    custom_passed: bool               # True if custom conditions passed (or no custom conditions)
```

### 3.4 DataContext

```python
class DataContext:
    """Per-symbol OHLCV cache. Shared across all conditions for one symbol evaluation."""

    def __init__(self, symbol: str, default_tf: str, fetch_fn):
        self._symbol = symbol
        self._default_tf = default_tf
        self._fetch_fn = fetch_fn   # async: (symbol, tf) -> pd.DataFrame
        self._cache: dict[str, pd.DataFrame] = {}

    async def get(self, tf: str | None) -> pd.DataFrame:
        resolved = tf or self._default_tf
        if resolved not in self._cache:
            self._cache[resolved] = await self._fetch_fn(self._symbol, resolved)
        return self._cache[resolved]
```

One `DataContext` per symbol per scan. Prevents re-fetching the same (symbol, timeframe) when multiple conditions share a timeframe.

**`fetch_fn` implementation** (`Scanner._make_fetch_fn`):

```python
def _make_fetch_fn(self, lookback_days: int):
    """Returns async (symbol, tf) -> DataFrame with timeframe-aware lookback."""
    md = MarketData()

    # Timeframe-aware lookback: intraday TFs get shorter windows to limit data volume.
    # 1min on 200 days = ~57k bars → wasteful. Cap intraday to sensible windows.
    TF_LOOKBACK_CAP = {
        "1min": 5,     # 5 days of 1min = ~1875 bars
        "3min": 10,
        "5min": 15,
        "15min": 30,
        "30min": 60,
        "1h": 120,
        "1d": lookback_days,
        "1w": lookback_days,
        "1M": lookback_days,
    }

    async def fetch(symbol: str, tf: str) -> pd.DataFrame:
        cap = TF_LOOKBACK_CAP.get(tf, lookback_days)
        effective_days = min(lookback_days, cap)
        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=effective_days)
        return await md.ohlcv(symbol, tf, from_dt, to_dt)

    return fetch
```

---

## 4. ConditionEvaluator

```python
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
        raise ValueError(f"Invalid ConditionNode: no leaf type set")
```

### 4.1 Indicator Evaluation

```python
async def _eval_indicator(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
    df = await ctx.get(node.timeframe)
    if df.empty:
        return ConditionResult(passed=False, score=0.0, details={"error": "no_data"}, node_type="indicator")

    from core.sdk import get_indicator_by_name
    fn = get_indicator_by_name(node.indicator)

    # Pass indicator-specific params (period, fast, slow, std, etc.)
    # Empty dict = use function defaults.
    try:
        result = fn(df, **node.params)
    except TypeError as e:
        return ConditionResult(passed=False, score=0.0,
                               details={"error": f"bad_params: {e}"}, node_type="indicator")

    if result is None or (hasattr(result, 'empty') and result.empty):
        return ConditionResult(passed=False, score=0.0,
                               details={"error": "indicator_empty"}, node_type="indicator")

    value = self._extract_scalar(result, node.indicator, node.params)

    passed, score = self._apply_operator(value, node.operator, float(node.value))
    return ConditionResult(
        passed=passed,
        score=score,
        details={f"{node.indicator}_value": round(value, 4)},
        node_type="indicator",
    )
```

**`_extract_scalar` — dynamic column resolution (no hardcoded names):**

```python
def _extract_scalar(self, result, indicator_name: str, params: dict) -> float:
    """Extract a single float from indicator output. Handles Series and DataFrame."""
    if isinstance(result, pd.Series):
        return float(result.dropna().iloc[-1])

    if isinstance(result, pd.DataFrame):
        # pandas_ta generates columns like MACD_12_26_9, BBU_20_2.0, STOCHk_14_3_3
        # Strategy: pick the "primary" column by prefix convention.
        PRIMARY_PREFIXES = {
            "macd": "MACD_",      # MACD line (not MACDh_ histogram, not MACDs_ signal)
            "bollinger_bands": "BBM_",  # middle band by default
            "stochastic": "STOCHk_",
            "supertrend": "SUPERT_",
            "ichimoku": "ISA_",
        }
        prefix = PRIMARY_PREFIXES.get(indicator_name)
        if prefix:
            matching = [c for c in result.columns if c.startswith(prefix)]
            if matching:
                return float(result[matching[0]].dropna().iloc[-1])
        # Fallback: first column
        return float(result.iloc[:, 0].dropna().iloc[-1])

    return float(result)
```

For Bollinger Bands upper/lower: the `operator` + `value` field in the condition handles this naturally. `indicator="bollinger_bands", operator="gt", value="upper"` is NOT supported — use price comparisons instead. BB conditions are expressed as: "close > BB upper" which is a crossover-style comparison. For MVP, BB is used as indicator overlay on chart, not as scanner condition. If needed later, add a `price_vs_indicator` leaf type.

**`_apply_operator`:**

```python
SCORE_RANGE_FACTOR = 0.5

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
        passed = abs(value - threshold) < (threshold * 0.01)  # within 1%
        score = 1.0 if passed else 0.0
    elif operator in ("cross_above", "cross_below"):
        # Threshold crossing: indicator crosses a static value
        # Uses last 2 non-NaN values from the indicator series
        # Handled at caller level — see _eval_indicator_cross
        passed = False
        score = 0.0
    else:
        raise ValueError(f"Unknown operator: {operator!r}")
    return passed, round(score, 4)
```

For `cross_above` / `cross_below` on a static threshold, the evaluator needs the last 2 values, not just the last one. The `_eval_indicator` method detects these operators and calls a separate path:

```python
if node.operator in ("cross_above", "cross_below"):
    return await self._eval_indicator_cross(node, ctx, result)
```

```python
async def _eval_indicator_cross(self, node, ctx, series_or_df) -> ConditionResult:
    if isinstance(series_or_df, pd.DataFrame):
        series = series_or_df.iloc[:, 0].dropna()
    else:
        series = series_or_df.dropna()
    if len(series) < 2:
        return ConditionResult(passed=False, score=0.0, details={"error": "need_2_bars"}, node_type="indicator")
    prev, curr = float(series.iloc[-2]), float(series.iloc[-1])
    threshold = float(node.value)
    if node.operator == "cross_above":
        passed = prev < threshold and curr >= threshold
    else:
        passed = prev > threshold and curr <= threshold
    return ConditionResult(
        passed=passed,
        score=1.0 if passed else 0.0,
        details={f"{node.indicator}_prev": round(prev, 4), f"{node.indicator}_curr": round(curr, 4)},
        node_type="indicator",
    )
```

### 4.2 Crossover Evaluation (indicator vs indicator)

This is the **new leaf type** for conditions like "EMA 20 crosses above EMA 50":

```python
async def _eval_crossover(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
    df = await ctx.get(node.timeframe)
    if df.empty or len(df) < 2:
        return ConditionResult(passed=False, score=0.0, details={"error": "no_data"}, node_type="crossover")

    from core.sdk import get_indicator_by_name
    fn_a = get_indicator_by_name(node.indicator_a)
    fn_b = get_indicator_by_name(node.indicator_b)

    try:
        result_a = fn_a(df, **node.params_a)
        result_b = fn_b(df, **node.params_b)
    except TypeError as e:
        return ConditionResult(passed=False, score=0.0,
                               details={"error": f"bad_params: {e}"}, node_type="crossover")

    series_a = result_a if isinstance(result_a, pd.Series) else result_a.iloc[:, 0]
    series_b = result_b if isinstance(result_b, pd.Series) else result_b.iloc[:, 0]

    # Align and drop NaN
    combined = pd.DataFrame({"a": series_a, "b": series_b}).dropna()
    if len(combined) < 2:
        return ConditionResult(passed=False, score=0.0, details={"error": "insufficient_data"}, node_type="crossover")

    prev_a, curr_a = combined["a"].iloc[-2], combined["a"].iloc[-1]
    prev_b, curr_b = combined["b"].iloc[-2], combined["b"].iloc[-1]

    if node.crossover == "above":
        passed = prev_a <= prev_b and curr_a > curr_b
    else:  # "below"
        passed = prev_a >= prev_b and curr_a < curr_b

    details = {
        f"{node.indicator_a}_curr": round(float(curr_a), 4),
        f"{node.indicator_b}_curr": round(float(curr_b), 4),
        "gap": round(float(abs(curr_a - curr_b)), 4),
    }
    return ConditionResult(passed=passed, score=1.0 if passed else 0.0,
                           details=details, node_type="crossover")
```

### 4.3 Candlestick Evaluation

```python
async def _eval_candlestick(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
    df = await ctx.get(node.timeframe)
    if len(df) < 3:
        return ConditionResult(passed=False, score=0.0, details={}, node_type="candlestick")

    from core.sdk import Patterns
    result = Patterns.detect_candlestick(df.tail(3), node.candlestick)
    if result is None:
        return ConditionResult(passed=False, score=0.0, details={"pattern": node.candlestick}, node_type="candlestick")
    return ConditionResult(
        passed=True,
        score=result["confidence"],
        details={"pattern": node.candlestick, "confidence": result["confidence"]},
        node_type="candlestick",
    )
```

### 4.4 Chart Pattern Evaluation

```python
async def _eval_chart_pattern(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
    df = await ctx.get(node.timeframe)
    if len(df) < 20:
        return ConditionResult(passed=False, score=0.0, details={}, node_type="chart_pattern")

    from core.sdk import Patterns
    results = Patterns.detect(df, [node.chart_pattern])
    if not results:
        return ConditionResult(passed=False, score=0.0, details={"pattern": node.chart_pattern}, node_type="chart_pattern")

    best = max(results, key=lambda r: r["confidence"])
    passed = best["confidence"] >= node.min_confidence
    return ConditionResult(
        passed=passed,
        score=best["confidence"] if passed else 0.0,
        details=best,
        node_type="chart_pattern",
    )
```

### 4.5 Volume Evaluation

```python
async def _eval_volume(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
    df = await ctx.get(node.timeframe)
    if len(df) < node.volume_period + 1:
        return ConditionResult(passed=False, score=0.0, details={}, node_type="volume")

    last_volume = df["volume"].iloc[-1]
    avg_volume = df["volume"].iloc[-(node.volume_period + 1):-1].mean()
    if avg_volume == 0:
        return ConditionResult(passed=False, score=0.0, details={"error": "zero_avg_volume"}, node_type="volume")

    ratio = last_volume / avg_volume
    passed = ratio >= node.volume_ratio
    score = min(1.0, (ratio - node.volume_ratio) / node.volume_ratio) if passed else 0.0
    return ConditionResult(
        passed=passed,
        score=round(score, 4),
        details={"volume_ratio": round(ratio, 2), "required": node.volume_ratio},
        node_type="volume",
    )
```

### 4.6 Trend Evaluation

```python
async def _eval_trend(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
    df = await ctx.get(node.timeframe)
    from core.sdk import Patterns
    result = Patterns.trend(df, window=node.trend_window)
    passed = result.direction == node.trend
    score = result.strength if passed else 0.0
    return ConditionResult(
        passed=passed,
        score=round(score, 4),
        details={"direction": result.direction, "strength": result.strength, "r_squared": result.r_squared},
        node_type="trend",
    )
```

### 4.7 Composite (AND/OR)

```python
async def _eval_composite(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
    child_results = [await self.evaluate(child, ctx) for child in node.children]

    if node.logic == "AND":
        passed = all(r.passed for r in child_results)
        score = sum(r.score for r in child_results) / len(child_results) if passed else 0.0
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
```

Note: each child dict in `details["children"]` includes `passed` and `score` fields so `conditions_passed` count can be derived correctly.

---

## 5. Signal Evaluation

### 5.1 SignalCondition — updated fields

```python
# scanner/signals/models.py
class SignalCondition(BaseModel):
    type: Literal[
        "candlestick_pattern", "chart_pattern", "volume_confirmation",
        "trend_context", "indicator", "crossover", "custom_activity",
    ]
    pattern: str | None = None
    indicator: str | None = None
    operator: str | None = None
    value: float | str | None = None
    params: dict[str, Any] = {}               # NEW — indicator-specific kwargs
    min_volume_ratio: float | None = None
    min_confidence: float | None = None        # NEW — for chart_pattern
    trend: str | None = None
    timeframe: str | None = None               # NEW — per-condition TF override
    # crossover-specific
    indicator_a: str | None = None             # NEW
    indicator_b: str | None = None             # NEW
    params_a: dict[str, Any] = {}              # NEW
    params_b: dict[str, Any] = {}              # NEW
    crossover: str | None = None               # NEW — "above" | "below"
```

### 5.2 `signal.timeframes` semantics

Every signal in `signals.yaml` has `timeframes: [15min, 1h, 1d]`. These mean:

**Advisory only.** The `timeframes` list declares which timeframes the signal is designed for. It does NOT cause the scanner to auto-run the signal on every listed timeframe. The scan's `default_timeframe` (from the API request) determines which timeframe is used unless individual conditions override with their own `timeframe` field.

The frontend uses `signal.timeframes` to show applicable TF badges on signal preset chips. If the user's `default_timeframe` is `1min` and the signal declares `timeframes: [1h, 1d]`, the UI shows a warning badge — the user can still run it, but the signal wasn't designed for that resolution.

Future enhancement: a `strict_timeframe_match` flag on the scan request that filters signals to only those matching the default TF.

### 5.3 SignalEvaluator

```python
# scanner/signals/evaluator.py
class SignalEvaluator:
    """Converts a SignalConfig to a ConditionNode tree and evaluates it."""

    def to_condition_tree(self, signal: SignalConfig) -> ConditionNode:
        """Map YAML condition types to ConditionNode leaf types."""
        children = []
        for cond in signal.conditions:
            if cond.type == "indicator":
                children.append(ConditionNode(
                    indicator=cond.indicator,
                    operator=cond.operator,
                    value=cond.value,
                    params=cond.params,
                    timeframe=cond.timeframe,
                ))
            elif cond.type == "crossover":
                children.append(ConditionNode(
                    crossover=cond.crossover,
                    indicator_a=cond.indicator_a,
                    indicator_b=cond.indicator_b,
                    params_a=cond.params_a,
                    params_b=cond.params_b,
                    timeframe=cond.timeframe,
                ))
            elif cond.type == "candlestick_pattern":
                children.append(ConditionNode(
                    candlestick=cond.pattern,
                    timeframe=cond.timeframe,
                ))
            elif cond.type == "chart_pattern":
                children.append(ConditionNode(
                    chart_pattern=cond.pattern,
                    min_confidence=cond.min_confidence or 0.5,
                    timeframe=cond.timeframe,
                ))
            elif cond.type == "volume_confirmation":
                children.append(ConditionNode(
                    volume_ratio=cond.min_volume_ratio or 1.5,
                    timeframe=cond.timeframe,
                ))
            elif cond.type == "trend_context":
                children.append(ConditionNode(
                    trend=cond.trend,
                    timeframe=cond.timeframe,
                ))
            elif cond.type == "custom_activity":
                # Reserved for future quant model integration. Skip for now.
                pass
        return ConditionNode(logic="AND", children=children)

    async def evaluate(
        self,
        signal: SignalConfig,
        ctx: DataContext,
        evaluator: ConditionEvaluator,
    ) -> SignalResult:
        tree = self.to_condition_tree(signal)
        result = await evaluator.evaluate(tree, ctx)
        # Count passed children from composite result details
        child_details = result.details.get("children", [])
        conditions_passed = sum(1 for c in child_details if c.get("passed", False))
        return SignalResult(
            signal_name=signal.name,
            passed=result.passed,
            score=result.score,
            conditions_passed=conditions_passed,
            conditions_total=len(signal.conditions),
            details=result.details,
            display=signal.display,
        )
```

### 5.4 SignalResult

```python
@dataclass
class SignalResult:
    signal_name: str
    passed: bool
    score: float
    conditions_passed: int
    conditions_total: int
    details: dict
    display: dict   # {"color": "#f23645", "icon": "▼", "strength_score": 4}
```

---

## 6. Scanner Engine v2

### 6.1 Concurrency control

Scanning 500 symbols with `asyncio.gather` would fire 500+ concurrent DB queries. QuestDB and psycopg2 will choke.

**Solution: `asyncio.Semaphore`** to cap concurrent symbol evaluations.

```python
SCANNER_MAX_CONCURRENT = 20  # configurable via settings
```

### 6.2 New run_async() method

```python
# scanner/engine.py  — replace run() entirely
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
    """Core async scan."""
    from scanner.signals.loader import load_signals
    from scanner.signals.evaluator import SignalEvaluator
    from scanner.evaluator import ConditionEvaluator, DataContext, ConditionNode

    all_signals = {s.name: s for s in load_signals()}
    requested_signals = [all_signals[n] for n in signals if n in all_signals]

    # Warn about unknown signal names
    unknown = set(signals) - set(all_signals)
    if unknown:
        log.warning("scanner_unknown_signals", names=list(unknown))

    sig_eval = SignalEvaluator()
    cond_eval = ConditionEvaluator()

    custom_tree: ConditionNode | None = None
    if custom_conditions:
        custom_tree = ConditionNode.from_dict(custom_conditions)

    symbols = universe[:max_symbols]
    results = []
    semaphore = asyncio.Semaphore(SCANNER_MAX_CONCURRENT)

    async def eval_symbol(symbol: str) -> ScanResult | None:
        async with semaphore:
            ctx = DataContext(
                symbol=symbol,
                default_tf=default_timeframe,
                fetch_fn=self._make_fetch_fn(lookback_days),
            )
            signal_results: dict[str, SignalResult] = {}
            for sig in requested_signals:
                try:
                    sr = await sig_eval.evaluate(sig, ctx, cond_eval)
                    signal_results[sig.name] = sr
                except Exception as exc:
                    log.warning("signal_eval_failed", signal=sig.name, symbol=symbol, error=str(exc))
                    # Signal evaluation failure = signal did not pass. Don't crash the whole scan.
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

            passes = self._apply_match_mode(match_mode, matched, signal_results, custom_passed, custom_tree)
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
```

### 6.3 `_apply_match_mode`

```python
def _apply_match_mode(
    self,
    mode: str,
    matched: list[str],
    signal_results: dict[str, SignalResult],
    custom_passed: bool,
    custom_tree: ConditionNode | None,
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
```

### 6.4 ConditionNode.from_dict

```python
@classmethod
def from_dict(cls, d: dict) -> ConditionNode:
    if "logic" in d:
        return cls(
            logic=d["logic"],
            children=[cls.from_dict(c) for c in d.get("conditions", [])],
        )
    node_type = d.get("type", "")
    if node_type == "indicator":
        return cls(indicator=d["indicator"], operator=d["operator"], value=d["value"],
                   params=d.get("params", {}), timeframe=d.get("timeframe"))
    if node_type == "crossover":
        return cls(crossover=d["crossover"],
                   indicator_a=d["indicator_a"], indicator_b=d["indicator_b"],
                   params_a=d.get("params_a", {}), params_b=d.get("params_b", {}),
                   timeframe=d.get("timeframe"))
    if node_type == "candlestick":
        return cls(candlestick=d["pattern"], timeframe=d.get("timeframe"))
    if node_type == "chart_pattern":
        return cls(chart_pattern=d["pattern"], min_confidence=d.get("min_confidence", 0.5),
                   timeframe=d.get("timeframe"))
    if node_type == "volume":
        return cls(volume_ratio=d["value"], volume_period=d.get("period", 20),
                   timeframe=d.get("timeframe"))
    if node_type == "trend":
        return cls(trend=d["value"], trend_window=d.get("period", 20),
                   timeframe=d.get("timeframe"))
    raise ValueError(f"Unknown condition type: {node_type!r}")
```

---

## 7. Indicator Registry Fixes

### 7.1 Missing indicators

The registry currently has: `rsi`, `macd`, `ema`, `vwap`, `bollinger_bands`, `atr`.

Missing but implemented in `technical/indicators/`: `sma`, `stochastic`, `cci`, `williams_r`, `obv`, `wma`, `supertrend`.

**Add all to registry.** Also add `get_indicator_by_name` passthrough to `core/sdk.py`.

### 7.2 YAML signals referencing non-existent indicators

Two signals reference indicators that don't exist:
- `ema_20_crosses_ema_50` — **convert this signal to use `crossover` condition type** instead of `indicator`.
- `price_vs_resistance` — **implement as new indicator** that returns `close / nearest_resistance`. Uses `find_support_resistance` from `technical/patterns/levels.py`.

Updated `signals.yaml`:

```yaml
  - name: ema_crossover_bullish
    category: entry
    direction: bullish
    timeframes: [1d]
    conditions:
      - type: crossover
        indicator_a: ema
        indicator_b: ema
        params_a: {period: 20}
        params_b: {period: 50}
        crossover: above
    severity: medium
    display:
      color: "#089981"
      icon: "✕"
      strength_score: 3

  - name: breakout_high_volume
    category: alert
    direction: any
    timeframes: [15min, 1h]
    conditions:
      - type: indicator
        indicator: price_vs_resistance
        operator: gt
        value: 1.0
      - type: volume_confirmation
        min_volume_ratio: 2.0
    severity: high
    display:
      color: "#f5a623"
      icon: "◉"
      strength_score: 5
```

`price_vs_resistance` implementation (new indicator):

```python
# technical/indicators/price.py (NEW file)
def price_vs_resistance(data: pd.DataFrame) -> pd.Series:
    """Returns ratio of close to nearest resistance level for each bar."""
    from technical.patterns.levels import find_support_resistance
    levels = find_support_resistance(data)
    resistance_levels = [l["price"] for l in levels if l["type"] == "resistance"]
    if not resistance_levels:
        return pd.Series([0.0] * len(data), index=data.index)
    # For each bar, ratio = close / nearest resistance above
    result = []
    for close in data["close"]:
        above = [r for r in resistance_levels if r >= close]
        if above:
            result.append(close / min(above))
        else:
            result.append(1.1)  # above all resistance
    return pd.Series(result, index=data.index)
```

Register in `registry.py` and expose via `core/sdk.py`.

### 7.3 `core/sdk.py` additions

```python
# Add to core/sdk.py

def get_indicator_by_name(name: str):
    """Passthrough to technical indicators registry. Used by ConditionEvaluator."""
    from technical.indicators.registry import get_indicator
    return get_indicator(name)

class Patterns:
    # ... existing methods ...

    @staticmethod
    def detect_candlestick(data: pd.DataFrame, pattern: str) -> dict | None:
        from technical.patterns.candlestick import detect_candlestick
        return detect_candlestick(data, pattern)
```

---

## 8. API Changes

### 8.1 POST /scanner/run — new contract

**Request:**
```json
{
  "universe": "nse_all",
  "max_symbols": 500,
  "default_timeframe": "1d",
  "signals": ["rsi_oversold_uptrend", "ema_crossover_bullish"],
  "custom_conditions": {
    "logic": "AND",
    "conditions": [
      {"type": "indicator", "indicator": "rsi", "operator": "lt", "value": 30, "params": {"period": 14}},
      {"type": "volume", "value": 1.5}
    ]
  },
  "match_mode": "any_signal"
}
```

`universe`: `"nse_all"` (fetch from DB) | `["RELIANCE", "TCS", ...]` (explicit list)

**Response:**
```json
{
  "symbols": ["RELIANCE", "TCS"],
  "results": [
    {
      "symbol": "RELIANCE",
      "overall_score": 0.82,
      "matched_signals": ["rsi_oversold_uptrend"],
      "signal_details": {
        "rsi_oversold_uptrend": {
          "passed": true,
          "score": 0.82,
          "conditions_passed": 2,
          "conditions_total": 2,
          "details": {"children": [{"passed": true, "rsi_value": 24.5}, {"passed": true, "direction": "up"}]},
          "display": {"color": "#089981", "icon": "▲", "strength_score": 3}
        }
      },
      "custom_passed": true
    }
  ],
  "total_scanned": 500,
  "matched": 2,
  "duration_ms": 4200
}
```

### 8.2 POST /scanner/evaluate — new endpoint

Evaluate a single symbol against a condition tree. Used by screener UI for live preview.

**Request:**
```json
{
  "symbol": "RELIANCE",
  "default_timeframe": "1d",
  "conditions": {
    "logic": "AND",
    "conditions": [
      {"type": "indicator", "indicator": "rsi", "operator": "lt", "value": 30, "params": {"period": 14}}
    ]
  }
}
```

**Response:**
```json
{
  "symbol": "RELIANCE",
  "passed": false,
  "score": 0.0,
  "details": {"children": [{"passed": false, "score": 0.0, "node_type": "indicator", "rsi_value": 52.3}]}
}
```

### 8.3 GET /scanner/signals — unchanged

Returns list of available signals from YAML. No change needed.

---

## 9. Candlestick Patterns

New file: `technical/patterns/candlestick.py`

### 9.1 Patterns

| Pattern | Bars needed | Detection logic |
|---------|-------------|-----------------|
| `bearish_engulfing` | 2 | prev bar green, curr bar red, curr body engulfs prev body |
| `bullish_engulfing` | 2 | prev bar red, curr bar green, curr body engulfs prev body |
| `hammer` | 1 | lower shadow ≥ 2× body, upper shadow ≤ 10% of body, close near high |
| `shooting_star` | 1 | upper shadow ≥ 2× body, lower shadow ≤ 10% of body, close near low |
| `doji` | 1 | abs(open - close) / (high - low) < 0.1 (body < 10% of range) |
| `morning_star` | 3 | bar1 bearish large, bar2 small body (gap down), bar3 bullish large |
| `evening_star` | 3 | bar1 bullish large, bar2 small body (gap up), bar3 bearish large |

### 9.2 API

```python
_CANDLESTICK_DETECTORS = {
    "bearish_engulfing": _detect_bearish_engulfing,
    "bullish_engulfing": _detect_bullish_engulfing,
    "hammer": _detect_hammer,
    "shooting_star": _detect_shooting_star,
    "doji": _detect_doji,
    "morning_star": _detect_morning_star,
    "evening_star": _detect_evening_star,
}

def detect_candlestick(df: pd.DataFrame, pattern: str) -> dict | None:
    """
    df: last N bars (3 is sufficient for all patterns).
    Returns {"confidence": float, "direction": str} or None if pattern not found.
    Raises ValueError if pattern name unknown.
    """
    if pattern not in _CANDLESTICK_DETECTORS:
        raise ValueError(f"Unknown candlestick pattern: {pattern!r}. Available: {list(_CANDLESTICK_DETECTORS)}")
    return _CANDLESTICK_DETECTORS[pattern](df)
```

Confidence scoring:
- `bearish_engulfing`: `min(curr_body / prev_body, 3.0) / 3.0` — ratio of how much bigger the engulfing body is, capped at 1.0 when 3× or more.
- `hammer/shooting_star`: `min(shadow_ratio / 3.0, 1.0)` — shadow_ratio = relevant shadow / body.
- `doji`: `1 - (body_pct / 0.1)` — tighter doji = higher confidence.
- `morning_star/evening_star`: `min((bar1_body + bar3_body) / (2 * avg_body), 1.0)`.

Also expose via `Patterns.detect_candlestick()` in `core/sdk.py` (see §7.3).

---

## 10. Frontend Screener

### 10.1 Store: filters.ts

Replace flat filters array with ConditionNode tree:

```typescript
// frontend/src/store/filters.ts
interface ConditionLeaf {
  id: string          // uuid for React key
  type: "indicator" | "crossover" | "candlestick" | "chart_pattern" | "volume" | "trend"
  // indicator
  indicator?: string
  operator?: string
  value?: number | string
  params?: Record<string, number | string>
  // crossover
  indicatorA?: string
  indicatorB?: string
  paramsA?: Record<string, number | string>
  paramsB?: Record<string, number | string>
  crossover?: "above" | "below"
  // candlestick/chart_pattern
  pattern?: string
  // volume
  volumeRatio?: number
  // trend
  trend?: string
  // shared
  timeframe?: string  // undefined = use scan default
}

interface ConditionGroup {
  id: string
  logic: "AND" | "OR"
  children: (ConditionLeaf | ConditionGroup)[]
}

interface FiltersStore {
  source: string
  defaultTimeframe: string
  signals: string[]         // selected YAML signal names
  customConditions: ConditionGroup | null
  matchMode: "any_signal" | "all_signals" | "custom_only" | "signals_and_custom"
  maxSymbols: number
  // actions
  setSource: (s: string) => void
  setDefaultTimeframe: (tf: string) => void
  toggleSignal: (name: string) => void
  setCustomConditions: (tree: ConditionGroup | null) => void
  setMatchMode: (mode: string) => void
  reset: () => void
}
```

### 10.2 ConditionBuilder.tsx

Replace current flat list with three sections:

**Section 1 — Signal Presets**
Chips from `GET /scanner/signals`. Click to toggle. Selected signals highlighted in blue. Each chip shows the signal's `display.icon` and `display.color`. If `default_timeframe` is not in `signal.timeframes`, chip shows a ⚠ badge.

**Section 2 — Custom Conditions**
Hierarchical AND/OR group builder:
- Root is always an AND/OR group
- Each row: `[type dropdown] [params...] [TF selector (optional)] [× remove]`
- Type dropdown: `Indicator | Crossover | Candlestick | Chart Pattern | Volume | Trend`
- Indicator row: `[indicator select] [operator select] [value input] [params inputs]`
- Crossover row: `[indicator A select] [params A] crosses [above/below] [indicator B select] [params B]`
- `+ Add Condition` button adds a leaf row
- `+ Add Group` button nests another AND/OR group
- TF selector: `default | 1min | 5min | 15min | 1h | 1d` (default = greyed out, uses scan default)

**Section 3 — Scan Config**
- Default timeframe selector
- Max symbols input
- Match mode: `any_signal | all_signals | custom_only | signals_and_custom`

### 10.3 ResultsTable.tsx

Add columns:
- **Matched Signals** — chip per matched signal using `display.color` and `display.icon` from signal config. E.g. `▲ RSI Oversold` in green.
- **Score** — existing strength dots driven by `overall_score * 5` (0.0–1.0 → 0–5 dots).
- **Expandable row** — click to expand; shows per-condition detail: `RSI: 24.5 ✓`, `Trend: UP ✓`, `Volume: 1.8× ✓`. Reads from `signal_details[name].details.children`.

Symbol column already navigates to `/chart/:symbol` on click.

---

## 11. Testing

### 11.1 Unit Tests — pure condition evaluation

`tests/unit/test_condition_evaluator.py`:

```python
# All tests use synthetic DataFrames — no real data needed
def make_ohlcv(closes: list[float], volumes: list[int] | None = None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "ts": pd.date_range("2026-01-01", periods=n, freq="1D"),
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low":  [c * 0.99 for c in closes],
        "close": closes,
        "volume": volumes or [100_000] * n,
        "symbol": ["TEST"] * n,
    })

# Test: RSI lt 30 — passes when RSI is low
# Test: RSI lt 30 — fails when RSI is high
# Test: indicator with custom params — ema with period=20 works, macd with fast/slow works
# Test: indicator with bad params — returns error detail, doesn't crash
# Test: EMA crossover above SMA — passes when EMA crosses above SMA on last bar
# Test: EMA crossover above SMA — fails when no cross
# Test: volume_ratio 1.5 — passes when volume spikes
# Test: volume_ratio — score is 0.0 at exact threshold, higher above
# Test: AND composite — passes only when all children pass
# Test: AND composite — details.children each have "passed" field
# Test: OR composite — passes when any child passes
# Test: trend up — passes when linear slope is positive
# Test: multi-TF — DataContext fetches correct TF per condition
# Test: DataContext cache — fetch_fn called once per (symbol, tf) even with multiple conditions
# Test: score formula — RSI=15 on lt 30 → score > RSI=25 on lt 30
```

`tests/unit/test_candlestick.py`:
```python
# Synthetic OHLCV for each pattern — one test per pattern
# Test bearish_engulfing: returns confidence > 0 when pattern present
# Test bearish_engulfing: returns None when not present
# Test all 7 patterns for presence/absence
# Test unknown pattern name raises ValueError
```

`tests/unit/test_signal_evaluator.py`:
```python
# Test: to_condition_tree correctly maps each SignalCondition type including crossover
# Test: evaluate returns SignalResult with correct conditions_passed count
# Test: signal with non-existent indicator — returns failed result, doesn't crash scan
```

### 11.2 Integration Tests

`tests/integration/test_scanner_api.py`:
```python
# POST /scanner/run with explicit symbol list (bypasses universe fetch)
# Verify response shape: symbols, results, total_scanned, matched, duration_ms
# POST /scanner/evaluate — verify single symbol result shape
# POST /scanner/evaluate — verify details include per-condition passed/score
# GET /scanner/signals — verify returns signal list from YAML
# POST /scanner/run with unknown signal name — still works, logs warning
```

Run: `make test`

---

## 12. What This Spec Does NOT Cover

- **Backtesting** — reuses `ConditionEvaluator` directly. ConditionNode trees built here are portable. Separate spec.
- **Quant Models** — will add `quant_model` leaf type to ConditionNode. Dispatcher added to ConditionEvaluator. Separate spec.
- **Pine Script integration** — deferred. Will add `pinescript` leaf type when scoped.
- **LLM NL→ConditionNode translation** — NL query translated to ConditionNode JSON by Claude. Separate task, reuses existing `llm/translator.py`.
- **Scheduled scanning (Temporal)** — `universe_scanner` workflow calls `Scanner.run_async()` directly. No changes to workflow code needed; activity config references signal names already.
- **Redis caching of scan results** — can be layered on top without changing evaluator. Deferred.

---

## 13. Success Criteria

- [ ] `POST /scanner/run` with `signals: ["rsi_oversold_uptrend"]` returns symbols where RSI < 30 and trend is up
- [ ] `POST /scanner/run` with `custom_conditions` evaluates correctly
- [ ] Multi-TF condition: RSI on 1h + trend on 1d evaluated from different OHLCV DataFrames (DataContext fetches both)
- [ ] Crossover condition: EMA 20 crosses above EMA 50 detected on last bar
- [ ] Screener frontend shows matched signal chips and score dots in results
- [ ] `POST /scanner/evaluate` returns per-condition details including indicator values and passed/score per child
- [ ] All 7 candlestick patterns detected correctly on synthetic data
- [ ] All registered indicators callable with custom params (period, fast/slow, etc.) — no TypeError
- [ ] Scanner run for 500 symbols with semaphore=20 completes without connection exhaustion
- [ ] Unknown signal names in request logged as warning, don't crash scan
- [ ] Signal evaluation failure for one symbol doesn't crash entire scan
- [ ] Unit tests pass: `make test`
- [ ] Scanner run for 50 symbols completes < 30s

---

## Appendix A: Issues Found in Spec Review (resolved)

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | No indicator-vs-indicator crossover | Added `crossover` leaf type (§3.1, §4.2) |
| 2 | HIGH | Hardcoded pandas_ta column names | Dynamic column resolution via prefix matching (§4.1) |
| 3 | MEDIUM | `period` kwarg crashes macd/vwap | Replaced with `params: dict` — indicator-specific (§3.1, §4.1) |
| 4 | MEDIUM | `ema()` requires period, no default | `params` passes through to function; empty = use default. `ema` has no default so `params` must include `period` — validated at eval time, returns error detail (§4.1) |
| 5 | HIGH | `fetch_fn` undefined; no TF-aware lookback | Defined `_make_fetch_fn` with `TF_LOOKBACK_CAP` (§3.4) |
| 6 | HIGH | 500 concurrent DB queries | `asyncio.Semaphore(20)` (§6.1, §6.2) |
| 7 | MEDIUM | `conditions_passed` always = total (truthy dict) | Child details now include `passed` field; count uses `c.get("passed", False)` (§4.7, §5.3) |
| 8 | MEDIUM | `signal.timeframes` semantics undefined | Defined as advisory-only; UI shows mismatch badge (§5.2) |
| 9 | LOW | YAML references non-existent indicators | `ema_crossover_bullish` → crossover type; `price_vs_resistance` → new indicator (§7.2) |
| 10 | MEDIUM | Score formula contradicts example | Rewrote with `SCORE_RANGE_FACTOR`, correct examples (§3.2) |
| 11 | LOW | Direct cross-module imports | All access through `core/sdk.py` passthrough (§2.2, §7.3) |
| 12 | LOW | `ScanResult` not defined | Defined explicitly (§3.3) |
