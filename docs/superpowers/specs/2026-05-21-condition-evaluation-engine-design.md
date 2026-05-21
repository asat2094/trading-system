# Condition Evaluation Engine — Design Spec

**Date:** 2026-05-21
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

### 2.2 New Files

```
backend/
  scanner/
    evaluator.py              # NEW — ConditionNode, ConditionEvaluator, DataContext, ConditionResult
    signals/
      evaluator.py            # NEW — SignalEvaluator wraps SignalConfig → ConditionNode tree
  technical/
    patterns/
      candlestick.py          # NEW — candlestick pattern detection (7 patterns)
```

### 2.3 Modified Files

```
backend/
  scanner/
    engine.py                 # Rewrite run() to use ConditionEvaluator
    signals/
      models.py               # Add timeframe field to SignalCondition
  api/routers/
    scanner.py                # New request/response format + POST /scanner/evaluate
frontend/src/
  components/Screener/
    ConditionBuilder.tsx      # Hierarchical AND/OR builder with per-condition TF
    ResultsTable.tsx          # Show signal match chips + score breakdown
  api/
    scanner.ts                # Updated request/response types
  store/
    filters.ts                # ConditionNode tree state
```

---

## 3. Data Structures

### 3.1 ConditionNode

```python
# scanner/evaluator.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class ConditionNode:
    # ── Composite node ──────────────────────────────────────────────────────
    logic: Literal["AND", "OR"] | None = None
    children: list[ConditionNode] = field(default_factory=list)

    # ── Leaf: indicator ─────────────────────────────────────────────────────
    # Covers: rsi, macd, ema, sma, vwap, atr, bb, stochastic, cci, obv
    # operator: "lt" | "gt" | "lte" | "gte" | "eq" | "cross_above" | "cross_below"
    # cross_above/cross_below: compares last two bars (t-1 was below/above, t is above/below)
    indicator: str | None = None          # e.g. "rsi"
    operator: str | None = None
    value: float | str | None = None
    period: int | None = None             # for ema(20), rsi(14) etc. — None = indicator default

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

    # ── Leaf: price ──────────────────────────────────────────────────────────
    # Direct price comparisons
    # e.g. close > ema_200 → use indicator leaf with operator="gt"
    # Reserved for future: price vs prev_high, price vs 52w_high, etc.

    # ── Shared: timeframe override ───────────────────────────────────────────
    # None = use the scan's default_timeframe
    timeframe: str | None = None
```

Rules:
- Node is a **composite** if `logic` is set and `children` is non-empty.
- Node is a **leaf** if exactly one of `indicator`, `candlestick`, `chart_pattern`, `volume_ratio`, `trend` is set.
- A node that is neither is invalid — `ConditionEvaluator.__init__` validates on construction.

### 3.2 ConditionResult

```python
@dataclass
class ConditionResult:
    passed: bool
    score: float          # 0.0–1.0 — strength of signal, not just bool
    details: dict         # {"rsi_value": 24.5} | {"pattern": "double_bottom", "confidence": 0.82}
    node_type: str        # "indicator" | "candlestick" | "chart_pattern" | "volume" | "trend" | "AND" | "OR"
```

**Score semantics:**
- Indicator `lt`/`gt`: normalized proximity to threshold. RSI=25 on `rsi lt 30` → score=1.0. RSI=29 → score=0.17. RSI=31 (failed) → score=0.0.
- Formula: `score = max(0, (threshold - value) / threshold)` for `lt`; inverse for `gt`.
- Pattern: `confidence` from detector mapped 0–1.
- Volume: `min(volume_ratio / required_ratio, 1.0)`.
- Trend: 1.0 if direction matches, 0.0 if not.
- AND composite: `mean(child scores)` if all passed, else 0.0.
- OR composite: `max(child scores)`.

### 3.3 DataContext

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

---

## 4. ConditionEvaluator

```python
class ConditionEvaluator:
    """Evaluates a ConditionNode tree against a DataContext. Pure logic — no I/O."""

    async def evaluate(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
        if node.logic:
            return await self._eval_composite(node, ctx)

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

        raise ValueError(f"Invalid ConditionNode: no type set")
```

### 4.1 Indicator Evaluation

```python
async def _eval_indicator(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
    df = await ctx.get(node.timeframe)
    if df.empty:
        return ConditionResult(passed=False, score=0.0, details={"error": "no_data"}, node_type="indicator")

    from technical.indicators.registry import get_indicator
    fn = get_indicator(node.indicator)

    # Pass period/params if specified
    kwargs = {}
    if node.period:
        # indicator functions accept 'period' kwarg
        kwargs["period"] = node.period

    series = fn(df, **kwargs)
    if series is None or (hasattr(series, 'empty') and series.empty):
        return ConditionResult(passed=False, score=0.0, details={"error": "indicator_empty"}, node_type="indicator")

    # For DataFrame indicators (macd, bb), extract relevant series
    value = self._extract_scalar(series, node.indicator, node.operator)

    passed, score = self._apply_operator(value, node.operator, node.value)
    return ConditionResult(
        passed=passed,
        score=score,
        details={f"{node.indicator}_value": round(value, 4)},
        node_type="indicator",
    )
```

`_extract_scalar` rules for multi-output indicators:
- `macd`: use `MACD_12_26_9` column (MACD line) for comparisons
- `bollinger_bands`: use `BBU_20_2.0` / `BBL_20_2.0` for `value="upper"/"lower"`, `BBM_20_2.0` for `"mid"`
- `stochastic`: use `STOCHk_14_3_3` (K line)
- All others: single Series, use last non-NaN value

`_apply_operator`:
- `lt`, `gt`, `lte`, `gte`, `eq`: standard comparisons
- `cross_above`: `prev_value < float(node.value)` AND `last_value >= float(node.value)` (use last 2 non-NaN values)
- `cross_below`: inverse

### 4.2 Candlestick Evaluation

```python
async def _eval_candlestick(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
    df = await ctx.get(node.timeframe)
    if len(df) < 3:
        return ConditionResult(passed=False, score=0.0, details={}, node_type="candlestick")

    from technical.patterns.candlestick import detect_candlestick
    result = detect_candlestick(df.tail(3), node.candlestick)
    if result is None:
        return ConditionResult(passed=False, score=0.0, details={"pattern": node.candlestick}, node_type="candlestick")
    return ConditionResult(
        passed=True,
        score=result["confidence"],
        details={"pattern": node.candlestick, "confidence": result["confidence"]},
        node_type="candlestick",
    )
```

### 4.3 Volume Evaluation

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
    score = min(ratio / node.volume_ratio, 1.0) if passed else 0.0
    return ConditionResult(
        passed=passed,
        score=score,
        details={"volume_ratio": round(ratio, 2), "required": node.volume_ratio},
        node_type="volume",
    )
```

### 4.4 Trend Evaluation

```python
async def _eval_trend(self, node: ConditionNode, ctx: DataContext) -> ConditionResult:
    df = await ctx.get(node.timeframe)
    from technical.trend import analyze_trend
    result = analyze_trend(df, window=node.trend_window)
    passed = result.direction == node.trend
    score = result.strength if passed else 0.0
    return ConditionResult(
        passed=passed,
        score=score,
        details={"direction": result.direction, "strength": result.strength, "r_squared": result.r_squared},
        node_type="trend",
    )
```

### 4.5 Composite (AND/OR)

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
        details={"children": [r.details for r in child_results]},
        node_type=node.logic,
    )
```

---

## 5. Signal Evaluation

### 5.1 SignalCondition — add timeframe field

```python
# scanner/signals/models.py
class SignalCondition(BaseModel):
    type: Literal[
        "candlestick_pattern", "volume_confirmation",
        "trend_context", "indicator", "custom_activity",
    ]
    pattern: str | None = None
    indicator: str | None = None
    operator: str | None = None
    value: float | str | None = None
    min_volume_ratio: float | None = None
    trend: str | None = None
    timeframe: str | None = None          # NEW — per-condition TF override
    period: int | None = None             # NEW — indicator period override
```

### 5.2 SignalEvaluator

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
                    period=cond.period,
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
            # custom_activity: reserved for future quant model integration
        return ConditionNode(logic="AND", children=children)

    async def evaluate(
        self,
        signal: SignalConfig,
        ctx: DataContext,
        evaluator: ConditionEvaluator,
    ) -> SignalResult:
        tree = self.to_condition_tree(signal)
        result = await evaluator.evaluate(tree, ctx)
        return SignalResult(
            signal_name=signal.name,
            passed=result.passed,
            score=result.score,
            conditions_passed=sum(1 for c in result.details.get("children", []) if c),
            conditions_total=len(signal.conditions),
            details=result.details,
            display=signal.display,
        )
```

### 5.3 SignalResult

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

### 6.1 New run() method

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
    """Core async scan. Called by run() which bridges sync→async."""
    from scanner.signals.loader import load_signals
    from scanner.signals.evaluator import SignalEvaluator
    from scanner.evaluator import ConditionEvaluator, DataContext, ConditionNode

    all_signals = {s.name: s for s in load_signals()}
    requested_signals = [all_signals[n] for n in signals if n in all_signals]
    sig_eval = SignalEvaluator()
    cond_eval = ConditionEvaluator()

    custom_tree: ConditionNode | None = None
    if custom_conditions:
        custom_tree = ConditionNode.from_dict(custom_conditions)

    symbols = universe[:max_symbols]
    results = []

    async def eval_symbol(symbol: str) -> ScanResult | None:
        ctx = DataContext(
            symbol=symbol,
            default_tf=default_timeframe,
            fetch_fn=self._make_fetch_fn(lookback_days),
        )
        signal_results: dict[str, SignalResult] = {}
        for sig in requested_signals:
            sr = await sig_eval.evaluate(sig, ctx, cond_eval)
            signal_results[sig.name] = sr

        custom_passed = True
        if custom_tree:
            cr = await cond_eval.evaluate(custom_tree, ctx)
            custom_passed = cr.passed

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

`match_mode` logic:
- `any_signal` — pass if any signal matched
- `all_signals` — pass if all requested signals matched
- `custom_only` — ignore signals, pass only if custom conditions passed
- `signals_and_custom` — all requested signals AND custom conditions must pass

### 6.2 ConditionNode.from_dict

For deserialization from API JSON:

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
                   period=d.get("period"), timeframe=d.get("timeframe"))
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

## 7. API Changes

### 7.1 POST /scanner/run — new contract

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
      {"type": "indicator", "indicator": "rsi", "operator": "lt", "value": 30},
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
          "details": {"rsi_value": 24.5},
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

### 7.2 POST /scanner/evaluate — new endpoint

Evaluate a single symbol against a condition tree. Used by screener UI for live preview.

**Request:**
```json
{
  "symbol": "RELIANCE",
  "default_timeframe": "1d",
  "conditions": {
    "logic": "AND",
    "conditions": [
      {"type": "indicator", "indicator": "rsi", "operator": "lt", "value": 30}
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
  "details": {"rsi_value": 52.3}
}
```

### 7.3 GET /scanner/signals — unchanged

Returns list of available signals from YAML. No change needed.

---

## 8. Candlestick Patterns

New file: `technical/patterns/candlestick.py`

### 8.1 Patterns

| Pattern | Bars needed | Detection logic |
|---------|-------------|-----------------|
| `bearish_engulfing` | 2 | prev bar green, curr bar red, curr body engulfs prev body |
| `bullish_engulfing` | 2 | prev bar red, curr bar green, curr body engulfs prev body |
| `hammer` | 1 | lower shadow ≥ 2× body, upper shadow ≤ 10% of body, close near high |
| `shooting_star` | 1 | upper shadow ≥ 2× body, lower shadow ≤ 10% of body, close near low |
| `doji` | 1 | abs(open - close) / (high - low) < 0.1 (body < 10% of range) |
| `morning_star` | 3 | bar1 bearish large, bar2 small body (gap down), bar3 bullish large |
| `evening_star` | 3 | bar1 bullish large, bar2 small body (gap up), bar3 bearish large |

### 8.2 API

```python
def detect_candlestick(df: pd.DataFrame, pattern: str) -> dict | None:
    """
    df: last N bars (3 is sufficient for all patterns).
    Returns {"confidence": float, "direction": str} or None if pattern not found.
    """
```

Confidence scoring:
- `bearish_engulfing`: `curr_body / prev_body` ratio, capped at 1.0
- `hammer/shooting_star`: `shadow_ratio / 3.0`, capped at 1.0
- `doji`: `1 - (body_pct / 0.1)` (tighter = higher confidence)
- `morning_star/evening_star`: `(bar1_body + bar3_body) / (2 * avg_body)`, capped at 1.0

Integrated into `technical/patterns/detector.py` — `_DETECTORS` dict updated to include all 7 candlestick patterns alongside existing chart patterns.

---

## 9. Frontend Screener

### 9.1 Store: filters.ts

Replace flat filters array with ConditionNode tree:

```typescript
// frontend/src/store/filters.ts
interface ConditionLeaf {
  id: string          // uuid for React key
  type: "indicator" | "candlestick" | "chart_pattern" | "volume" | "trend"
  // indicator
  indicator?: string
  operator?: string
  value?: number | string
  period?: number
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

### 9.2 ConditionBuilder.tsx

Replace current flat list with three sections:

**Section 1 — Signal Presets**
Chips from `GET /scanner/signals`. Click to toggle. Selected signals highlighted in blue.

**Section 2 — Custom Conditions**
Hierarchical AND/OR group builder:
- Root is always an AND/OR group
- Each row: `[type dropdown] [params...] [TF selector (optional)] [× remove]`
- `+ Add Condition` button adds a leaf row
- `+ Add Group` button nests another AND/OR group
- TF selector: `default | 1min | 5min | 15min | 1h | 1d` (default = greyed out, uses scan default)

**Section 3 — Scan Config**
- Default timeframe selector
- Max symbols input
- Match mode: `any_signal | all_signals | custom_only | signals_and_custom`

No changes to the Run Scan button or results layout wiring.

### 9.3 ResultsTable.tsx

Add columns:
- **Matched Signals** — chip per matched signal using `display.color` and `display.icon` from signal config. E.g. `▲ RSI Oversold` in green.
- **Score** — existing strength dots driven by `overall_score * 5` (0.0–1.0 → 0–5 dots).
- **Expandable row** — click to expand; shows per-condition detail: `RSI: 24.5 ✓`, `Trend: UP ✓`, `Volume: 1.8× ✓`.

Symbol column already navigates to `/chart/:symbol` on click.

---

## 10. Testing

### 10.1 Unit Tests — pure condition evaluation

`tests/unit/test_condition_evaluator.py`:

```python
# All tests use synthetic DataFrames — no real data needed
def make_ohlcv(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "ts": pd.date_range("2026-01-01", periods=n, freq="1D"),
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low":  [c * 0.99 for c in closes],
        "close": closes,
        "volume": [100_000] * n,
        "symbol": ["TEST"] * n,
    })

# Test: RSI lt 30 — passes when RSI is low
# Test: RSI lt 30 — fails when RSI is high
# Test: EMA cross_above — detects cross on last bar
# Test: volume_ratio 1.5 — passes when volume spikes
# Test: AND composite — passes only when all children pass
# Test: OR composite — passes when any child passes
# Test: trend up — passes when linear slope is positive
# Test: multi-TF — DataContext fetches correct TF per condition
# Test: DataContext cache — fetch_fn called once per (symbol, tf) even with multiple conditions
```

`tests/unit/test_candlestick.py`:
```python
# Synthetic OHLCV for each pattern — one test per pattern
# Test bearish_engulfing: returns confidence > 0 when pattern present
# Test bearish_engulfing: returns None when not present
# Test all 7 patterns for presence/absence
```

`tests/unit/test_signal_evaluator.py`:
```python
# Test: to_condition_tree correctly maps each SignalCondition type
# Test: evaluate returns SignalResult with correct conditions_passed count
```

### 10.2 Integration Tests

`tests/integration/test_scanner_api.py`:
```python
# POST /scanner/run with explicit symbol list (bypasses universe fetch)
# Verify response shape: symbols, results, total_scanned, matched, duration_ms
# POST /scanner/evaluate — verify single symbol result shape
# GET /scanner/signals — verify returns signal list from YAML
```

Run: `make test`

---

## 11. What This Spec Does NOT Cover

- **Backtesting** — reuses `ConditionEvaluator` directly. ConditionNode trees built here are portable. Separate spec.
- **Quant Models** — will add `quant_model` leaf type to ConditionNode. Dispatcher added to ConditionEvaluator. Separate spec.
- **Pine Script integration** — deferred. Will add `pinescript` leaf type when scoped.
- **LLM NL→ConditionNode translation** — NL query translated to ConditionNode JSON by Claude. Separate task, reuses existing `llm/translator.py`.
- **Scheduled scanning (Temporal)** — `universe_scanner` workflow calls `Scanner.run_async()` directly. No changes to workflow code needed; activity config references signal names already.
- **Redis caching of scan results** — can be layered on top without changing evaluator. Deferred.

---

## 12. Success Criteria

- [ ] `POST /scanner/run` with `signals: ["rsi_oversold_uptrend"]` returns symbols where RSI < 30 and trend is up
- [ ] `POST /scanner/run` with `custom_conditions` evaluates correctly
- [ ] Multi-TF condition: RSI on 1h + trend on 1d evaluated from different OHLCV DataFrames (DataContext fetches both)
- [ ] Screener frontend shows matched signal chips and score dots in results
- [ ] `POST /scanner/evaluate` returns per-condition details including indicator values
- [ ] All 7 candlestick patterns detected correctly on synthetic data
- [ ] Unit tests pass: `make test`
- [ ] Scanner run for 50 symbols completes < 30s
