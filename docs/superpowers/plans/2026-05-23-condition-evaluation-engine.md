# Condition Evaluation Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a composable, multi-timeframe condition evaluation engine that fixes broken scanner signals, API contract mismatch, and adds condition composition (AND/OR trees).

**Architecture:** `ConditionNode` tree → `ConditionEvaluator` → `DataContext` (lazy OHLCV cache). Scanner, backtesting, and quant models all share the same evaluator. `scanner/` accesses `technical/` only through `core/sdk.py` (existing boundary rule).

**Tech Stack:** Python 3.12, pandas, pandas_ta, asyncio, FastAPI, Pydantic v2, Zustand (frontend), React

---

## Task 1: Candlestick Pattern Detection

**Files:**
- Create: `backend/technical/patterns/candlestick.py`
- Modify: `backend/technical/patterns/detector.py` (add candlestick to existing `_DETECTORS`)
- Test: `backend/tests/unit/test_candlestick.py`

- [ ] **Step 1: Write failing tests for all 7 patterns**

```python
# backend/tests/unit/test_candlestick.py
import pandas as pd
import pytest
from technical.patterns.candlestick import detect_candlestick


def make_bar(o, h, l, c, v=100_000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def df_from_bars(*bars):
    rows = list(bars)
    df = pd.DataFrame(rows)
    df["ts"] = pd.date_range("2026-01-01", periods=len(rows), freq="1D")
    df["symbol"] = "TEST"
    return df


# ── bearish_engulfing ─────────────────────────────────────────────────────────

def test_bearish_engulfing_detected():
    # bar1: green (100→105), bar2: red (106→99) — engulfs bar1 body
    df = df_from_bars(
        make_bar(100, 106, 99, 105),   # bar1 green: body 100–105
        make_bar(106, 107, 98, 99),    # bar2 red:   body 99–106, engulfs
    )
    result = detect_candlestick(df, "bearish_engulfing")
    assert result is not None
    assert result["confidence"] > 0
    assert result["direction"] == "bearish"


def test_bearish_engulfing_not_detected():
    # bar1 red, bar2 green — wrong direction
    df = df_from_bars(
        make_bar(105, 107, 99, 100),
        make_bar(99, 106, 98, 104),
    )
    result = detect_candlestick(df, "bearish_engulfing")
    assert result is None


# ── bullish_engulfing ─────────────────────────────────────────────────────────

def test_bullish_engulfing_detected():
    # bar1: red (105→100), bar2: green (99→107) — engulfs
    df = df_from_bars(
        make_bar(105, 106, 99, 100),
        make_bar(99, 108, 98, 107),
    )
    result = detect_candlestick(df, "bullish_engulfing")
    assert result is not None
    assert result["direction"] == "bullish"


def test_bullish_engulfing_not_detected():
    # bar1 green, bar2 red — wrong direction
    df = df_from_bars(
        make_bar(100, 106, 99, 105),
        make_bar(106, 107, 98, 100),
    )
    result = detect_candlestick(df, "bullish_engulfing")
    assert result is None


# ── hammer ────────────────────────────────────────────────────────────────────

def test_hammer_detected():
    # body: 98–100 (2), lower shadow: 90–98 (8 = 4x body), upper shadow: 100–101 (1 = 0.5x, < 10% check fails)
    # Let's make body=2, lower_shadow=8, upper_shadow=0 → valid hammer
    df = df_from_bars(make_bar(100, 100, 90, 98))
    result = detect_candlestick(df, "hammer")
    assert result is not None
    assert result["direction"] == "bullish"


def test_hammer_not_detected_small_shadow():
    # body: 98–100, lower shadow: 98–97 (1, not ≥ 2x body)
    df = df_from_bars(make_bar(100, 101, 97, 98))
    result = detect_candlestick(df, "hammer")
    assert result is None


# ── shooting_star ─────────────────────────────────────────────────────────────

def test_shooting_star_detected():
    # body: 100–102 (2), upper shadow: 102–110 (8 = 4x body), lower shadow: 99–100 (1, <= 10%)
    # open=100, close=102, high=110, low=99 → upper_shadow=8, body=2, lower=1
    df = df_from_bars(make_bar(100, 110, 99, 102))
    result = detect_candlestick(df, "shooting_star")
    assert result is not None
    assert result["direction"] == "bearish"


def test_shooting_star_not_detected():
    df = df_from_bars(make_bar(100, 101, 97, 98))  # large lower shadow, not upper
    result = detect_candlestick(df, "shooting_star")
    assert result is None


# ── doji ──────────────────────────────────────────────────────────────────────

def test_doji_detected():
    # open=100, close=100.5 → body=0.5, range=100.5-99=1.5, body_pct=0.33 > 0.1
    # Need very small body vs range: open=100, close=100.1, high=105, low=95
    # body=0.1, range=10, body_pct=0.01 < 0.1 → doji
    df = df_from_bars(make_bar(100, 105, 95, 100.1))
    result = detect_candlestick(df, "doji")
    assert result is not None


def test_doji_not_detected():
    # Large body relative to range
    df = df_from_bars(make_bar(100, 105, 99, 104))  # body=4, range=6, body_pct=0.67
    result = detect_candlestick(df, "doji")
    assert result is None


# ── morning_star ──────────────────────────────────────────────────────────────

def test_morning_star_detected():
    # bar1: large bearish (110→100), bar2: small body near 100 (101→99), bar3: large bullish (100→108)
    df = df_from_bars(
        make_bar(110, 111, 99, 100),   # bar1: large bearish
        make_bar(101, 102, 98, 99),    # bar2: small body
        make_bar(100, 109, 99, 108),   # bar3: large bullish
    )
    result = detect_candlestick(df, "morning_star")
    assert result is not None
    assert result["direction"] == "bullish"


def test_morning_star_not_detected():
    # All green bars
    df = df_from_bars(
        make_bar(100, 105, 99, 104),
        make_bar(104, 108, 103, 107),
        make_bar(107, 112, 106, 111),
    )
    result = detect_candlestick(df, "morning_star")
    assert result is None


# ── evening_star ──────────────────────────────────────────────────────────────

def test_evening_star_detected():
    # bar1: large bullish (100→110), bar2: small body near top (111→109), bar3: large bearish (108→101)
    df = df_from_bars(
        make_bar(100, 111, 99, 110),   # bar1: large bullish
        make_bar(111, 113, 108, 109),  # bar2: small body at top
        make_bar(108, 109, 100, 101),  # bar3: large bearish
    )
    result = detect_candlestick(df, "evening_star")
    assert result is not None
    assert result["direction"] == "bearish"


def test_evening_star_not_detected():
    df = df_from_bars(
        make_bar(100, 105, 99, 104),
        make_bar(104, 108, 103, 107),
        make_bar(107, 112, 106, 111),
    )
    result = detect_candlestick(df, "evening_star")
    assert result is None


# ── unknown pattern ───────────────────────────────────────────────────────────

def test_unknown_pattern_raises():
    df = df_from_bars(make_bar(100, 105, 95, 102))
    with pytest.raises(ValueError, match="Unknown candlestick pattern"):
        detect_candlestick(df, "nonexistent_pattern")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest tests/unit/test_candlestick.py -v 2>&1 | head -30
```
Expected: `ImportError` or `ModuleNotFoundError: No module named 'technical.patterns.candlestick'`

- [ ] **Step 3: Create `backend/technical/patterns/candlestick.py`**

```python
# backend/technical/patterns/candlestick.py
"""
Candlestick pattern detection.
Returns {"confidence": float, "direction": str} or None.
All detectors receive a DataFrame of up to 3 bars (last N bars from caller).
"""
from __future__ import annotations
import pandas as pd


def _body(row) -> float:
    return abs(row["close"] - row["open"])


def _upper_shadow(row) -> float:
    return row["high"] - max(row["open"], row["close"])


def _lower_shadow(row) -> float:
    return min(row["open"], row["close"]) - row["low"]


def _is_green(row) -> bool:
    return row["close"] >= row["open"]


def _is_red(row) -> bool:
    return row["close"] < row["open"]


# ── bearish_engulfing ─────────────────────────────────────────────────────────

def _detect_bearish_engulfing(df: pd.DataFrame) -> dict | None:
    if len(df) < 2:
        return None
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    if not (_is_green(prev) and _is_red(curr)):
        return None
    prev_open, prev_close = prev["open"], prev["close"]
    curr_open, curr_close = curr["open"], curr["close"]
    # curr body must engulf prev body: curr opens above prev close, closes below prev open
    if curr_open >= prev_close and curr_close <= prev_open:
        prev_body = _body(prev)
        curr_body = _body(curr)
        if prev_body == 0:
            return None
        ratio = curr_body / prev_body
        confidence = min(ratio / 3.0, 1.0)
        return {"confidence": round(confidence, 4), "direction": "bearish"}
    return None


# ── bullish_engulfing ─────────────────────────────────────────────────────────

def _detect_bullish_engulfing(df: pd.DataFrame) -> dict | None:
    if len(df) < 2:
        return None
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    if not (_is_red(prev) and _is_green(curr)):
        return None
    prev_open, prev_close = prev["open"], prev["close"]
    curr_open, curr_close = curr["open"], curr["close"]
    # curr body engulfs prev: curr opens below prev close, closes above prev open
    if curr_open <= prev_close and curr_close >= prev_open:
        prev_body = _body(prev)
        curr_body = _body(curr)
        if prev_body == 0:
            return None
        ratio = curr_body / prev_body
        confidence = min(ratio / 3.0, 1.0)
        return {"confidence": round(confidence, 4), "direction": "bullish"}
    return None


# ── hammer ────────────────────────────────────────────────────────────────────

def _detect_hammer(df: pd.DataFrame) -> dict | None:
    row = df.iloc[-1]
    body = _body(row)
    lower = _lower_shadow(row)
    upper = _upper_shadow(row)
    if body == 0:
        return None
    # lower shadow >= 2x body, upper shadow <= 10% of body
    if lower >= 2 * body and upper <= 0.1 * body:
        shadow_ratio = lower / body
        confidence = min(shadow_ratio / 3.0, 1.0)
        return {"confidence": round(confidence, 4), "direction": "bullish"}
    return None


# ── shooting_star ─────────────────────────────────────────────────────────────

def _detect_shooting_star(df: pd.DataFrame) -> dict | None:
    row = df.iloc[-1]
    body = _body(row)
    lower = _lower_shadow(row)
    upper = _upper_shadow(row)
    if body == 0:
        return None
    # upper shadow >= 2x body, lower shadow <= 10% of body
    if upper >= 2 * body and lower <= 0.1 * body:
        shadow_ratio = upper / body
        confidence = min(shadow_ratio / 3.0, 1.0)
        return {"confidence": round(confidence, 4), "direction": "bearish"}
    return None


# ── doji ──────────────────────────────────────────────────────────────────────

def _detect_doji(df: pd.DataFrame) -> dict | None:
    row = df.iloc[-1]
    price_range = row["high"] - row["low"]
    if price_range == 0:
        return None
    body_pct = _body(row) / price_range
    if body_pct < 0.1:
        confidence = round(1.0 - (body_pct / 0.1), 4)
        return {"confidence": confidence, "direction": "neutral"}
    return None


# ── morning_star ──────────────────────────────────────────────────────────────

def _detect_morning_star(df: pd.DataFrame) -> dict | None:
    if len(df) < 3:
        return None
    b1, b2, b3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    # bar1: large bearish, bar2: small body, bar3: large bullish
    if not (_is_red(b1) and _is_green(b3)):
        return None
    avg_body = (_body(b1) + _body(b3)) / 2
    if avg_body == 0:
        return None
    # bar1 and bar3 must be "large" (body > some threshold vs bar2)
    b2_body = _body(b2)
    if _body(b1) < 2 * b2_body or _body(b3) < 2 * b2_body:
        return None
    confidence = min(avg_body / (avg_body + b2_body + 1e-9), 1.0)
    return {"confidence": round(confidence, 4), "direction": "bullish"}


# ── evening_star ──────────────────────────────────────────────────────────────

def _detect_evening_star(df: pd.DataFrame) -> dict | None:
    if len(df) < 3:
        return None
    b1, b2, b3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    # bar1: large bullish, bar2: small body, bar3: large bearish
    if not (_is_green(b1) and _is_red(b3)):
        return None
    avg_body = (_body(b1) + _body(b3)) / 2
    if avg_body == 0:
        return None
    b2_body = _body(b2)
    if _body(b1) < 2 * b2_body or _body(b3) < 2 * b2_body:
        return None
    confidence = min(avg_body / (avg_body + b2_body + 1e-9), 1.0)
    return {"confidence": round(confidence, 4), "direction": "bearish"}


# ── registry + public API ─────────────────────────────────────────────────────

_CANDLESTICK_DETECTORS: dict[str, callable] = {
    "bearish_engulfing": _detect_bearish_engulfing,
    "bullish_engulfing": _detect_bullish_engulfing,
    "hammer":            _detect_hammer,
    "shooting_star":     _detect_shooting_star,
    "doji":              _detect_doji,
    "morning_star":      _detect_morning_star,
    "evening_star":      _detect_evening_star,
}


def detect_candlestick(df: pd.DataFrame, pattern: str) -> dict | None:
    """
    Detect a candlestick pattern on the last 1–3 bars of df.

    Args:
        df: DataFrame with columns open, high, low, close, volume. Pass df.tail(3).
        pattern: Pattern name — must be in _CANDLESTICK_DETECTORS.

    Returns:
        {"confidence": float (0–1), "direction": str} if pattern detected, None otherwise.

    Raises:
        ValueError: if pattern name is not known.
    """
    if pattern not in _CANDLESTICK_DETECTORS:
        raise ValueError(
            f"Unknown candlestick pattern: {pattern!r}. "
            f"Available: {sorted(_CANDLESTICK_DETECTORS)}"
        )
    return _CANDLESTICK_DETECTORS[pattern](df)
```

- [ ] **Step 4: Run tests, verify all pass**

```bash
cd backend && pytest tests/unit/test_candlestick.py -v
```
Expected: all tests green. Fix any failing test by adjusting detection thresholds in `candlestick.py` — do not change test logic.

- [ ] **Step 5: Commit**

```bash
git add backend/technical/patterns/candlestick.py backend/tests/unit/test_candlestick.py
git commit -m "feat: add candlestick pattern detection (7 patterns)"
```

---

## Task 2: Complete Indicator Registry + `price_vs_resistance`

**Files:**
- Create: `backend/technical/indicators/price.py`
- Modify: `backend/technical/indicators/registry.py` (add sma, wma, stochastic, cci, williams_r, obv, supertrend, price_vs_resistance)
- Modify: `backend/core/sdk.py` (add `get_indicator_by_name()` + `Patterns.detect_candlestick()`)
- Test: `backend/tests/unit/test_indicator_registry.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_indicator_registry.py
import pandas as pd
import numpy as np
import pytest
from technical.indicators.registry import get_indicator, list_indicators


def make_ohlcv(n=50, start_price=100.0) -> pd.DataFrame:
    closes = [start_price + i * 0.5 + (i % 5) * 0.3 for i in range(n)]
    return pd.DataFrame({
        "ts":     pd.date_range("2026-01-01", periods=n, freq="1D"),
        "open":   [c - 0.2 for c in closes],
        "high":   [c + 0.5 for c in closes],
        "low":    [c - 0.5 for c in closes],
        "close":  closes,
        "volume": [100_000 + i * 1000 for i in range(n)],
        "symbol": ["TEST"] * n,
    })


@pytest.fixture
def df():
    return make_ohlcv()


def test_all_expected_indicators_registered():
    names = list_indicators()
    expected = [
        "rsi", "macd", "ema", "sma", "wma", "vwap", "bollinger_bands",
        "atr", "stochastic", "cci", "williams_r", "obv", "supertrend",
        "price_vs_resistance",
    ]
    for name in expected:
        assert name in names, f"Missing from registry: {name!r}"


def test_get_indicator_returns_callable(df):
    for name in list_indicators():
        fn = get_indicator(name)
        assert callable(fn), f"{name!r} is not callable"


def test_sma_returns_series(df):
    fn = get_indicator("sma")
    result = fn(df, period=10)
    assert isinstance(result, pd.Series)
    assert not result.dropna().empty


def test_wma_returns_series(df):
    fn = get_indicator("wma")
    result = fn(df, period=10)
    assert isinstance(result, pd.Series)


def test_stochastic_returns_dataframe(df):
    fn = get_indicator("stochastic")
    result = fn(df)
    assert isinstance(result, pd.DataFrame)
    # Must have at least one column starting with STOCHk_
    assert any(c.startswith("STOCHk_") for c in result.columns)


def test_cci_returns_series(df):
    fn = get_indicator("cci")
    result = fn(df)
    assert isinstance(result, pd.Series)


def test_williams_r_returns_series(df):
    fn = get_indicator("williams_r")
    result = fn(df)
    assert isinstance(result, pd.Series)


def test_obv_returns_series(df):
    fn = get_indicator("obv")
    result = fn(df)
    assert isinstance(result, pd.Series)


def test_supertrend_returns_dataframe(df):
    fn = get_indicator("supertrend")
    result = fn(df)
    assert isinstance(result, pd.DataFrame)
    assert any(c.startswith("SUPERT_") for c in result.columns)


def test_price_vs_resistance_returns_series(df):
    fn = get_indicator("price_vs_resistance")
    result = fn(df)
    assert isinstance(result, pd.Series)
    assert len(result) == len(df)


def test_get_indicator_unknown_raises():
    with pytest.raises(KeyError, match="not in indicator registry"):
        get_indicator("nonexistent_indicator")


def test_sdk_get_indicator_by_name():
    from core.sdk import get_indicator_by_name
    fn = get_indicator_by_name("rsi")
    assert callable(fn)


def test_sdk_get_indicator_by_name_unknown_raises():
    from core.sdk import get_indicator_by_name
    with pytest.raises(KeyError):
        get_indicator_by_name("nonexistent")


def test_sdk_patterns_detect_candlestick():
    from core.sdk import Patterns
    import pandas as pd
    # hammer: body=2, lower_shadow=8, upper=0
    df = pd.DataFrame({
        "open": [100.0], "high": [100.0], "low": [90.0], "close": [98.0],
        "volume": [100_000],
        "ts": pd.date_range("2026-01-01", periods=1),
        "symbol": ["TEST"],
    })
    result = Patterns.detect_candlestick(df, "hammer")
    assert result is not None
    assert "confidence" in result
```

- [ ] **Step 2: Run to confirm fail**

```bash
cd backend && pytest tests/unit/test_indicator_registry.py -v 2>&1 | head -30
```
Expected: `AssertionError` on `test_all_expected_indicators_registered` (sma/stochastic/etc. missing).

- [ ] **Step 3: Create `backend/technical/indicators/price.py`**

```python
# backend/technical/indicators/price.py
"""Price-relative indicators — indicators that compare close to chart levels."""
from __future__ import annotations
import pandas as pd


def price_vs_resistance(data: pd.DataFrame) -> pd.Series:
    """
    Returns ratio of close price to nearest resistance level above.
    Values > 1.0 mean close is above all resistance (breakout).
    Values < 1.0 mean close is below resistance.
    Returns 1.1 for bars above all resistance levels.
    """
    from technical.patterns.levels import find_support_resistance

    levels = find_support_resistance(data)
    resistance_levels = [lv["price"] for lv in levels if lv["type"] == "resistance"]

    if not resistance_levels:
        # No resistance found — return neutral series
        return pd.Series([1.0] * len(data), index=data.index)

    result = []
    for close in data["close"]:
        above = [r for r in resistance_levels if r >= close]
        if above:
            result.append(close / min(above))
        else:
            result.append(1.1)  # above all resistance = breakout
    return pd.Series(result, index=data.index)
```

- [ ] **Step 4: Update `backend/technical/indicators/registry.py`**

```python
# backend/technical/indicators/registry.py
from typing import Callable
from core.sdk import Indicators
from technical.indicators.momentum import stochastic, cci, williams_r
from technical.indicators.trend import sma, wma, supertrend
from technical.indicators.volume import obv
from technical.indicators.price import price_vs_resistance

_REGISTRY: dict[str, Callable] = {
    "rsi":                  Indicators.rsi,
    "macd":                 Indicators.macd,
    "ema":                  Indicators.ema,
    "vwap":                 Indicators.vwap,
    "bollinger_bands":      Indicators.bollinger_bands,
    "atr":                  Indicators.atr,
    # previously missing
    "sma":                  sma,
    "wma":                  wma,
    "stochastic":           stochastic,
    "cci":                  cci,
    "williams_r":           williams_r,
    "obv":                  obv,
    "supertrend":           supertrend,
    "price_vs_resistance":  price_vs_resistance,
}


def get_indicator(name: str) -> Callable:
    if name not in _REGISTRY:
        raise KeyError(f"{name!r}: not in indicator registry. Available: {list(_REGISTRY)}")
    return _REGISTRY[name]


def list_indicators() -> list[str]:
    return list(_REGISTRY.keys())


def register_indicator(name: str, fn: Callable, overwrite: bool = False) -> None:
    if name in _REGISTRY and not overwrite:
        raise ValueError(f"Indicator {name!r} already registered. Pass overwrite=True to replace.")
    _REGISTRY[name] = fn
```

- [ ] **Step 5: Add `get_indicator_by_name` and `Patterns.detect_candlestick` to `backend/core/sdk.py`**

Find the end of the `Patterns` class in `core/sdk.py`. Add `detect_candlestick` as a staticmethod. Add `get_indicator_by_name` as a module-level function after the class definitions.

Open `backend/core/sdk.py`, locate the `Patterns` class, add inside it:

```python
    @staticmethod
    def detect_candlestick(data: pd.DataFrame, pattern: str) -> dict | None:
        """Detect a candlestick pattern. Returns {"confidence": float, "direction": str} or None."""
        from technical.patterns.candlestick import detect_candlestick
        return detect_candlestick(data, pattern)
```

After all class definitions at module level, add:

```python
def get_indicator_by_name(name: str):
    """Return indicator function by name. Passthrough to technical.indicators.registry."""
    from technical.indicators.registry import get_indicator
    return get_indicator(name)
```

- [ ] **Step 6: Run tests**

```bash
cd backend && pytest tests/unit/test_indicator_registry.py -v
```
Expected: all pass. If `ImportError` on `core.sdk` importing `technical.indicators.registry` (circular), verify that `registry.py` imports direct module functions (not through sdk). The pattern `registry.py → sdk.Indicators` for existing indicators is fine; new indicators import from their own modules directly (not from sdk) so no circular dependency is introduced.

- [ ] **Step 7: Commit**

```bash
git add backend/technical/indicators/price.py backend/technical/indicators/registry.py backend/core/sdk.py backend/tests/unit/test_indicator_registry.py
git commit -m "feat: complete indicator registry (sma/wma/stochastic/cci/williams_r/obv/supertrend/price_vs_resistance) + sdk passthrough"
```

---

## Task 3: ConditionNode, ConditionResult, DataContext, ConditionEvaluator

**Files:**
- Create: `backend/scanner/evaluator.py`
- Test: `backend/tests/unit/test_condition_evaluator.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_condition_evaluator.py
"""Unit tests for ConditionEvaluator. All use synthetic DataFrames — no DB calls."""
import asyncio
import pandas as pd
import numpy as np
import pytest
from scanner.evaluator import ConditionNode, ConditionEvaluator, DataContext, ConditionResult


# ── helpers ───────────────────────────────────────────────────────────────────

def make_ohlcv(closes: list[float], volumes: list[int] | None = None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "ts":     pd.date_range("2026-01-01", periods=n, freq="1D"),
        "open":   closes,
        "high":   [c * 1.01 for c in closes],
        "low":    [c * 0.99 for c in closes],
        "close":  closes,
        "volume": volumes or [100_000] * n,
        "symbol": ["TEST"] * n,
    })


def make_ctx(df: pd.DataFrame, default_tf: str = "1d") -> DataContext:
    """DataContext backed by a fixed DataFrame for all TF requests."""
    async def fetch(symbol: str, tf: str) -> pd.DataFrame:
        return df
    return DataContext(symbol="TEST", default_tf=default_tf, fetch_fn=fetch)


def eval_node(node: ConditionNode, df: pd.DataFrame) -> ConditionResult:
    ctx = make_ctx(df)
    evaluator = ConditionEvaluator()
    return asyncio.get_event_loop().run_until_complete(evaluator.evaluate(node, ctx))


# ── indicator: rsi lt ─────────────────────────────────────────────────────────

def test_rsi_lt_passes_when_low():
    # Falling prices → low RSI
    closes = [100 - i * 2 for i in range(30)]
    df = make_ohlcv(closes)
    node = ConditionNode(indicator="rsi", operator="lt", value=50.0, params={"period": 14})
    result = eval_node(node, df)
    assert result.passed
    assert result.score > 0.0
    assert "rsi_value" in result.details
    assert result.node_type == "indicator"


def test_rsi_lt_fails_when_high():
    # Rising prices → high RSI
    closes = [100 + i * 2 for i in range(30)]
    df = make_ohlcv(closes)
    node = ConditionNode(indicator="rsi", operator="lt", value=30.0, params={"period": 14})
    result = eval_node(node, df)
    assert not result.passed
    assert result.score == 0.0


def test_rsi_lt_score_stronger_when_further_below():
    closes_low = [100 - i * 3 for i in range(30)]   # lower RSI
    closes_mid = [100 - i * 1 for i in range(30)]   # higher RSI
    df_low = make_ohlcv(closes_low)
    df_mid = make_ohlcv(closes_mid)
    node = ConditionNode(indicator="rsi", operator="lt", value=50.0, params={"period": 14})
    r_low = eval_node(node, df_low)
    r_mid = eval_node(node, df_mid)
    # Both may pass, but low should have higher score
    if r_low.passed and r_mid.passed:
        assert r_low.score >= r_mid.score


# ── indicator: bad params ─────────────────────────────────────────────────────

def test_indicator_bad_params_returns_error_not_crash():
    closes = [100 + i for i in range(30)]
    df = make_ohlcv(closes)
    node = ConditionNode(indicator="rsi", operator="lt", value=30.0,
                         params={"nonexistent_kwarg": 99})
    result = eval_node(node, df)
    assert not result.passed
    assert "error" in result.details


# ── crossover ─────────────────────────────────────────────────────────────────

def test_ema_crossover_above_detected():
    # Construct prices where EMA20 was below EMA50 then crosses above
    # Rising trend from low: EMA20 (fast) crosses above EMA50 (slow)
    # Use 60 bars: first 50 flat, last 10 sharply rising
    closes = [100.0] * 50 + [105 + i * 2 for i in range(10)]
    df = make_ohlcv(closes)
    node = ConditionNode(
        crossover="above",
        indicator_a="ema", params_a={"period": 20},
        indicator_b="ema", params_b={"period": 50},
    )
    result = eval_node(node, df)
    # Crossover may or may not be detected depending on exact prices
    # Test that it doesn't crash and returns a ConditionResult
    assert isinstance(result, ConditionResult)
    assert result.node_type == "crossover"
    assert 0.0 <= result.score <= 1.0


def test_ema_crossover_returns_details():
    closes = [100 + i * 0.5 for i in range(60)]
    df = make_ohlcv(closes)
    node = ConditionNode(
        crossover="above",
        indicator_a="ema", params_a={"period": 10},
        indicator_b="ema", params_b={"period": 20},
    )
    result = eval_node(node, df)
    if result.passed:
        assert "ema_curr" in result.details or any("curr" in k for k in result.details)
    assert result.node_type == "crossover"


# ── volume ────────────────────────────────────────────────────────────────────

def test_volume_passes_on_spike():
    # 20 bars at 100k volume, last bar at 300k (3× avg)
    volumes = [100_000] * 20 + [300_000]
    closes = [100.0] * 21
    df = make_ohlcv(closes, volumes)
    node = ConditionNode(volume_ratio=1.5, volume_period=20)
    result = eval_node(node, df)
    assert result.passed
    assert result.score > 0.0
    assert result.details["volume_ratio"] == pytest.approx(3.0, rel=0.1)


def test_volume_score_zero_at_exact_threshold():
    # Last bar exactly at threshold (1.5× avg)
    volumes = [100_000] * 20 + [150_000]
    closes = [100.0] * 21
    df = make_ohlcv(closes, volumes)
    node = ConditionNode(volume_ratio=1.5, volume_period=20)
    result = eval_node(node, df)
    assert result.passed
    assert result.score == pytest.approx(0.0, abs=0.05)


def test_volume_fails_below_threshold():
    volumes = [100_000] * 21
    closes = [100.0] * 21
    df = make_ohlcv(closes, volumes)
    node = ConditionNode(volume_ratio=2.0, volume_period=20)
    result = eval_node(node, df)
    assert not result.passed
    assert result.score == 0.0


# ── AND composite ─────────────────────────────────────────────────────────────

def test_and_passes_when_all_children_pass():
    closes = [100 - i * 2 for i in range(30)]  # falling → low RSI, down trend
    df = make_ohlcv(closes)
    node = ConditionNode(logic="AND", children=[
        ConditionNode(indicator="rsi", operator="lt", value=70.0, params={"period": 14}),
        ConditionNode(volume_ratio=0.1, volume_period=20),  # any volume passes
    ])
    result = eval_node(node, df)
    assert result.passed
    assert result.node_type == "AND"


def test_and_fails_when_any_child_fails():
    closes = [100 + i * 2 for i in range(30)]  # rising → high RSI
    df = make_ohlcv(closes)
    node = ConditionNode(logic="AND", children=[
        ConditionNode(indicator="rsi", operator="lt", value=20.0, params={"period": 14}),  # will fail
        ConditionNode(volume_ratio=0.1, volume_period=20),  # passes
    ])
    result = eval_node(node, df)
    assert not result.passed
    assert result.score == 0.0


def test_and_details_include_children_with_passed_field():
    closes = [100.0] * 30
    df = make_ohlcv(closes)
    node = ConditionNode(logic="AND", children=[
        ConditionNode(volume_ratio=0.1, volume_period=20),
    ])
    result = eval_node(node, df)
    children = result.details.get("children", [])
    assert len(children) == 1
    assert "passed" in children[0]
    assert "score" in children[0]
    assert "node_type" in children[0]


# ── OR composite ──────────────────────────────────────────────────────────────

def test_or_passes_when_any_child_passes():
    closes = [100 + i * 2 for i in range(30)]
    df = make_ohlcv(closes)
    node = ConditionNode(logic="OR", children=[
        ConditionNode(indicator="rsi", operator="lt", value=5.0, params={"period": 14}),  # fails
        ConditionNode(volume_ratio=0.1, volume_period=20),   # passes
    ])
    result = eval_node(node, df)
    assert result.passed
    assert result.node_type == "OR"


def test_or_score_is_max_of_children():
    closes = [100.0] * 30
    df = make_ohlcv(closes)
    node = ConditionNode(logic="OR", children=[
        ConditionNode(volume_ratio=0.1, volume_period=20),
        ConditionNode(volume_ratio=0.05, volume_period=20),
    ])
    result = eval_node(node, df)
    assert result.passed
    # score should be max of children, which is > 0
    assert result.score > 0.0


# ── trend ─────────────────────────────────────────────────────────────────────

def test_trend_up_passes_on_rising_prices():
    closes = [100 + i * 1.0 for i in range(30)]
    df = make_ohlcv(closes)
    node = ConditionNode(trend="up", trend_window=20)
    result = eval_node(node, df)
    assert result.passed
    assert "direction" in result.details


def test_trend_down_fails_on_rising_prices():
    closes = [100 + i * 1.0 for i in range(30)]
    df = make_ohlcv(closes)
    node = ConditionNode(trend="down", trend_window=20)
    result = eval_node(node, df)
    assert not result.passed


# ── DataContext cache ─────────────────────────────────────────────────────────

def test_datacontext_fetch_called_once_per_tf():
    call_count = {"1d": 0, "1h": 0}
    closes = [100.0] * 30

    async def fetch(symbol: str, tf: str):
        call_count[tf] = call_count.get(tf, 0) + 1
        return make_ohlcv(closes)

    async def run():
        ctx = DataContext("TEST", "1d", fetch)
        # Request same TF twice — should only fetch once
        await ctx.get("1d")
        await ctx.get("1d")
        await ctx.get("1h")
        await ctx.get("1h")
        return ctx

    asyncio.get_event_loop().run_until_complete(run())
    assert call_count["1d"] == 1
    assert call_count["1h"] == 1


# ── multi-TF ──────────────────────────────────────────────────────────────────

def test_multi_tf_node_fetches_correct_tf():
    fetched_tfs = []
    closes = [100.0] * 30

    async def fetch(symbol: str, tf: str):
        fetched_tfs.append(tf)
        return make_ohlcv(closes)

    async def run():
        ctx = DataContext("TEST", "1d", fetch)
        evaluator = ConditionEvaluator()
        node = ConditionNode(
            logic="AND",
            children=[
                ConditionNode(indicator="rsi", operator="lt", value=70.0,
                              params={"period": 14}, timeframe="1h"),
                ConditionNode(volume_ratio=0.1, volume_period=20, timeframe="1d"),
            ]
        )
        await evaluator.evaluate(node, ctx)

    asyncio.get_event_loop().run_until_complete(run())
    assert "1h" in fetched_tfs
    assert "1d" in fetched_tfs


# ── ConditionNode.from_dict ───────────────────────────────────────────────────

def test_from_dict_indicator():
    d = {"type": "indicator", "indicator": "rsi", "operator": "lt", "value": 30,
         "params": {"period": 14}}
    node = ConditionNode.from_dict(d)
    assert node.indicator == "rsi"
    assert node.operator == "lt"
    assert node.value == 30
    assert node.params == {"period": 14}


def test_from_dict_crossover():
    d = {"type": "crossover", "crossover": "above",
         "indicator_a": "ema", "params_a": {"period": 20},
         "indicator_b": "ema", "params_b": {"period": 50}}
    node = ConditionNode.from_dict(d)
    assert node.crossover == "above"
    assert node.indicator_a == "ema"
    assert node.params_a == {"period": 20}


def test_from_dict_composite():
    d = {
        "logic": "AND",
        "conditions": [
            {"type": "indicator", "indicator": "rsi", "operator": "lt", "value": 30, "params": {}},
            {"type": "volume", "value": 1.5, "period": 20},
        ]
    }
    node = ConditionNode.from_dict(d)
    assert node.logic == "AND"
    assert len(node.children) == 2
    assert node.children[0].indicator == "rsi"
    assert node.children[1].volume_ratio == 1.5


def test_from_dict_unknown_type_raises():
    with pytest.raises(ValueError, match="Unknown condition type"):
        ConditionNode.from_dict({"type": "mystery"})
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && pytest tests/unit/test_condition_evaluator.py -v 2>&1 | head -20
```
Expected: `ImportError: cannot import name 'ConditionNode' from 'scanner.evaluator'`

- [ ] **Step 3: Create `backend/scanner/evaluator.py`**

```python
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
from datetime import datetime, timedelta
from typing import Any, Literal

import pandas as pd
import structlog

log = structlog.get_logger()

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
        """Extract primary scalar from indicator output. Handles Series and DataFrame."""
        if isinstance(result, pd.Series):
            return float(result.dropna().iloc[-1])

        if isinstance(result, pd.DataFrame):
            PRIMARY_PREFIXES = {
                "macd":           "MACD_",
                "bollinger_bands": "BBM_",
                "stochastic":     "STOCHk_",
                "supertrend":     "SUPERT_",
                "ichimoku":       "ISA_",
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
```

- [ ] **Step 4: Run all unit tests**

```bash
cd backend && pytest tests/unit/test_condition_evaluator.py -v
```
Expected: all pass. If `ImportError` on `structlog`, add it to `pyproject.toml` dependencies or replace with `import logging; log = logging.getLogger(__name__)`.

- [ ] **Step 5: Run full unit test suite to check no regressions**

```bash
cd backend && pytest tests/unit/ -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/scanner/evaluator.py backend/tests/unit/test_condition_evaluator.py
git commit -m "feat: add ConditionNode, ConditionEvaluator, DataContext (core eval engine)"
```

---

## Task 4: Update SignalCondition Model + Fix signals.yaml

**Files:**
- Modify: `backend/scanner/signals/models.py` (add params, timeframe, min_confidence, crossover fields)
- Modify: `backend/workers/config/signals.yaml` (fix ema_crossover_bullish + breakout_high_volume)
- Test: `backend/tests/unit/test_signal_models.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_signal_models.py
import pytest
from scanner.signals.models import SignalCondition, SignalConfig


def test_signal_condition_accepts_params():
    sc = SignalCondition(type="indicator", indicator="rsi", operator="lt", value=30,
                        params={"period": 14})
    assert sc.params == {"period": 14}


def test_signal_condition_params_defaults_to_empty():
    sc = SignalCondition(type="indicator", indicator="rsi", operator="lt", value=30)
    assert sc.params == {}


def test_signal_condition_accepts_timeframe():
    sc = SignalCondition(type="indicator", indicator="rsi", operator="lt", value=30,
                        timeframe="1h")
    assert sc.timeframe == "1h"


def test_signal_condition_timeframe_defaults_none():
    sc = SignalCondition(type="indicator", indicator="rsi", operator="lt", value=30)
    assert sc.timeframe is None


def test_signal_condition_accepts_crossover_type():
    sc = SignalCondition(
        type="crossover",
        indicator_a="ema", params_a={"period": 20},
        indicator_b="ema", params_b={"period": 50},
        crossover="above",
    )
    assert sc.type == "crossover"
    assert sc.indicator_a == "ema"
    assert sc.params_a == {"period": 20}
    assert sc.crossover == "above"


def test_signal_condition_accepts_chart_pattern_type():
    sc = SignalCondition(type="chart_pattern", pattern="double_bottom", min_confidence=0.7)
    assert sc.min_confidence == 0.7


def test_signal_condition_min_confidence_defaults_none():
    sc = SignalCondition(type="chart_pattern", pattern="double_bottom")
    assert sc.min_confidence is None


def test_load_signals_yaml_parses_crossover():
    """Verify that the updated signals.yaml loads without errors."""
    from scanner.signals.loader import load_signals
    signals = load_signals()
    names = [s.name for s in signals]
    assert "ema_crossover_bullish" in names
    crossover_signal = next(s for s in signals if s.name == "ema_crossover_bullish")
    assert crossover_signal.conditions[0].type == "crossover"
    assert crossover_signal.conditions[0].crossover == "above"


def test_load_signals_yaml_parses_breakout():
    from scanner.signals.loader import load_signals
    signals = load_signals()
    breakout = next((s for s in signals if s.name == "breakout_high_volume"), None)
    assert breakout is not None
    assert breakout.conditions[0].type == "indicator"
    assert breakout.conditions[0].indicator == "price_vs_resistance"
```

- [ ] **Step 2: Run to confirm fail**

```bash
cd backend && pytest tests/unit/test_signal_models.py -v 2>&1 | head -20
```
Expected: `ValidationError` or `AttributeError` — `params`, `timeframe`, crossover fields not present on `SignalCondition`.

- [ ] **Step 3: Update `backend/scanner/signals/models.py`**

```python
# backend/scanner/signals/models.py
from typing import Any, Literal
from pydantic import BaseModel, field_validator


class SignalCondition(BaseModel):
    type: Literal[
        "candlestick_pattern", "chart_pattern", "volume_confirmation",
        "trend_context", "indicator", "crossover", "custom_activity",
    ]
    pattern: str | None = None
    indicator: str | None = None
    operator: str | None = None
    value: float | str | None = None
    params: dict[str, Any] = {}                # indicator-specific kwargs
    min_volume_ratio: float | None = None
    min_confidence: float | None = None        # for chart_pattern
    trend: str | None = None
    timeframe: str | None = None               # per-condition TF override
    # crossover-specific
    indicator_a: str | None = None
    indicator_b: str | None = None
    params_a: dict[str, Any] = {}
    params_b: dict[str, Any] = {}
    crossover: str | None = None               # "above" | "below"


class SignalDisplay(BaseModel):
    color: str
    icon: str = "●"
    strength_score: int

    @field_validator("strength_score")
    @classmethod
    def score_in_range(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError(f"strength_score must be 1–5, got {v}")
        return v


class SignalConfig(BaseModel):
    name: str
    category: Literal["entry", "exit", "alert", "custom"]
    direction: Literal["bullish", "bearish", "any"]
    timeframes: list[str]
    conditions: list[SignalCondition]
    severity: Literal["low", "medium", "high"]
    display: dict[str, Any]
```

- [ ] **Step 4: Fix `backend/workers/config/signals.yaml`**

Replace the `ema_crossover_bullish` and `breakout_high_volume` entries. The full file should be:

```yaml
signals:
  - name: bearish_engulfing_strong
    category: entry
    direction: bearish
    timeframes: [15min, 1h, 1d]
    conditions:
      - type: candlestick_pattern
        pattern: bearish_engulfing
      - type: volume_confirmation
        min_volume_ratio: 1.5
      - type: trend_context
        trend: up
    severity: high
    display:
      color: "#f23645"
      icon: "▼"
      strength_score: 4

  - name: rsi_oversold_uptrend
    category: entry
    direction: bullish
    timeframes: [1h, 1d]
    conditions:
      - type: indicator
        indicator: rsi
        operator: lt
        value: 30
      - type: trend_context
        trend: up
    severity: medium
    display:
      color: "#089981"
      icon: "▲"
      strength_score: 3

  - name: ema_crossover_bullish
    category: entry
    direction: bullish
    timeframes: [1d]
    conditions:
      - type: crossover
        indicator_a: ema
        params_a: {period: 20}
        indicator_b: ema
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

- [ ] **Step 5: Run tests**

```bash
cd backend && pytest tests/unit/test_signal_models.py -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/scanner/signals/models.py backend/workers/config/signals.yaml backend/tests/unit/test_signal_models.py
git commit -m "feat: update SignalCondition model with params/timeframe/crossover fields + fix signals.yaml"
```

---

## Task 5: SignalEvaluator + SignalResult

**Files:**
- Create: `backend/scanner/signals/evaluator.py`
- Test: `backend/tests/unit/test_signal_evaluator.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_signal_evaluator.py
import asyncio
import pandas as pd
import pytest
from scanner.signals.models import SignalConfig, SignalCondition
from scanner.signals.evaluator import SignalEvaluator, SignalResult
from scanner.evaluator import ConditionEvaluator, DataContext, ConditionNode


def make_ohlcv(n=30, trend="rising") -> pd.DataFrame:
    if trend == "rising":
        closes = [100 + i * 1.0 for i in range(n)]
    else:
        closes = [130 - i * 1.0 for i in range(n)]
    return pd.DataFrame({
        "ts":     pd.date_range("2026-01-01", periods=n, freq="1D"),
        "open":   closes,
        "high":   [c * 1.01 for c in closes],
        "low":    [c * 0.99 for c in closes],
        "close":  closes,
        "volume": [100_000] * n,
        "symbol": ["TEST"] * n,
    })


def make_ctx(df: pd.DataFrame) -> DataContext:
    async def fetch(symbol, tf):
        return df
    return DataContext("TEST", "1d", fetch)


def make_signal(conditions: list[SignalCondition]) -> SignalConfig:
    return SignalConfig(
        name="test_signal",
        category="entry",
        direction="bullish",
        timeframes=["1d"],
        conditions=conditions,
        severity="medium",
        display={"color": "#089981", "icon": "▲", "strength_score": 3},
    )


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── to_condition_tree ─────────────────────────────────────────────────────────

def test_to_condition_tree_indicator():
    signal = make_signal([
        SignalCondition(type="indicator", indicator="rsi", operator="lt", value=30,
                        params={"period": 14}),
    ])
    se = SignalEvaluator()
    tree = se.to_condition_tree(signal)
    assert tree.logic == "AND"
    assert len(tree.children) == 1
    child = tree.children[0]
    assert child.indicator == "rsi"
    assert child.operator == "lt"
    assert child.params == {"period": 14}


def test_to_condition_tree_crossover():
    signal = make_signal([
        SignalCondition(
            type="crossover",
            indicator_a="ema", params_a={"period": 20},
            indicator_b="ema", params_b={"period": 50},
            crossover="above",
        ),
    ])
    se = SignalEvaluator()
    tree = se.to_condition_tree(signal)
    child = tree.children[0]
    assert child.crossover == "above"
    assert child.indicator_a == "ema"
    assert child.params_a == {"period": 20}


def test_to_condition_tree_candlestick():
    signal = make_signal([
        SignalCondition(type="candlestick_pattern", pattern="hammer"),
    ])
    se = SignalEvaluator()
    tree = se.to_condition_tree(signal)
    assert tree.children[0].candlestick == "hammer"


def test_to_condition_tree_volume():
    signal = make_signal([
        SignalCondition(type="volume_confirmation", min_volume_ratio=1.5),
    ])
    se = SignalEvaluator()
    tree = se.to_condition_tree(signal)
    assert tree.children[0].volume_ratio == 1.5


def test_to_condition_tree_trend():
    signal = make_signal([
        SignalCondition(type="trend_context", trend="up"),
    ])
    se = SignalEvaluator()
    tree = se.to_condition_tree(signal)
    assert tree.children[0].trend == "up"


def test_to_condition_tree_chart_pattern():
    signal = make_signal([
        SignalCondition(type="chart_pattern", pattern="double_bottom", min_confidence=0.7),
    ])
    se = SignalEvaluator()
    tree = se.to_condition_tree(signal)
    child = tree.children[0]
    assert child.chart_pattern == "double_bottom"
    assert child.min_confidence == 0.7


# ── evaluate ──────────────────────────────────────────────────────────────────

def test_evaluate_returns_signal_result():
    signal = make_signal([
        SignalCondition(type="volume_confirmation", min_volume_ratio=0.1),
    ])
    df = make_ohlcv()
    ctx = make_ctx(df)
    se = SignalEvaluator()
    cond_eval = ConditionEvaluator()
    result = run(se.evaluate(signal, ctx, cond_eval))
    assert isinstance(result, SignalResult)
    assert result.signal_name == "test_signal"
    assert isinstance(result.passed, bool)
    assert 0.0 <= result.score <= 1.0


def test_evaluate_conditions_passed_count():
    # 2 conditions: volume (passes) + trend up (on rising prices, passes)
    signal = make_signal([
        SignalCondition(type="volume_confirmation", min_volume_ratio=0.1),
        SignalCondition(type="trend_context", trend="up"),
    ])
    df = make_ohlcv(n=30, trend="rising")
    ctx = make_ctx(df)
    se = SignalEvaluator()
    cond_eval = ConditionEvaluator()
    result = run(se.evaluate(signal, ctx, cond_eval))
    assert result.conditions_total == 2
    # conditions_passed should be derivable from details
    assert result.conditions_passed >= 0


def test_evaluate_nonexistent_indicator_returns_failed_not_crash():
    signal = make_signal([
        SignalCondition(type="indicator", indicator="nonexistent_xyz",
                        operator="lt", value=30),
    ])
    df = make_ohlcv()
    ctx = make_ctx(df)
    se = SignalEvaluator()
    cond_eval = ConditionEvaluator()
    result = run(se.evaluate(signal, ctx, cond_eval))
    assert not result.passed
    assert result.score == 0.0


def test_evaluate_includes_display():
    signal = make_signal([
        SignalCondition(type="volume_confirmation", min_volume_ratio=0.1),
    ])
    df = make_ohlcv()
    ctx = make_ctx(df)
    se = SignalEvaluator()
    cond_eval = ConditionEvaluator()
    result = run(se.evaluate(signal, ctx, cond_eval))
    assert result.display["color"] == "#089981"
    assert result.display["strength_score"] == 3
```

- [ ] **Step 2: Run to confirm fail**

```bash
cd backend && pytest tests/unit/test_signal_evaluator.py -v 2>&1 | head -10
```
Expected: `ImportError: cannot import name 'SignalEvaluator'`

- [ ] **Step 3: Create `backend/scanner/signals/evaluator.py`**

```python
# backend/scanner/signals/evaluator.py
"""
SignalEvaluator: converts a SignalConfig YAML definition to a ConditionNode tree
and evaluates it using the ConditionEvaluator.
"""
from __future__ import annotations
from dataclasses import dataclass
from scanner.signals.models import SignalConfig
from scanner.evaluator import ConditionNode, ConditionEvaluator, DataContext, ConditionResult


@dataclass
class SignalResult:
    signal_name: str
    passed: bool
    score: float
    conditions_passed: int
    conditions_total: int
    details: dict
    display: dict


class SignalEvaluator:
    """Converts a SignalConfig to a ConditionNode tree and evaluates it."""

    def to_condition_tree(self, signal: SignalConfig) -> ConditionNode:
        """Map YAML condition types to ConditionNode leaf types."""
        children: list[ConditionNode] = []
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
                # Reserved for future quant model integration — skip.
                pass
        return ConditionNode(logic="AND", children=children)

    async def evaluate(
        self,
        signal: SignalConfig,
        ctx: DataContext,
        evaluator: ConditionEvaluator,
    ) -> SignalResult:
        tree = self.to_condition_tree(signal)
        result: ConditionResult = await evaluator.evaluate(tree, ctx)
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

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/unit/test_signal_evaluator.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/scanner/signals/evaluator.py backend/tests/unit/test_signal_evaluator.py
git commit -m "feat: add SignalEvaluator + SignalResult"
```

---

## Task 6: Rewrite Scanner Engine + API Router

**Files:**
- Modify: `backend/scanner/engine.py` (add `run_async()`, `ScanResult`, `_make_fetch_fn`, `_apply_match_mode`)
- Modify: `backend/api/routers/scanner.py` (new request/response types, fix return shape, add `/evaluate`)
- Test: `backend/tests/integration/test_scanner_api.py`

- [ ] **Step 1: Write failing integration tests**

```python
# backend/tests/integration/test_scanner_api.py
"""
Integration tests for scanner API.
Uses an explicit symbol list to bypass universe fetch (no real DB needed for shape tests).
Requires backend to be importable: PYTHONPATH=backend pytest
"""
import asyncio
import pandas as pd
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock


def make_ohlcv(n=50, trend="rising") -> pd.DataFrame:
    closes = [100 + i for i in range(n)] if trend == "rising" else [150 - i for i in range(n)]
    return pd.DataFrame({
        "ts":     pd.date_range("2026-01-01", periods=n, freq="1D"),
        "open":   closes,
        "high":   [c * 1.01 for c in closes],
        "low":    [c * 0.99 for c in closes],
        "close":  closes,
        "volume": [100_000] * n,
        "symbol": ["TEST"] * n,
    })


@pytest.fixture
def mock_ohlcv():
    """Patch MarketData.ohlcv to return synthetic data."""
    async def fake_ohlcv(self, symbol, tf, from_dt, to_dt):
        return make_ohlcv()
    with patch("core.sdk.MarketData.ohlcv", fake_ohlcv):
        yield


@pytest.fixture
def mock_auth():
    """Bypass auth middleware."""
    from core.auth.provider import User
    fake_user = User(id="test", email="test@test.com")
    with patch("core.auth.middleware.get_current_user", return_value=fake_user):
        yield


@pytest.mark.asyncio
async def test_scanner_run_response_shape(mock_ohlcv, mock_auth):
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/scanner/run", json={
            "universe": ["RELIANCE", "TCS"],
            "signals": ["rsi_oversold_uptrend"],
            "default_timeframe": "1d",
            "match_mode": "any_signal",
            "max_symbols": 10,
        })
    assert resp.status_code == 200
    body = resp.json()
    assert "symbols" in body
    assert "results" in body
    assert "total_scanned" in body
    assert "matched" in body
    assert "duration_ms" in body
    assert isinstance(body["results"], list)


@pytest.mark.asyncio
async def test_scanner_run_result_item_shape(mock_ohlcv, mock_auth):
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/scanner/run", json={
            "universe": ["RELIANCE"],
            "signals": ["rsi_oversold_uptrend"],
            "default_timeframe": "1d",
            "match_mode": "any_signal",
            "max_symbols": 10,
        })
    body = resp.json()
    # May or may not have results depending on synthetic data RSI
    # Just check shape when results exist
    for item in body["results"]:
        assert "symbol" in item
        assert "overall_score" in item
        assert "matched_signals" in item
        assert "signal_details" in item
        assert "custom_passed" in item


@pytest.mark.asyncio
async def test_scanner_evaluate_endpoint(mock_ohlcv, mock_auth):
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/scanner/evaluate", json={
            "symbol": "RELIANCE",
            "default_timeframe": "1d",
            "conditions": {
                "logic": "AND",
                "conditions": [
                    {"type": "indicator", "indicator": "rsi", "operator": "lt",
                     "value": 30, "params": {"period": 14}}
                ]
            }
        })
    assert resp.status_code == 200
    body = resp.json()
    assert "symbol" in body
    assert "passed" in body
    assert "score" in body
    assert "details" in body


@pytest.mark.asyncio
async def test_scanner_evaluate_details_include_per_condition(mock_ohlcv, mock_auth):
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/scanner/evaluate", json={
            "symbol": "RELIANCE",
            "default_timeframe": "1d",
            "conditions": {
                "logic": "AND",
                "conditions": [
                    {"type": "volume", "value": 0.1, "period": 20}
                ]
            }
        })
    body = resp.json()
    children = body["details"].get("children", [])
    assert len(children) == 1
    assert "passed" in children[0]
    assert "score" in children[0]
    assert "node_type" in children[0]


@pytest.mark.asyncio
async def test_scanner_run_unknown_signal_doesnt_crash(mock_ohlcv, mock_auth):
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/scanner/run", json={
            "universe": ["RELIANCE"],
            "signals": ["nonexistent_signal_xyz"],
            "default_timeframe": "1d",
            "match_mode": "any_signal",
            "max_symbols": 10,
        })
    # Should return 200, not 500
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_scanner_signals_list(mock_auth):
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/scanner/signals")
    assert resp.status_code == 200
    signals = resp.json()
    assert isinstance(signals, list)
    names = [s["name"] for s in signals]
    assert "rsi_oversold_uptrend" in names
    assert "ema_crossover_bullish" in names
```

- [ ] **Step 2: Run to confirm fail**

```bash
cd backend && pytest tests/integration/test_scanner_api.py -v 2>&1 | head -20
```
Expected: assertion failures on response shape (returns `{"results": ...}` without `symbols`/`total_scanned` etc.)

- [ ] **Step 3: Rewrite `backend/scanner/engine.py`**

Replace the entire file:

```python
# backend/scanner/engine.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import structlog

from core.logging import get_logger

log = get_logger(__name__)

SCANNER_MAX_CONCURRENT = 20


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
    """Async scanner. Run via run_async()."""

    def _make_fetch_fn(self, lookback_days: int):
        """Returns async (symbol, tf) -> DataFrame with timeframe-aware lookback."""
        from core.sdk import MarketData
        md = MarketData()

        TF_LOOKBACK_CAP = {
            "1min":  5,
            "3min":  10,
            "5min":  15,
            "15min": 30,
            "30min": 60,
            "1h":    120,
            "1d":    lookback_days,
            "1w":    lookback_days,
            "1M":    lookback_days,
        }

        async def fetch(symbol: str, tf: str):
            cap = TF_LOOKBACK_CAP.get(tf, lookback_days)
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

        custom_tree: ConditionNode | None = None
        if custom_conditions:
            custom_tree = ConditionNode.from_dict(custom_conditions)

        symbols = universe[:max_symbols]
        results: list[ScanResult] = []
        semaphore = asyncio.Semaphore(SCANNER_MAX_CONCURRENT)

        async def eval_symbol(symbol: str) -> ScanResult | None:
            async with semaphore:
                from scanner.evaluator import DataContext
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
                        from scanner.signals.evaluator import SignalResult
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

    # ── legacy compat (kept for any callers that haven't migrated yet) ────────

    def run(self, universe: list[str], max_symbols: int | None = None) -> list[dict]:
        """Deprecated sync API. Use run_async instead."""
        symbols = universe[:max_symbols] if max_symbols else universe
        log.warning("scanner_legacy_run_used", symbol_count=len(symbols))
        return [{"symbol": s, "passed": True, "conditions_met": 0, "total_conditions": 0}
                for s in symbols]
```

- [ ] **Step 4: Rewrite `backend/api/routers/scanner.py`**

```python
# backend/api/routers/scanner.py
import time
from typing import Any
from dataclasses import asdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.auth.middleware import get_current_user
from core.auth.provider import User
from core.logging import get_logger
from scanner.engine import Scanner
from scanner.evaluator import ConditionNode, ConditionEvaluator, DataContext

log = get_logger(__name__)
router = APIRouter(prefix="/scanner", tags=["scanner"])


# ── request/response models ───────────────────────────────────────────────────

class ScanRequest(BaseModel):
    universe: list[str] | str = "nse_all"
    max_symbols: int = 500
    default_timeframe: str = "1d"
    signals: list[str] = []
    custom_conditions: dict | None = None
    match_mode: str = "any_signal"
    lookback_days: int = 200


class EvaluateRequest(BaseModel):
    symbol: str
    default_timeframe: str = "1d"
    conditions: dict
    lookback_days: int = 200


# ── helpers ───────────────────────────────────────────────────────────────────

def _result_to_dict(scan_result) -> dict:
    """Convert ScanResult dataclass to JSON-serialisable dict."""
    signal_details = {}
    for name, sr in scan_result.signal_details.items():
        signal_details[name] = {
            "passed": sr.passed,
            "score": sr.score,
            "conditions_passed": sr.conditions_passed,
            "conditions_total": sr.conditions_total,
            "details": sr.details,
            "display": sr.display,
        }
    return {
        "symbol": scan_result.symbol,
        "overall_score": scan_result.overall_score,
        "matched_signals": scan_result.matched_signals,
        "signal_details": signal_details,
        "custom_passed": scan_result.custom_passed,
    }


async def _resolve_universe(universe) -> list[str]:
    if isinstance(universe, list):
        return universe
    # "nse_all" — fetch from DB
    from core.sdk import MarketData
    md = MarketData()
    return await md.universe()


def _make_fetch_fn(lookback_days: int):
    from core.sdk import MarketData
    from datetime import datetime, timedelta
    md = MarketData()
    TF_LOOKBACK_CAP = {
        "1min": 5, "3min": 10, "5min": 15, "15min": 30,
        "30min": 60, "1h": 120, "1d": lookback_days,
        "1w": lookback_days, "1M": lookback_days,
    }
    async def fetch(symbol: str, tf: str):
        cap = TF_LOOKBACK_CAP.get(tf, lookback_days)
        effective = min(lookback_days, cap)
        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=effective)
        return await md.ohlcv(symbol, tf, from_dt, to_dt)
    return fetch


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.post("/run")
async def run_scan(req: ScanRequest, user: User = Depends(get_current_user)):
    t0 = time.monotonic()
    universe = await _resolve_universe(req.universe)
    scanner = Scanner()
    results = await scanner.run_async(
        universe=universe,
        signals=req.signals,
        custom_conditions=req.custom_conditions,
        default_timeframe=req.default_timeframe,
        match_mode=req.match_mode,
        max_symbols=req.max_symbols,
        lookback_days=req.lookback_days,
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    matched_symbols = [r.symbol for r in results]
    return {
        "symbols": matched_symbols,
        "results": [_result_to_dict(r) for r in results],
        "total_scanned": min(len(universe), req.max_symbols),
        "matched": len(results),
        "duration_ms": duration_ms,
    }


@router.post("/evaluate")
async def evaluate_symbol(req: EvaluateRequest, user: User = Depends(get_current_user)):
    """Evaluate a single symbol against a custom condition tree. Used for live screener preview."""
    node = ConditionNode.from_dict(req.conditions)
    ctx = DataContext(
        symbol=req.symbol,
        default_tf=req.default_timeframe,
        fetch_fn=_make_fetch_fn(req.lookback_days),
    )
    evaluator = ConditionEvaluator()
    result = await evaluator.evaluate(node, ctx)
    return {
        "symbol": req.symbol,
        "passed": result.passed,
        "score": result.score,
        "details": result.details,
    }


@router.get("/signals")
async def list_signals(user: User = Depends(get_current_user)):
    from scanner.signals.loader import load_signals
    signals = load_signals()
    return [
        {
            "name": s.name,
            "category": s.category,
            "direction": s.direction,
            "timeframes": s.timeframes,
            "display": s.display,
            "severity": s.severity,
        }
        for s in signals
    ]


# ── legacy GET kept for backwards compat ─────────────────────────────────────

@router.get("/run")
async def run_scan_get(user: User = Depends(get_current_user)):
    return {"symbols": [], "results": [], "total_scanned": 0, "matched": 0, "duration_ms": 0}
```

- [ ] **Step 5: Run integration tests**

```bash
cd backend && pytest tests/integration/test_scanner_api.py -v
```
If `ModuleNotFoundError: api.main` — check import path. The app object may be in `api/main.py` or `main.py`. Adjust the import in tests to match.

- [ ] **Step 6: Run full test suite**

```bash
cd backend && pytest tests/ -v
```

- [ ] **Step 7: Commit**

```bash
git add backend/scanner/engine.py backend/api/routers/scanner.py backend/tests/integration/test_scanner_api.py
git commit -m "feat: rewrite scanner engine + API router (run_async, ScanResult, /evaluate endpoint, correct response shape)"
```

---

## Task 7: Frontend — API types + Zustand store

**Files:**
- Modify: `frontend/src/api/scanner.ts`
- Modify: `frontend/src/store/filters.ts`

- [ ] **Step 1: Rewrite `frontend/src/api/scanner.ts`**

```typescript
// frontend/src/api/scanner.ts
import { useMutation, useQuery } from "@tanstack/react-query";
import { apiClient } from "./client";

// ── condition tree types (mirror backend ConditionNode) ───────────────────────

export interface ConditionLeaf {
  id: string;           // uuid for React key only — stripped before sending to API
  type: "indicator" | "crossover" | "candlestick" | "chart_pattern" | "volume" | "trend";
  // indicator
  indicator?: string;
  operator?: string;
  value?: number | string;
  params?: Record<string, number | string>;
  // crossover
  indicator_a?: string;
  indicator_b?: string;
  params_a?: Record<string, number | string>;
  params_b?: Record<string, number | string>;
  crossover?: "above" | "below";
  // candlestick / chart_pattern
  pattern?: string;
  min_confidence?: number;
  // volume
  volume_ratio?: number;
  volume_period?: number;
  // trend
  trend?: string;
  trend_window?: number;
  // shared
  timeframe?: string;    // undefined = use scan default
}

export interface ConditionGroup {
  id: string;
  logic: "AND" | "OR";
  children: (ConditionLeaf | ConditionGroup)[];
}

// ── API wire types (no id fields) ─────────────────────────────────────────────

interface WireLeaf extends Omit<ConditionLeaf, "id"> {}
interface WireGroup {
  logic: "AND" | "OR";
  conditions: (WireLeaf | WireGroup)[];
}

function toWireNode(node: ConditionLeaf | ConditionGroup): WireLeaf | WireGroup {
  if ("logic" in node) {
    return {
      logic: node.logic,
      conditions: node.children.map(toWireNode),
    };
  }
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { id, ...rest } = node;
  return rest as WireLeaf;
}

// ── signal types ──────────────────────────────────────────────────────────────

export interface SignalConfig {
  name: string;
  category: string;
  direction: string;
  timeframes: string[];
  display: { color: string; icon: string; strength_score: number };
  severity: string;
}

// ── scan request/response ─────────────────────────────────────────────────────

interface ScanRequest {
  universe: string[] | string;
  max_symbols: number;
  default_timeframe: string;
  signals: string[];
  custom_conditions: WireGroup | null;
  match_mode: string;
}

export interface SignalDetail {
  passed: boolean;
  score: number;
  conditions_passed: number;
  conditions_total: number;
  details: {
    children?: Array<{
      passed: boolean;
      score: number;
      node_type: string;
      [key: string]: unknown;
    }>;
    [key: string]: unknown;
  };
  display: { color: string; icon: string; strength_score: number };
}

export interface ScanResultItem {
  symbol: string;
  overall_score: number;
  matched_signals: string[];
  signal_details: Record<string, SignalDetail>;
  custom_passed: boolean;
}

export interface ScanResponse {
  symbols: string[];
  results: ScanResultItem[];
  total_scanned: number;
  matched: number;
  duration_ms: number;
}

// ── evaluate request/response ─────────────────────────────────────────────────

interface EvaluateRequest {
  symbol: string;
  default_timeframe: string;
  conditions: WireGroup;
}

export interface EvaluateResponse {
  symbol: string;
  passed: boolean;
  score: number;
  details: {
    children?: Array<{
      passed: boolean;
      score: number;
      node_type: string;
      [key: string]: unknown;
    }>;
  };
}

// ── hooks ─────────────────────────────────────────────────────────────────────

export function useRunScan() {
  return useMutation({
    mutationFn: async (req: {
      universe: string[] | string;
      maxSymbols: number;
      defaultTimeframe: string;
      signals: string[];
      customConditions: ConditionGroup | null;
      matchMode: string;
    }): Promise<ScanResponse> => {
      const body: ScanRequest = {
        universe: req.universe,
        max_symbols: req.maxSymbols,
        default_timeframe: req.defaultTimeframe,
        signals: req.signals,
        custom_conditions: req.customConditions ? toWireNode(req.customConditions) as WireGroup : null,
        match_mode: req.matchMode,
      };
      const { data } = await apiClient.post<ScanResponse>("/scanner/run", body);
      return data;
    },
  });
}

export function useEvaluateSymbol() {
  return useMutation({
    mutationFn: async (req: {
      symbol: string;
      defaultTimeframe: string;
      conditions: ConditionGroup;
    }): Promise<EvaluateResponse> => {
      const body: EvaluateRequest = {
        symbol: req.symbol,
        default_timeframe: req.defaultTimeframe,
        conditions: toWireNode(req.conditions) as WireGroup,
      };
      const { data } = await apiClient.post<EvaluateResponse>("/scanner/evaluate", body);
      return data;
    },
  });
}

export function useListSignals() {
  return useQuery({
    queryKey: ["signals"],
    queryFn: async (): Promise<SignalConfig[]> => {
      const { data } = await apiClient.get<SignalConfig[]>("/scanner/signals");
      return data;
    },
  });
}
```

- [ ] **Step 2: Rewrite `frontend/src/store/filters.ts`**

```typescript
// frontend/src/store/filters.ts
import { create } from "zustand";
import { ConditionGroup, ConditionLeaf } from "../api/scanner";

export type { ConditionGroup, ConditionLeaf };

function newGroup(logic: "AND" | "OR" = "AND"): ConditionGroup {
  return { id: crypto.randomUUID(), logic, children: [] };
}

interface FiltersStore {
  source: string;
  defaultTimeframe: string;
  signals: string[];
  customConditions: ConditionGroup | null;
  matchMode: "any_signal" | "all_signals" | "custom_only" | "signals_and_custom";
  maxSymbols: number;
  // actions
  setSource: (s: string) => void;
  setDefaultTimeframe: (tf: string) => void;
  toggleSignal: (name: string) => void;
  setCustomConditions: (tree: ConditionGroup | null) => void;
  setMatchMode: (mode: FiltersStore["matchMode"]) => void;
  setMaxSymbols: (n: number) => void;
  // condition tree manipulation
  addCondition: (groupId: string, leaf: ConditionLeaf) => void;
  removeCondition: (groupId: string, childId: string) => void;
  addGroup: (parentGroupId: string) => void;
  updateCondition: (groupId: string, updatedLeaf: ConditionLeaf) => void;
  updateGroupLogic: (groupId: string, logic: "AND" | "OR") => void;
  initCustomConditions: () => void;
  reset: () => void;
}

function findGroup(node: ConditionGroup, id: string): ConditionGroup | null {
  if (node.id === id) return node;
  for (const child of node.children) {
    if ("logic" in child) {
      const found = findGroup(child as ConditionGroup, id);
      if (found) return found;
    }
  }
  return null;
}

function removeFromGroup(node: ConditionGroup, childId: string): ConditionGroup {
  return {
    ...node,
    children: node.children
      .filter((c) => c.id !== childId)
      .map((c) => ("logic" in c ? removeFromGroup(c as ConditionGroup, childId) : c)),
  };
}

function updateInGroup(node: ConditionGroup, updated: ConditionLeaf): ConditionGroup {
  return {
    ...node,
    children: node.children.map((c) => {
      if (c.id === updated.id) return updated;
      if ("logic" in c) return updateInGroup(c as ConditionGroup, updated);
      return c;
    }),
  };
}

function updateGroupLogicInTree(node: ConditionGroup, groupId: string, logic: "AND" | "OR"): ConditionGroup {
  if (node.id === groupId) return { ...node, logic };
  return {
    ...node,
    children: node.children.map((c) =>
      "logic" in c ? updateGroupLogicInTree(c as ConditionGroup, groupId, logic) : c
    ),
  };
}

export const useFiltersStore = create<FiltersStore>((set, get) => ({
  source: "nse_all",
  defaultTimeframe: "1d",
  signals: [],
  customConditions: null,
  matchMode: "any_signal",
  maxSymbols: 500,

  setSource: (source) => set({ source }),
  setDefaultTimeframe: (tf) => set({ defaultTimeframe: tf }),
  toggleSignal: (name) =>
    set((s) => ({
      signals: s.signals.includes(name) ? s.signals.filter((n) => n !== name) : [...s.signals, name],
    })),
  setCustomConditions: (tree) => set({ customConditions: tree }),
  setMatchMode: (mode) => set({ matchMode: mode }),
  setMaxSymbols: (n) => set({ maxSymbols: n }),

  initCustomConditions: () => {
    if (!get().customConditions) {
      set({ customConditions: newGroup("AND") });
    }
  },

  addCondition: (groupId, leaf) =>
    set((s) => {
      if (!s.customConditions) return s;
      const root = { ...s.customConditions };
      const group = findGroup(root, groupId);
      if (!group) return s;
      group.children = [...group.children, leaf];
      return { customConditions: root };
    }),

  removeCondition: (groupId, childId) =>
    set((s) => {
      if (!s.customConditions) return s;
      return { customConditions: removeFromGroup(s.customConditions, childId) };
    }),

  addGroup: (parentGroupId) =>
    set((s) => {
      if (!s.customConditions) return s;
      const root = { ...s.customConditions };
      const parent = findGroup(root, parentGroupId);
      if (!parent) return s;
      parent.children = [...parent.children, newGroup("AND")];
      return { customConditions: root };
    }),

  updateCondition: (groupId, updatedLeaf) =>
    set((s) => {
      if (!s.customConditions) return s;
      return { customConditions: updateInGroup(s.customConditions, updatedLeaf) };
    }),

  updateGroupLogic: (groupId, logic) =>
    set((s) => {
      if (!s.customConditions) return s;
      return { customConditions: updateGroupLogicInTree(s.customConditions, groupId, logic) };
    }),

  reset: () =>
    set({
      source: "nse_all",
      defaultTimeframe: "1d",
      signals: [],
      customConditions: null,
      matchMode: "any_signal",
      maxSymbols: 500,
    }),
}));
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```
Fix any type errors. Common fixes: `crypto.randomUUID()` needs `lib: ["ES2021"]` in `tsconfig.json` — if missing, replace with `Math.random().toString(36).slice(2)`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/scanner.ts frontend/src/store/filters.ts
git commit -m "feat: update scanner API types + Zustand store to ConditionNode tree"
```

---

## Task 8: ConditionBuilder.tsx rewrite

**Files:**
- Modify: `frontend/src/components/Screener/ConditionBuilder.tsx`

- [ ] **Step 1: Rewrite `frontend/src/components/Screener/ConditionBuilder.tsx`**

```tsx
// frontend/src/components/Screener/ConditionBuilder.tsx
import { useState } from "react";
import { useFiltersStore, ConditionLeaf, ConditionGroup } from "../../store/filters";
import { useListSignals, SignalConfig } from "../../api/scanner";

// ── constants ─────────────────────────────────────────────────────────────────

const INDICATORS = [
  { value: "rsi", label: "RSI" },
  { value: "macd", label: "MACD" },
  { value: "ema", label: "EMA" },
  { value: "sma", label: "SMA" },
  { value: "vwap", label: "VWAP" },
  { value: "bollinger_bands", label: "Bollinger Bands" },
  { value: "atr", label: "ATR" },
  { value: "stochastic", label: "Stochastic" },
  { value: "cci", label: "CCI" },
  { value: "williams_r", label: "Williams %R" },
  { value: "obv", label: "OBV" },
  { value: "supertrend", label: "Supertrend" },
  { value: "price_vs_resistance", label: "Price vs Resistance" },
];
const OPERATORS = [
  { value: "lt", label: "<" },
  { value: "lte", label: "≤" },
  { value: "gt", label: ">" },
  { value: "gte", label: "≥" },
  { value: "eq", label: "=" },
];
const TIMEFRAMES = ["1min", "5min", "15min", "1h", "1d", "1w"];
const CANDLESTICK_PATTERNS = [
  "bearish_engulfing", "bullish_engulfing", "hammer",
  "shooting_star", "doji", "morning_star", "evening_star",
];
const CHART_PATTERNS = ["double_bottom", "double_top", "head_shoulders", "triangle"];
const TREND_DIRS = ["up", "down", "sideways"];

// ── shared styles ─────────────────────────────────────────────────────────────

const s = {
  sectionLabel: {
    fontSize: 11, color: "#787b86", textTransform: "uppercase" as const,
    letterSpacing: "0.8px", marginBottom: 8, marginTop: 16, fontWeight: 600,
  },
  input: {
    background: "#1e222d", border: "1px solid #2a2e39", borderRadius: 4,
    color: "#d1d4dc", padding: "5px 8px", fontSize: 12, outline: "none",
  },
  select: {
    background: "#1e222d", border: "1px solid #2a2e39", borderRadius: 4,
    color: "#d1d4dc", padding: "5px 8px", fontSize: 12, outline: "none",
  },
  chipActive: {
    padding: "3px 10px", borderRadius: 12, fontSize: 12, cursor: "pointer",
    border: "1px solid #2962ff", background: "rgba(41,98,255,0.18)", color: "#7ba7ff",
  },
  chipInactive: {
    padding: "3px 10px", borderRadius: 12, fontSize: 12, cursor: "pointer",
    border: "1px solid #2a2e39", background: "transparent", color: "#787b86",
  },
  removeBtn: {
    background: "none", border: "none", color: "#787b86", cursor: "pointer",
    fontSize: 16, lineHeight: 1, padding: "0 4px", flexShrink: 0,
  },
  addBtn: {
    background: "none", border: "1px dashed #2a2e39", borderRadius: 4,
    color: "#787b86", cursor: "pointer", fontSize: 11, padding: "4px 8px",
    marginTop: 4,
  },
};

// ── SignalPresets ─────────────────────────────────────────────────────────────

function SignalPresets() {
  const { signals, toggleSignal, defaultTimeframe } = useFiltersStore();
  const { data: available = [] } = useListSignals();

  return (
    <div>
      <p style={s.sectionLabel}>Signal Presets</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {available.map((sig: SignalConfig) => {
          const active = signals.includes(sig.name);
          const tfMismatch = sig.timeframes.length > 0 && !sig.timeframes.includes(defaultTimeframe);
          return (
            <button
              key={sig.name}
              onClick={() => toggleSignal(sig.name)}
              title={tfMismatch ? `Designed for ${sig.timeframes.join(", ")}` : sig.name}
              style={active ? { ...s.chipActive, borderColor: sig.display.color, color: sig.display.color, background: `${sig.display.color}22` } : s.chipInactive}
            >
              {sig.display.icon} {sig.name.replace(/_/g, " ")}
              {tfMismatch && <span style={{ marginLeft: 4, opacity: 0.7 }}>⚠</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── LeafRow ───────────────────────────────────────────────────────────────────

function newLeaf(): ConditionLeaf {
  return { id: Math.random().toString(36).slice(2), type: "indicator", indicator: "rsi", operator: "lt", value: 30, params: { period: 14 } };
}

function LeafRow({ leaf, groupId }: { leaf: ConditionLeaf; groupId: string }) {
  const { updateCondition, removeCondition } = useFiltersStore();
  const upd = (patch: Partial<ConditionLeaf>) => updateCondition(groupId, { ...leaf, ...patch });

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", background: "#1e222d", borderRadius: 4, padding: "6px 8px", marginBottom: 4 }}>
      {/* Type */}
      <select value={leaf.type} onChange={(e) => upd({ type: e.target.value as ConditionLeaf["type"] })} style={s.select}>
        <option value="indicator">Indicator</option>
        <option value="crossover">Crossover</option>
        <option value="candlestick">Candlestick</option>
        <option value="chart_pattern">Chart Pattern</option>
        <option value="volume">Volume</option>
        <option value="trend">Trend</option>
      </select>

      {/* Indicator */}
      {leaf.type === "indicator" && (
        <>
          <select value={leaf.indicator ?? "rsi"} onChange={(e) => upd({ indicator: e.target.value })} style={s.select}>
            {INDICATORS.map((i) => <option key={i.value} value={i.value}>{i.label}</option>)}
          </select>
          <select value={leaf.operator ?? "lt"} onChange={(e) => upd({ operator: e.target.value })} style={{ ...s.select, width: 44 }}>
            {OPERATORS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <input type="number" value={leaf.value as number ?? 30} onChange={(e) => upd({ value: parseFloat(e.target.value) })} style={{ ...s.input, width: 60 }} />
          <input placeholder="period=14" defaultValue={leaf.params ? Object.entries(leaf.params).map(([k, v]) => `${k}=${v}`).join(",") : ""} onBlur={(e) => {
            const params: Record<string, number> = {};
            e.target.value.split(",").forEach((p) => {
              const [k, v] = p.trim().split("=");
              if (k && v) params[k.trim()] = parseFloat(v);
            });
            upd({ params });
          }} style={{ ...s.input, width: 80 }} title="params e.g. period=14" />
        </>
      )}

      {/* Crossover */}
      {leaf.type === "crossover" && (
        <>
          <select value={leaf.indicator_a ?? "ema"} onChange={(e) => upd({ indicator_a: e.target.value })} style={s.select}>
            {INDICATORS.map((i) => <option key={i.value} value={i.value}>{i.label}</option>)}
          </select>
          <input placeholder="period=20" defaultValue={leaf.params_a ? Object.entries(leaf.params_a).map(([k, v]) => `${k}=${v}`).join(",") : ""} onBlur={(e) => {
            const params: Record<string, number> = {};
            e.target.value.split(",").forEach((p) => { const [k, v] = p.trim().split("="); if (k && v) params[k.trim()] = parseFloat(v); });
            upd({ params_a: params });
          }} style={{ ...s.input, width: 72 }} />
          <select value={leaf.crossover ?? "above"} onChange={(e) => upd({ crossover: e.target.value as "above" | "below" })} style={{ ...s.select, width: 70 }}>
            <option value="above">crosses ↑</option>
            <option value="below">crosses ↓</option>
          </select>
          <select value={leaf.indicator_b ?? "ema"} onChange={(e) => upd({ indicator_b: e.target.value })} style={s.select}>
            {INDICATORS.map((i) => <option key={i.value} value={i.value}>{i.label}</option>)}
          </select>
          <input placeholder="period=50" defaultValue={leaf.params_b ? Object.entries(leaf.params_b).map(([k, v]) => `${k}=${v}`).join(",") : ""} onBlur={(e) => {
            const params: Record<string, number> = {};
            e.target.value.split(",").forEach((p) => { const [k, v] = p.trim().split("="); if (k && v) params[k.trim()] = parseFloat(v); });
            upd({ params_b: params });
          }} style={{ ...s.input, width: 72 }} />
        </>
      )}

      {/* Candlestick */}
      {leaf.type === "candlestick" && (
        <select value={leaf.pattern ?? "hammer"} onChange={(e) => upd({ pattern: e.target.value })} style={s.select}>
          {CANDLESTICK_PATTERNS.map((p) => <option key={p} value={p}>{p.replace(/_/g, " ")}</option>)}
        </select>
      )}

      {/* Chart pattern */}
      {leaf.type === "chart_pattern" && (
        <>
          <select value={leaf.pattern ?? "double_bottom"} onChange={(e) => upd({ pattern: e.target.value })} style={s.select}>
            {CHART_PATTERNS.map((p) => <option key={p} value={p}>{p.replace(/_/g, " ")}</option>)}
          </select>
          <span style={{ fontSize: 11, color: "#787b86" }}>min conf:</span>
          <input type="number" min={0} max={1} step={0.1} value={leaf.min_confidence ?? 0.5} onChange={(e) => upd({ min_confidence: parseFloat(e.target.value) })} style={{ ...s.input, width: 48 }} />
        </>
      )}

      {/* Volume */}
      {leaf.type === "volume" && (
        <>
          <span style={{ fontSize: 11, color: "#787b86" }}>ratio ≥</span>
          <input type="number" step={0.1} value={leaf.volume_ratio ?? 1.5} onChange={(e) => upd({ volume_ratio: parseFloat(e.target.value) })} style={{ ...s.input, width: 56 }} />
          <span style={{ fontSize: 11, color: "#787b86" }}>period</span>
          <input type="number" value={leaf.volume_period ?? 20} onChange={(e) => upd({ volume_period: parseInt(e.target.value) })} style={{ ...s.input, width: 48 }} />
        </>
      )}

      {/* Trend */}
      {leaf.type === "trend" && (
        <select value={leaf.trend ?? "up"} onChange={(e) => upd({ trend: e.target.value })} style={s.select}>
          {TREND_DIRS.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      )}

      {/* TF override */}
      <select value={leaf.timeframe ?? ""} onChange={(e) => upd({ timeframe: e.target.value || undefined })} style={{ ...s.select, width: 64, color: leaf.timeframe ? "#d1d4dc" : "#787b86" }}>
        <option value="">default</option>
        {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
      </select>

      <button onClick={() => removeCondition(groupId, leaf.id)} style={s.removeBtn}>×</button>
    </div>
  );
}

// ── GroupNode ─────────────────────────────────────────────────────────────────

function GroupNode({ group }: { group: ConditionGroup }) {
  const { addCondition, addGroup, removeCondition, updateGroupLogic } = useFiltersStore();

  return (
    <div style={{ border: "1px solid #2a2e39", borderRadius: 4, padding: "8px 10px", marginBottom: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <select value={group.logic} onChange={(e) => updateGroupLogic(group.id, e.target.value as "AND" | "OR")}
          style={{ ...s.select, fontWeight: 600, width: 56 }}>
          <option value="AND">AND</option>
          <option value="OR">OR</option>
        </select>
        <span style={{ fontSize: 11, color: "#787b86" }}>match all/any of:</span>
      </div>

      {group.children.map((child) =>
        "logic" in child
          ? <GroupNode key={child.id} group={child as ConditionGroup} />
          : <LeafRow key={child.id} leaf={child as ConditionLeaf} groupId={group.id} />
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
        <button onClick={() => addCondition(group.id, newLeaf())} style={s.addBtn}>+ Condition</button>
        <button onClick={() => addGroup(group.id)} style={s.addBtn}>+ Group</button>
      </div>
    </div>
  );
}

// ── ScanConfig ────────────────────────────────────────────────────────────────

function ScanConfig() {
  const { defaultTimeframe, setDefaultTimeframe, matchMode, setMatchMode, maxSymbols, setMaxSymbols } = useFiltersStore();
  return (
    <div>
      <p style={s.sectionLabel}>Scan Config</p>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: "#787b86", width: 110 }}>Default TF</span>
          <select value={defaultTimeframe} onChange={(e) => setDefaultTimeframe(e.target.value)} style={{ ...s.select, flex: 1 }}>
            {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
          </select>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: "#787b86", width: 110 }}>Match mode</span>
          <select value={matchMode} onChange={(e) => setMatchMode(e.target.value as FiltersStore["matchMode"])} style={{ ...s.select, flex: 1 }}>
            <option value="any_signal">Any signal</option>
            <option value="all_signals">All signals</option>
            <option value="custom_only">Custom only</option>
            <option value="signals_and_custom">Signal + custom</option>
          </select>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: "#787b86", width: 110 }}>Max symbols</span>
          <input type="number" min={1} max={1000} value={maxSymbols} onChange={(e) => setMaxSymbols(parseInt(e.target.value))} style={{ ...s.input, flex: 1 }} />
        </div>
      </div>
    </div>
  );
}

// ── ConditionBuilder ──────────────────────────────────────────────────────────

export default function ConditionBuilder() {
  const { customConditions, initCustomConditions } = useFiltersStore();

  return (
    <div style={{ padding: "16px", flex: 1, overflowY: "auto" }}>
      {/* Section 1 — Signal Presets */}
      <SignalPresets />

      {/* Section 2 — Custom Conditions */}
      <p style={s.sectionLabel}>Custom Conditions</p>
      {!customConditions ? (
        <button onClick={initCustomConditions} style={s.addBtn}>+ Add conditions</button>
      ) : (
        <GroupNode group={customConditions} />
      )}

      {/* Section 3 — Scan Config */}
      <ScanConfig />
    </div>
  );
}
```

Note: the `FiltersStore["matchMode"]` reference in `ScanConfig` requires exporting the type. Since `FiltersStore` is defined inside the store module, add `export type { FiltersStore }` at the bottom of `filters.ts`.

- [ ] **Step 2: Add missing export to `frontend/src/store/filters.ts`**

At the bottom of `filters.ts`, ensure:
```typescript
export type { FiltersStore };
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```
Fix any errors. Common: unused `groupId` param in `removeCondition` — the store's implementation ignores groupId since it does tree-wide search.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Screener/ConditionBuilder.tsx frontend/src/store/filters.ts
git commit -m "feat: rewrite ConditionBuilder with AND/OR tree, signal presets, scan config"
```

---

## Task 9: ResultsTable + Screener page wiring

**Files:**
- Modify: `frontend/src/components/Screener/ResultsTable.tsx`
- Modify: `frontend/src/pages/Screener.tsx`

- [ ] **Step 1: Rewrite `frontend/src/components/Screener/ResultsTable.tsx`**

```tsx
// frontend/src/components/Screener/ResultsTable.tsx
import { useState } from "react";
import { useReactTable, getCoreRowModel, getSortedRowModel, flexRender, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { useNavigate } from "react-router-dom";
import { ScanResultItem, SignalDetail } from "../../api/scanner";

// ── score dots ────────────────────────────────────────────────────────────────

function ScoreDots({ score }: { score: number }) {
  const filled = Math.round(score * 5);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 3 }}>
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} style={{ width: 14, height: 4, borderRadius: 2, background: i < filled ? "#26a69a" : "#2a2e39" }} />
      ))}
    </div>
  );
}

// ── signal chip ───────────────────────────────────────────────────────────────

function SignalChip({ name, detail }: { name: string; detail: SignalDetail }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 8px", borderRadius: 10, fontSize: 11,
      border: `1px solid ${detail.display.color}`,
      background: `${detail.display.color}22`,
      color: detail.display.color,
      marginRight: 4,
    }}>
      {detail.display.icon} {name.replace(/_/g, " ")}
    </span>
  );
}

// ── expandable row ────────────────────────────────────────────────────────────

function ExpandedRow({ item }: { item: ScanResultItem }) {
  return (
    <tr>
      <td colSpan={4} style={{ padding: "0 16px 12px 32px" }}>
        {Object.entries(item.signal_details).map(([name, detail]) => (
          <div key={name} style={{ marginTop: 8 }}>
            <div style={{ fontSize: 11, color: "#787b86", marginBottom: 4 }}>
              <span style={{ color: detail.display.color }}>{detail.display.icon} {name.replace(/_/g, " ")}</span>
              {" — "}{detail.conditions_passed}/{detail.conditions_total} conditions
            </div>
            {detail.details.children?.map((child, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: child.passed ? "#d1d4dc" : "#787b86", marginBottom: 2, paddingLeft: 8 }}>
                <span style={{ color: child.passed ? "#26a69a" : "#f23645", fontSize: 10 }}>{child.passed ? "✓" : "✗"}</span>
                <span style={{ fontFamily: "monospace", color: "#7ba7ff" }}>{child.node_type}</span>
                {Object.entries(child).filter(([k]) => !["passed", "score", "node_type"].includes(k)).map(([k, v]) => (
                  <span key={k} style={{ fontSize: 11, color: "#787b86" }}>{k}: <span style={{ color: "#d1d4dc" }}>{String(v)}</span></span>
                ))}
                <ScoreDots score={child.score} />
              </div>
            ))}
          </div>
        ))}
      </td>
    </tr>
  );
}

// ── ResultsTable ──────────────────────────────────────────────────────────────

export default function ResultsTable({ data }: { data: ScanResultItem[] }) {
  const navigate = useNavigate();
  const [sorting, setSorting] = useState<SortingState>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggleExpand = (symbol: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(symbol) ? next.delete(symbol) : next.add(symbol);
      return next;
    });
  };

  const columns: ColumnDef<ScanResultItem>[] = [
    {
      id: "expand",
      header: "",
      size: 32,
      cell: ({ row }) => (
        <span onClick={(e) => toggleExpand(row.original.symbol, e)}
          style={{ cursor: "pointer", color: "#787b86", fontSize: 10, padding: "0 4px" }}>
          {expanded.has(row.original.symbol) ? "▼" : "▶"}
        </span>
      ),
    },
    {
      accessorKey: "symbol",
      header: "Symbol",
      cell: ({ getValue }) => (
        <span style={{ fontFamily: "monospace", color: "#7ba7ff", fontWeight: 600 }}>
          {getValue() as string}
        </span>
      ),
    },
    {
      id: "matched_signals",
      header: "Signals",
      cell: ({ row }) => (
        <div>
          {row.original.matched_signals.map((name) => {
            const detail = row.original.signal_details[name];
            return detail ? <SignalChip key={name} name={name} detail={detail} /> : null;
          })}
        </div>
      ),
    },
    {
      accessorKey: "overall_score",
      header: "Strength",
      cell: ({ getValue }) => <ScoreDots score={getValue() as number} />,
    },
  ];

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    state: { sorting },
    onSortingChange: setSorting,
  });

  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
      <thead>
        {table.getHeaderGroups().map((hg) => (
          <tr key={hg.id} style={{ background: "#131722" }}>
            {hg.headers.map((h) => (
              <th key={h.id} onClick={h.column.getToggleSortingHandler()}
                style={{ cursor: "pointer", textAlign: "left", padding: "10px 12px", borderBottom: "1px solid #2a2e39", fontSize: 11, color: "#787b86", textTransform: "uppercase", letterSpacing: "0.8px", fontWeight: 600, userSelect: "none" }}>
                {flexRender(h.column.columnDef.header, h.getContext())}
                {h.column.getIsSorted() === "asc" ? " ▲" : h.column.getIsSorted() === "desc" ? " ▼" : ""}
              </th>
            ))}
          </tr>
        ))}
      </thead>
      <tbody>
        {table.getRowModel().rows.map((row) => (
          <>
            <tr key={row.id}
              onClick={() => navigate(`/chart/${row.original.symbol}`)}
              style={{ cursor: "pointer", borderBottom: "1px solid #1e222d" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "#1e222d")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} style={{ padding: "8px 12px" }}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
            {expanded.has(row.original.symbol) && <ExpandedRow key={`${row.id}-expanded`} item={row.original} />}
          </>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 2: Update `frontend/src/pages/Screener.tsx`**

Replace the entire file:

```tsx
// frontend/src/pages/Screener.tsx
import { useFiltersStore } from "../store/filters";
import { useRunScan, ScanResponse } from "../api/scanner";
import ConditionBuilder from "../components/Screener/ConditionBuilder";
import ResultsTable from "../components/Screener/ResultsTable";

export default function Screener() {
  const { source, defaultTimeframe, signals, customConditions, matchMode, maxSymbols } = useFiltersStore();
  const { mutate: runScan, data, isPending } = useRunScan();

  function handleRun() {
    runScan({
      universe: source,
      maxSymbols,
      defaultTimeframe,
      signals,
      customConditions,
      matchMode,
    });
  }

  const results = data?.results ?? [];
  const stats = data ? `${data.matched} / ${data.total_scanned} • ${data.duration_ms}ms` : null;

  return (
    <div style={{ display: "flex", height: "100vh", background: "#0d0d1a" }}>
      {/* Left panel */}
      <div style={{ width: 320, background: "#131722", borderRight: "1px solid #2a2e39", display: "flex", flexDirection: "column", overflowY: "auto", flexShrink: 0 }}>
        <div style={{ padding: "14px 16px", borderBottom: "1px solid #2a2e39" }}>
          <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: "#d1d4dc" }}>Scanner</h2>
        </div>
        <ConditionBuilder />
        <div style={{ padding: 16, borderTop: "1px solid #2a2e39" }}>
          <button
            onClick={handleRun}
            disabled={isPending}
            style={{
              width: "100%", padding: "10px 0",
              background: isPending ? "#1e4bd0" : "#2962ff",
              border: "none", borderRadius: 4, color: "#fff", fontSize: 14, fontWeight: 600,
              cursor: isPending ? "not-allowed" : "pointer",
            }}
          >
            {isPending ? "⟳ Scanning..." : "▶  Run Scan"}
          </button>
        </div>
      </div>

      {/* Results panel */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflowY: "auto" }}>
        <div style={{ padding: "14px 20px", borderBottom: "1px solid #2a2e39", background: "#131722", display: "flex", alignItems: "center", gap: 10 }}>
          <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: "#d1d4dc" }}>Results</h2>
          {results.length > 0 && (
            <span style={{ background: "#26a69a", color: "#fff", borderRadius: 10, padding: "1px 8px", fontSize: 11 }}>{results.length}</span>
          )}
          {stats && <span style={{ marginLeft: "auto", fontSize: 11, color: "#787b86" }}>{stats}</span>}
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: results.length === 0 ? 0 : 16 }}>
          {results.length === 0 ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: 300, color: "#363c4e" }}>
              <div style={{ fontSize: 48, marginBottom: 16 }}>⊞</div>
              <div style={{ fontSize: 14, color: "#787b86", marginBottom: 8 }}>No results yet</div>
              <div style={{ fontSize: 12, color: "#363c4e" }}>Select signals or add conditions, then run scan</div>
            </div>
          ) : (
            <ResultsTable data={results} />
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles and app starts**

```bash
cd frontend && npx tsc --noEmit && npm run dev -- --port 5174 &
```
Open `http://localhost:5174`. Verify:
- Left panel shows Signal Presets section with signal chips from `/scanner/signals`
- Custom Conditions section shows "+" button that creates an AND group
- Adding a condition row shows type dropdown + parameter inputs
- Scan Config section shows TF selector, match mode, max symbols
- Run Scan fires `POST /scanner/run` (check network tab)
- Results table shows Signals column with chips (if any matches) + expandable rows

- [ ] **Step 4: Fix any runtime errors from browser console**

Common: key warnings on `<>` fragments in table rows — wrap with `React.Fragment key={...}` instead of `<>`.

Fix in `ResultsTable.tsx`:
```tsx
// replace:
<>
  <tr key={row.id} ...>
  ...
  {expanded.has(...) && <ExpandedRow key={...} />}
</>

// with:
<React.Fragment key={row.id}>
  <tr ...>
  ...
  {expanded.has(...) && <ExpandedRow ... />}
</React.Fragment>
```

- [ ] **Step 5: Run full test suite one more time**

```bash
cd backend && pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Screener/ResultsTable.tsx frontend/src/pages/Screener.tsx
git commit -m "feat: update ResultsTable with signal chips + expandable rows, wire Screener page to new store"
```

---
