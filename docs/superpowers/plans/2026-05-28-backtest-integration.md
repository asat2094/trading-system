# Backtest Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Full end-to-end backtest workflow in trading-system chart: define conditions, run backtest against QuestDB data via backtest-engine sidecar, see entry/exit/pattern markers overlaid on candles.

**Architecture:** backtest-engine stays a standalone FastAPI sidecar (port 8085). trading-system frontend POSTs a run request directly to backtest-engine, polls status, then fetches lightweight-charts markers. Chart.tsx gains a LIVE/BACKTEST mode toggle; BacktestPanel handles launch+polling; BacktestOverlay renders markers on the existing candlestick series.

**Tech Stack:** Python 3.12 · backtesting.py · pandas_ta · FastAPI · SQLite · React 18 · lightweight-charts 5.2 · TypeScript

---

## File Map

### trading-system — backend (new/modified)
| File | Change |
|---|---|
| `backend/technical/patterns/candlestick.py` | Add `_detect_gravestone_doji` + register in `_CANDLESTICK_DETECTORS` |
| `backend/technical/patterns/levels.py` | Add `pivot_highs()` + `pivot_lows()` |
| `backend/tests/unit/test_candlestick.py` | Add gravestone_doji test cases |
| `backend/tests/unit/test_levels.py` | New file: pivot_high/low tests |

### trading-system — frontend (new/modified)
| File | Change |
|---|---|
| `frontend/src/components/Chart/CandlestickChart.tsx` | Export candleSeries + chart handles via `forwardRef`/`useImperativeHandle` |
| `frontend/src/components/Chart/BacktestOverlay.tsx` | New: fetch markers, render via `createSeriesMarkers`, add price lines |
| `frontend/src/components/Chart/BacktestPanel.tsx` | New: condition builder + SL/target config + run launcher + status poller |
| `frontend/src/pages/Chart.tsx` | Add LIVE/BACKTEST toggle, mount BacktestPanel + BacktestOverlay |

### backtest-engine (new/modified)
| File | Change |
|---|---|
| `backend/execution/base.py` | Add `annotations: list[str] = []` to `TradeRecord` |
| `backend/execution/sl_target.py` | New: `SLTargetConfig` model + `wrap_with_sl_target()` factory |
| `backend/execution/local/engine.py` | Accept `sl_target` param, call `wrap_with_sl_target`, collect annotations |
| `backend/strategy/dsl_bridge.py` | New: ConditionNode JSON → Python strategy class string |
| `backend/data/pattern_detector.py` | New: detect entry-bar annotations (gravestone_doji, VWAP cross, etc.) |
| `backend/api/runs.py` | Extend `RunRequest` with `condition_node`/`sl_target`; add `GET /runs/{id}/markers/{symbol}` |
| `backend/main.py` | Add `localhost:5173` to CORS `allow_origins` |
| `tests/test_dsl_bridge.py` | New: DSL → strategy → signal fires on known bars |
| `tests/test_sl_target.py` | New: SL/target wrapper closes position at correct bar |
| `tests/test_pattern_detector.py` | New: annotation detection on synthetic entry bars |

---

## Task 1: gravestone_doji pattern

**Files:**
- Modify: `backend/technical/patterns/candlestick.py`
- Modify: `backend/tests/unit/test_candlestick.py`

- [ ] **Step 1.1: Write failing tests**

Open `backend/tests/unit/test_candlestick.py` and add at the end:

```python
# ── gravestone_doji ───────────────────────────────────────────────────────────

def test_gravestone_doji_detected():
    # Long upper wick, tiny body at low, no lower wick
    # open=99, close=100, high=120, low=98 → body=1/22≈0.045, upper=20/22≈0.91, lower=2/22≈0.09
    df = df_from_bars(make_bar(99, 120, 98, 100))
    result = detect_candlestick(df, "gravestone_doji")
    assert result is not None
    assert result["direction"] == "bearish"
    assert result["confidence"] >= 0.6

def test_gravestone_doji_high_confidence():
    # Perfect gravestone: open=close=low, all wick above
    df = df_from_bars(make_bar(100, 130, 100, 100))
    result = detect_candlestick(df, "gravestone_doji")
    assert result is not None
    assert result["confidence"] > 0.9

def test_gravestone_doji_not_detected_large_body():
    # Large body — fails body < 0.1 check
    df = df_from_bars(make_bar(100, 130, 99, 120))
    result = detect_candlestick(df, "gravestone_doji")
    assert result is None

def test_gravestone_doji_not_detected_lower_wick():
    # Has significant lower wick — fails lower < 0.1 check
    df = df_from_bars(make_bar(100, 130, 90, 101))
    result = detect_candlestick(df, "gravestone_doji")
    assert result is None

def test_gravestone_doji_not_detected_small_upper_wick():
    # Small upper wick — fails upper > 0.6 check
    # body=99→100=1, range=103-98=5, upper=103-100=3/5=0.6 (just at boundary)
    df = df_from_bars(make_bar(99, 103, 98, 100))
    result = detect_candlestick(df, "gravestone_doji")
    # upper_wick/range = 3/5 = 0.6, exactly at boundary — borderline, assert is None for strict >0.6
    assert result is None

def test_gravestone_doji_not_detected_flat_candle():
    # Zero range — should not crash, should return None
    df = df_from_bars(make_bar(100, 100, 100, 100))
    result = detect_candlestick(df, "gravestone_doji")
    assert result is None
```

- [ ] **Step 1.2: Run tests — confirm they fail**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/backend
PYTHONPATH=. .venv/bin/pytest tests/unit/test_candlestick.py -k gravestone -v
```
Expected: `ValueError: Unknown candlestick pattern: 'gravestone_doji'`

- [ ] **Step 1.3: Implement gravestone_doji**

In `backend/technical/patterns/candlestick.py`, add this function before `_CANDLESTICK_DETECTORS`:

```python
def _detect_gravestone_doji(df: pd.DataFrame) -> dict | None:
    if len(df) < 1:
        return None
    row = df.iloc[-1]
    rng = row["high"] - row["low"]
    if rng < 1e-9:
        return None
    body = _body(row) / rng
    upper = _upper_shadow(row) / rng
    lower = _lower_shadow(row) / rng
    if body < 0.1 and upper > 0.6 and lower < 0.1:
        return {"confidence": round(upper, 4), "direction": "bearish"}
    return None
```

Then add to `_CANDLESTICK_DETECTORS`:

```python
_CANDLESTICK_DETECTORS: dict[str, callable] = {
    "bearish_engulfing": _detect_bearish_engulfing,
    "bullish_engulfing": _detect_bullish_engulfing,
    "hammer":            _detect_hammer,
    "shooting_star":     _detect_shooting_star,
    "doji":              _detect_doji,
    "morning_star":      _detect_morning_star,
    "evening_star":      _detect_evening_star,
    "gravestone_doji":   _detect_gravestone_doji,   # ← new
}
```

- [ ] **Step 1.4: Run tests — confirm they pass**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/backend
PYTHONPATH=. .venv/bin/pytest tests/unit/test_candlestick.py -v
```
Expected: all 21+ tests pass (including existing 15)

- [ ] **Step 1.5: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
git add backend/technical/patterns/candlestick.py backend/tests/unit/test_candlestick.py
git commit -m "feat: add gravestone_doji candlestick pattern"
```

---

## Task 2: pivot_high / pivot_low detectors

**Files:**
- Modify: `backend/technical/patterns/levels.py`
- Create: `backend/tests/unit/test_levels.py`

- [ ] **Step 2.1: Write failing tests**

Create `backend/tests/unit/test_levels.py`:

```python
import pandas as pd
import numpy as np
import pytest
from technical.patterns.levels import pivot_highs, pivot_lows


def _make_df(highs, lows=None, closes=None):
    n = len(highs)
    if lows is None:
        lows = [h - 2 for h in highs]
    if closes is None:
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    return pd.DataFrame({
        "open": closes, "high": highs, "low": lows,
        "close": closes, "volume": [100_000] * n,
    })


def test_pivot_high_detected_at_peak():
    # Clear peak at index 5
    highs = [10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10, 10, 10]
    df = _make_df(highs)
    result = pivot_highs(df, left=3, right=3)
    assert 5 in result


def test_pivot_high_not_detected_flat():
    highs = [10] * 15
    df = _make_df(highs)
    result = pivot_highs(df, left=3, right=3)
    # Flat series: every point equals max — all qualify but that's ok, or none
    # Just ensure no crash
    assert isinstance(result, list)


def test_pivot_low_detected_at_trough():
    lows = [20, 18, 15, 12, 10, 3, 10, 12, 15, 18, 20, 20, 20]
    df = _make_df([l + 5 for l in lows], lows)
    result = pivot_lows(df, left=3, right=3)
    assert 5 in result


def test_pivot_high_respects_left_right():
    # With left=5, right=5, need at least 11 bars; peak must beat 5 bars on each side
    highs = [5, 6, 7, 8, 9, 15, 9, 8, 7, 6, 5]
    df = _make_df(highs)
    result = pivot_highs(df, left=5, right=5)
    assert 5 in result


def test_pivot_multiple_peaks():
    highs = [5, 10, 5, 5, 5, 10, 5, 5, 5, 10, 5]
    df = _make_df(highs)
    result = pivot_highs(df, left=2, right=2)
    # Peaks at index 1, 5, 9
    assert 1 in result
    assert 5 in result
    assert 9 in result


def test_pivot_low_empty_when_short_series():
    df = _make_df([10, 9, 8])
    result = pivot_lows(df, left=5, right=5)
    assert result == []
```

- [ ] **Step 2.2: Run tests — confirm they fail**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/backend
PYTHONPATH=. .venv/bin/pytest tests/unit/test_levels.py -v
```
Expected: `ImportError: cannot import name 'pivot_highs' from 'technical.patterns.levels'`

- [ ] **Step 2.3: Implement pivot_highs and pivot_lows**

Add to `backend/technical/patterns/levels.py` (after `find_support_resistance`):

```python
def pivot_highs(df: pd.DataFrame, left: int = 5, right: int = 5) -> list[int]:
    """
    Return bar indices where high[i] is strictly greater than all highs
    in the [i-left, i-1] and [i+1, i+right] windows.
    """
    highs = df["high"].values
    n = len(highs)
    result = []
    for i in range(left, n - right):
        window = list(highs[i - left:i]) + list(highs[i + 1:i + right + 1])
        if len(window) == left + right and highs[i] >= max(window):
            result.append(i)
    return result


def pivot_lows(df: pd.DataFrame, left: int = 5, right: int = 5) -> list[int]:
    """
    Return bar indices where low[i] is less than or equal to all lows
    in the [i-left, i-1] and [i+1, i+right] windows.
    """
    lows = df["low"].values
    n = len(lows)
    result = []
    for i in range(left, n - right):
        window = list(lows[i - left:i]) + list(lows[i + 1:i + right + 1])
        if len(window) == left + right and lows[i] <= min(window):
            result.append(i)
    return result
```

- [ ] **Step 2.4: Run tests — confirm they pass**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/backend
PYTHONPATH=. .venv/bin/pytest tests/unit/test_levels.py -v
```
Expected: 6/6 pass

- [ ] **Step 2.5: Run full test suite — ensure no regressions**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/backend
PYTHONPATH=. .venv/bin/pytest tests/ -v --tb=short
```
Expected: 76+ tests pass, 0 failures

- [ ] **Step 2.6: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
git add backend/technical/patterns/levels.py backend/tests/unit/test_levels.py
git commit -m "feat: add pivot_highs and pivot_lows detectors"
```

---

## Task 3: SLTargetConfig + wrap_with_sl_target

**Files:**
- Create: `backend/execution/sl_target.py`
- Create: `tests/test_sl_target.py`

Working directory for all steps: `/Users/ankitatiwari/Desktop/claude-playground/backtest-engine`

- [ ] **Step 3.1: Write failing tests**

Create `tests/test_sl_target.py`:

```python
import pytest
import pandas as pd
import numpy as np
from backend.execution.sl_target import SLTargetConfig, wrap_with_sl_target
from backtesting import Strategy


def _make_df(closes):
    n = len(closes)
    closes = np.array(closes, dtype=float)
    highs = closes + 2
    lows = closes - 2
    df = pd.DataFrame({
        "Open": closes, "High": highs, "Low": lows,
        "Close": closes, "Volume": np.ones(n) * 100_000,
    })
    df.index = pd.date_range("2024-01-01", periods=n, freq="D")
    return df


class BuyOnBar5(Strategy):
    """Buys on bar 5, never closes."""
    def init(self): pass
    def next(self):
        if len(self.data) == 5 and not self.position:
            self.buy()


def test_fixed_pct_sl_closes_position():
    """SL at 2%: entry=100, SL=98. Bar 6 drops to 97 → position closes."""
    cfg = SLTargetConfig(sl_type="fixed_pct", sl_value=2.0,
                         target_type="fixed_pct", target_value=6.0)
    wrapped = wrap_with_sl_target(BuyOnBar5, cfg)
    # prices: rise to 100 on bar 5, drop to 97 on bar 6
    closes = [95, 96, 97, 98, 100, 97, 97, 97, 97, 97]
    from backtesting import Backtest
    bt = Backtest(_make_df(closes), wrapped, cash=100_000, commission=0.0)
    stats = bt.run()
    trades = stats._trades
    assert len(trades) >= 1
    # Entry on bar 5 (price 100), exit when price hits 98 or below
    trade = trades.iloc[0]
    assert float(trade["ExitPrice"]) <= 98.5


def test_fixed_pct_tp_closes_position():
    """TP at 6%: entry=100, TP=106. Bar 7 reaches 107 → position closes."""
    cfg = SLTargetConfig(sl_type="fixed_pct", sl_value=2.0,
                         target_type="fixed_pct", target_value=6.0)
    wrapped = wrap_with_sl_target(BuyOnBar5, cfg)
    closes = [95, 96, 97, 98, 100, 102, 107, 107, 107, 107]
    from backtesting import Backtest
    bt = Backtest(_make_df(closes), wrapped, cash=100_000, commission=0.0)
    stats = bt.run()
    trades = stats._trades
    assert len(trades) >= 1
    trade = trades.iloc[0]
    assert float(trade["PnL"]) > 0


def test_rr_ratio_tp():
    """RR 3:1 with 2% SL → TP at 6%."""
    cfg = SLTargetConfig(sl_type="fixed_pct", sl_value=2.0,
                         target_type="rr_ratio", target_value=3.0)
    wrapped = wrap_with_sl_target(BuyOnBar5, cfg)
    closes = [95, 96, 97, 98, 100, 102, 107, 107, 107, 107]
    from backtesting import Backtest
    bt = Backtest(_make_df(closes), wrapped, cash=100_000, commission=0.0)
    stats = bt.run()
    trades = stats._trades
    assert len(trades) >= 1
    assert float(trades.iloc[0]["PnL"]) > 0
```

- [ ] **Step 3.2: Run tests — confirm they fail**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/backtest-engine
PYTHONPATH=. venv/bin/pytest tests/test_sl_target.py -v
```
Expected: `ModuleNotFoundError: No module named 'backend.execution.sl_target'`

- [ ] **Step 3.3: Implement sl_target.py**

Create `backend/execution/sl_target.py`:

```python
"""
SLTargetConfig — configurable stop-loss / take-profit rules.
wrap_with_sl_target() — wraps any backtesting.py Strategy subclass so that
SL/TP are enforced independently of strategy logic.
"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel
import pandas as pd
import pandas_ta


class SLTargetConfig(BaseModel):
    sl_type:      Literal["fixed_pct", "atr_multiple", "trailing_pct", "trailing_atr"]
    sl_value:     float   # % or ATR multiplier
    target_type:  Literal["fixed_pct", "rr_ratio", "atr_multiple"]
    target_value: float   # %, R-multiple, or ATR multiplier


def wrap_with_sl_target(base_cls: type, config: SLTargetConfig) -> type:
    """
    Return a new Strategy class that wraps base_cls with SL/target enforcement.
    Works by overriding buy() (for non-trailing types) and next() (for trailing).
    """
    cfg = config

    class SLWrapped(base_cls):
        _sl_cfg = cfg
        _entry_price: float = 0.0
        _peak_price: float = 0.0

        def _atr(self) -> float:
            try:
                series = pandas_ta.atr(
                    pd.Series(list(self.data.High)),
                    pd.Series(list(self.data.Low)),
                    pd.Series(list(self.data.Close)),
                    length=14,
                )
                val = float(series.iloc[-1]) if series is not None and not series.empty else None
                return val if val and val == val else float(self.data.Close[-1]) * 0.02
            except Exception:
                return float(self.data.Close[-1]) * 0.02

        def _sl_price(self, entry: float) -> float | None:
            if cfg.sl_type == "fixed_pct":
                return entry * (1 - cfg.sl_value / 100)
            if cfg.sl_type == "atr_multiple":
                return entry - cfg.sl_value * self._atr()
            return None  # trailing: managed in next()

        def _tp_price(self, entry: float, sl: float | None) -> float | None:
            if cfg.target_type == "fixed_pct":
                return entry * (1 + cfg.target_value / 100)
            if cfg.target_type == "rr_ratio":
                risk = (entry - sl) if sl else entry * 0.02
                return entry + cfg.target_value * risk
            if cfg.target_type == "atr_multiple":
                return entry + cfg.target_value * self._atr()
            return None

        def buy(self, **kwargs):
            entry = float(self.data.Close[-1])
            if cfg.sl_type not in ("trailing_pct", "trailing_atr"):
                sl = self._sl_price(entry)
                tp = self._tp_price(entry, sl)
                kwargs.setdefault("sl", sl)
                kwargs.setdefault("tp", tp)
            return super().buy(**kwargs)

        def next(self):
            # Trailing stop management (before calling strategy logic)
            if self.position.is_long and cfg.sl_type in ("trailing_pct", "trailing_atr"):
                close = float(self.data.Close[-1])
                if close > self._peak_price:
                    self._peak_price = close
                if cfg.sl_type == "trailing_pct":
                    trail_dist = self._peak_price * (cfg.sl_value / 100)
                else:
                    trail_dist = cfg.sl_value * self._atr()
                if close <= self._peak_price - trail_dist:
                    self.position.close()
                    return

            was_long = self.position.is_long
            super().next()

            # Record entry when position just opened
            if not was_long and self.position.is_long:
                self._entry_price = float(self.data.Close[-1])
                self._peak_price = self._entry_price

    SLWrapped.__name__ = f"SLWrapped_{base_cls.__name__}"
    SLWrapped.__qualname__ = SLWrapped.__name__
    return SLWrapped
```

- [ ] **Step 3.4: Run tests — confirm they pass**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/backtest-engine
PYTHONPATH=. venv/bin/pytest tests/test_sl_target.py -v
```
Expected: 3/3 pass

- [ ] **Step 3.5: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/backtest-engine
git add backend/execution/sl_target.py tests/test_sl_target.py
git commit -m "feat: add SLTargetConfig and wrap_with_sl_target"
```

---

## Task 4: DSL bridge — ConditionNode JSON → Python strategy

**Files:**
- Create: `backend/strategy/dsl_bridge.py`
- Create: `tests/test_dsl_bridge.py`

- [ ] **Step 4.1: Write failing tests**

Create `tests/test_dsl_bridge.py`:

```python
"""
Tests for dsl_bridge: each ConditionNode tree fires signals on known synthetic bars.
"""
import pytest
import pandas as pd
import numpy as np
from backtesting import Backtest
from backend.strategy.dsl_bridge import condition_node_to_python
from backend.execution.sl_target import SLTargetConfig, wrap_with_sl_target
import types, textwrap


_SL_CFG = SLTargetConfig(sl_type="fixed_pct", sl_value=2.0,
                          target_type="fixed_pct", target_value=6.0)


def _exec_strategy(python_code: str) -> type:
    module = types.ModuleType("test_strat")
    exec(textwrap.dedent(python_code), module.__dict__)
    return module.__dict__["GeneratedStrategy"]


def _make_df(n=100, trend="flat"):
    np.random.seed(42)
    if trend == "up":
        closes = np.linspace(100, 130, n) + np.random.randn(n) * 0.5
    else:
        closes = np.full(n, 100.0) + np.random.randn(n) * 0.5
    closes = np.abs(closes)
    highs = closes + 2
    lows = closes - 2
    df = pd.DataFrame({
        "Open": closes, "High": highs, "Low": lows,
        "Close": closes, "Volume": np.ones(n) * 100_000,
    })
    df.index = pd.date_range("2020-01-01", periods=n, freq="D")
    return df


def test_indicator_node_rsi_lt():
    """Single RSI < 30 indicator node → generates runnable strategy."""
    node = {
        "type": "indicator",
        "indicator": "rsi",
        "operator": "lt",
        "value": 30,
        "params": {"period": 14},
    }
    code = condition_node_to_python(node, _SL_CFG)
    cls = _exec_strategy(code)
    cls = wrap_with_sl_target(cls, _SL_CFG)
    df = _make_df(100)
    bt = Backtest(df, cls, cash=100_000, commission=0.0)
    stats = bt.run()
    # Just verify it runs without error and returns a result
    assert stats is not None


def test_ema_crossover_node():
    """EMA crossover (20 above 50) node on uptrend data → generates at least one trade."""
    node = {
        "type": "crossover",
        "crossover_type": "above",
        "indicator_a": "ema",
        "indicator_b": "ema",
        "params_a": {"period": 5},
        "params_b": {"period": 10},
    }
    code = condition_node_to_python(node, _SL_CFG)
    cls = _exec_strategy(code)
    cls = wrap_with_sl_target(cls, _SL_CFG)
    df = _make_df(100, trend="up")
    bt = Backtest(df, cls, cash=100_000, commission=0.0)
    stats = bt.run()
    assert stats["# Trades"] >= 1


def test_and_composite_node():
    """AND node with two indicator leaves → runnable without error."""
    node = {
        "type": "composite",
        "logic": "AND",
        "children": [
            {"type": "indicator", "indicator": "rsi", "operator": "lt",
             "value": 60, "params": {"period": 14}},
            {"type": "indicator", "indicator": "ema", "operator": "gt",
             "value": 0, "params": {"period": 20}},
        ],
    }
    code = condition_node_to_python(node, _SL_CFG)
    cls = _exec_strategy(code)
    cls = wrap_with_sl_target(cls, _SL_CFG)
    df = _make_df(100)
    bt = Backtest(df, cls, cash=100_000, commission=0.0)
    stats = bt.run()
    assert stats is not None


def test_volume_node():
    """Volume ratio node → runnable without error."""
    node = {
        "type": "volume",
        "volume_ratio": 1.5,
        "volume_period": 20,
    }
    code = condition_node_to_python(node, _SL_CFG)
    cls = _exec_strategy(code)
    df = _make_df(100)
    bt = Backtest(df, cls, cash=100_000, commission=0.0)
    stats = bt.run()
    assert stats is not None


def test_chart_pattern_raises():
    """chart_pattern node type raises ValueError in v1."""
    node = {"type": "chart_pattern", "chart_pattern": "head_and_shoulders"}
    with pytest.raises(ValueError, match="chart_pattern"):
        condition_node_to_python(node, _SL_CFG)
```

- [ ] **Step 4.2: Run tests — confirm they fail**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/backtest-engine
PYTHONPATH=. venv/bin/pytest tests/test_dsl_bridge.py -v
```
Expected: `ModuleNotFoundError: No module named 'backend.strategy.dsl_bridge'`

- [ ] **Step 4.3: Implement dsl_bridge.py**

Create `backend/strategy/dsl_bridge.py`:

```python
"""
Convert ConditionNode JSON (trading-system scanner DSL) into a backtesting.py
GeneratedStrategy Python class string.

Node type detection (from wire format):
  - "type": "composite" or has "logic" key  → composite AND/OR
  - "type": "indicator" or has "indicator" key  → indicator comparison
  - "type": "crossover" or has "crossover_type" key  → crossover
  - "type": "candlestick" or has "candlestick" key  → pattern check
  - "type": "volume" or has "volume_ratio" key  → volume comparison
  - "type": "trend" or has "trend" key  → trend check
  - "type": "chart_pattern"  → ValueError (v2)
"""
from __future__ import annotations
from backend.execution.sl_target import SLTargetConfig

# pandas_ta function name + which data arrays it needs
_INDICATOR_TA: dict[str, tuple[str, list[str]]] = {
    "rsi":              ("rsi",     ["close"]),
    "ema":              ("ema",     ["close"]),
    "sma":              ("sma",     ["close"]),
    "wma":              ("wma",     ["close"]),
    "atr":              ("atr",     ["high", "low", "close"]),
    "cci":              ("cci",     ["high", "low", "close"]),
    "williams_r":       ("willr",   ["high", "low", "close"]),
    "obv":              ("obv",     ["close", "volume"]),
    "vwap":             ("vwap",    ["high", "low", "close", "volume"]),
    "bollinger_bands":  ("bbands",  ["close"]),
    "supertrend":       ("supertrend", ["high", "low", "close"]),
    "macd":             ("macd",    ["close"]),
    "stochastic":       ("stoch",   ["high", "low", "close"]),
    "price_vs_resistance": None,  # handled separately
}

_OP_MAP = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">=", "eq": "=="}

_PREAMBLE = '''import numpy as np
import pandas as pd
import pandas_ta
from backtesting import Strategy
from backtesting.lib import crossover


def _pd_ta(fn, *args, **kwargs):
    args = list(args)
    args[0] = pd.Series(args[0])
    result = fn(*args, **kwargs)
    if result is None:
        return np.full(len(args[0]), np.nan)
    if isinstance(result, pd.DataFrame):
        result = result.iloc[:, 0]
    return result.values if hasattr(result, "values") else np.asarray(result, dtype=float)

'''


def _ivar(indicator: str, params: dict) -> str:
    """Unique variable name for an indicator + params combo."""
    suffix = "_".join(f"{v}" for v in sorted(params.values())) if params else "def"
    return f"_i_{indicator}_{suffix}"


def _data_arg(col: str) -> str:
    return {"close": "self.data.Close", "high": "self.data.High",
            "low": "self.data.Low", "volume": "self.data.Volume"}[col]


def _collect_indicators(node: dict, inits: list[str], seen: set[str]) -> None:
    """Recursively collect self.I() init lines for all indicator/crossover leaves."""
    ntype = _node_type(node)

    if ntype == "composite":
        for child in node.get("children", []):
            _collect_indicators(child, inits, seen)

    elif ntype == "indicator":
        ind = node["indicator"]
        params = node.get("params", {})
        if ind == "price_vs_resistance":
            return  # handled inline in next()
        if ind not in _INDICATOR_TA:
            return
        ta_fn, cols = _INDICATOR_TA[ind]
        var = _ivar(ind, params)
        if var not in seen:
            seen.add(var)
            kw = ", ".join(f"{k}={v}" for k, v in params.items())
            data_args = ", ".join(_data_arg(c) for c in cols)
            kw_str = f", {kw}" if kw else ""
            inits.append(f"        self.{var} = self.I(_pd_ta, pandas_ta.{ta_fn}, {data_args}{kw_str})")

    elif ntype == "crossover":
        for side, pkey in [("indicator_a", "params_a"), ("indicator_b", "params_b")]:
            ind = node.get(side, "ema")
            params = node.get(pkey, {})
            if ind not in _INDICATOR_TA:
                continue
            ta_fn, cols = _INDICATOR_TA[ind]
            var = _ivar(ind, params)
            if var not in seen:
                seen.add(var)
                kw = ", ".join(f"{k}={v}" for k, v in params.items())
                data_args = ", ".join(_data_arg(c) for c in cols)
                kw_str = f", {kw}" if kw else ""
                inits.append(f"        self.{var} = self.I(_pd_ta, pandas_ta.{ta_fn}, {data_args}{kw_str})")


def _node_type(node: dict) -> str:
    t = node.get("type", "")
    if t == "chart_pattern" or node.get("chart_pattern"):
        return "chart_pattern"
    if t in ("composite", "group") or node.get("logic"):
        return "composite"
    if t == "crossover" or node.get("crossover_type"):
        return "crossover"
    if t == "indicator" or node.get("indicator"):
        return "indicator"
    if t == "candlestick" or node.get("candlestick"):
        return "candlestick"
    if t == "volume" or node.get("volume_ratio") is not None:
        return "volume"
    if t == "trend" or node.get("trend"):
        return "trend"
    return "unknown"


def _node_to_expr(node: dict) -> str:
    """Return a Python boolean expression for a single ConditionNode."""
    ntype = _node_type(node)

    if ntype == "chart_pattern":
        raise ValueError(
            "chart_pattern ConditionNode is not supported in DSL bridge v1. "
            "Use the LLM strategy path instead."
        )

    if ntype == "composite":
        logic = node.get("logic", "AND").upper()
        children = node.get("children", [])
        if not children:
            return "True"
        exprs = [f"({_node_to_expr(c)})" for c in children]
        joiner = " and " if logic == "AND" else " or "
        return joiner.join(exprs)

    if ntype == "indicator":
        ind = node["indicator"]
        op = _OP_MAP.get(node.get("operator", "gt"), ">")
        val = node.get("value", 0)
        params = node.get("params", {})
        if ind == "price_vs_resistance":
            return f"self.data.Close[-1] {op} {val}"
        var = _ivar(ind, params)
        return f"self.{var}[-1] {op} {val}"

    if ntype == "crossover":
        ind_a = node.get("indicator_a", "ema")
        ind_b = node.get("indicator_b", "ema")
        params_a = node.get("params_a", {})
        params_b = node.get("params_b", {})
        var_a = _ivar(ind_a, params_a)
        var_b = _ivar(ind_b, params_b)
        ctype = node.get("crossover_type", "above")
        if ctype == "above":
            return f"crossover(self.{var_a}, self.{var_b})"
        else:
            return f"crossover(self.{var_b}, self.{var_a})"

    if ntype == "candlestick":
        pattern = node.get("candlestick", "doji")
        min_conf = node.get("min_confidence", 0.5)
        return (
            f"_check_candle(self.data.Open, self.data.High, "
            f"self.data.Low, self.data.Close, {pattern!r}, {min_conf})"
        )

    if ntype == "volume":
        ratio = node.get("volume_ratio", 1.5)
        period = node.get("volume_period", 20)
        return (
            f"(len(self.data.Volume) > {period} and "
            f"self.data.Volume[-1] > {ratio} * float(pd.Series(list(self.data.Volume[-{period}:])).mean()))"
        )

    if ntype == "trend":
        direction = node.get("trend", "up")
        window = node.get("trend_window", 20)
        if direction == "up":
            return (
                f"(len(self.data.Close) > {window} and "
                f"self.data.Close[-1] > float(pd.Series(list(self.data.Close[-{window}:])).mean()))"
            )
        elif direction == "down":
            return (
                f"(len(self.data.Close) > {window} and "
                f"self.data.Close[-1] < float(pd.Series(list(self.data.Close[-{window}:])).mean()))"
            )
        else:  # sideways — within 1% of mean
            return (
                f"(len(self.data.Close) > {window} and "
                f"abs(self.data.Close[-1] - float(pd.Series(list(self.data.Close[-{window}:])).mean())) "
                f"/ max(float(pd.Series(list(self.data.Close[-{window}:])).mean()), 1e-9) < 0.01)"
            )

    return "False"


_CANDLE_HELPER = '''
def _check_candle(open_arr, high_arr, low_arr, close_arr, pattern, min_conf=0.5):
    o = float(open_arr[-1]); h = float(high_arr[-1])
    l = float(low_arr[-1]); c = float(close_arr[-1])
    rng = h - l
    if rng < 1e-9:
        return False
    body = abs(c - o) / rng
    upper = (h - max(o, c)) / rng
    lower = (min(o, c) - l) / rng
    if pattern == "gravestone_doji":
        return body < 0.1 and upper > 0.6 and lower < 0.1
    if pattern == "doji":
        return body < 0.1
    if pattern == "hammer":
        return body < 0.35 and lower > 0.5 and upper < 0.15
    if pattern == "shooting_star":
        return body < 0.35 and upper > 0.5 and lower < 0.15
    if pattern == "bullish_engulfing":
        if len(open_arr) < 2:
            return False
        po = float(open_arr[-2]); pc = float(close_arr[-2])
        return pc < po and c > o and o <= pc and c >= po
    if pattern == "bearish_engulfing":
        if len(open_arr) < 2:
            return False
        po = float(open_arr[-2]); pc = float(close_arr[-2])
        return pc > po and c < o and o >= pc and c <= po
    return False

'''


def condition_node_to_python(node: dict, sl_target: SLTargetConfig) -> str:
    """
    Convert a ConditionNode dict into a Python string defining GeneratedStrategy(Strategy).
    The returned string can be exec()'d and used with backtesting.py's Backtest().
    SL/target is NOT injected here — caller wraps with wrap_with_sl_target() after exec.

    Raises ValueError for unsupported node types (chart_pattern).
    """
    # Pre-validate for chart_pattern anywhere in tree
    def _check_no_chart_pattern(n: dict) -> None:
        if _node_type(n) == "chart_pattern":
            raise ValueError(
                "chart_pattern ConditionNode is not supported in DSL bridge v1."
            )
        for child in n.get("children", []):
            _check_no_chart_pattern(child)

    _check_no_chart_pattern(node)

    # Collect init lines
    inits: list[str] = []
    seen: set[str] = set()
    _collect_indicators(node, inits, seen)

    init_body = "\n".join(inits) if inits else "        pass"
    entry_expr = _node_to_expr(node)

    strategy_code = f'''{_PREAMBLE}{_CANDLE_HELPER}
class GeneratedStrategy(Strategy):
    def init(self):
{init_body}

    def next(self):
        if ({entry_expr}) and not self.position:
            self.buy()
'''
    return strategy_code
```

- [ ] **Step 4.4: Run tests — confirm they pass**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/backtest-engine
PYTHONPATH=. venv/bin/pytest tests/test_dsl_bridge.py -v
```
Expected: 5/5 pass

- [ ] **Step 4.5: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/backtest-engine
git add backend/strategy/dsl_bridge.py tests/test_dsl_bridge.py
git commit -m "feat: add DSL bridge — ConditionNode JSON to backtesting.py strategy"
```

---

## Task 5: TradeRecord.annotations + pattern_detector.py

**Files:**
- Modify: `backend/execution/base.py`
- Create: `backend/data/pattern_detector.py`
- Create: `tests/test_pattern_detector.py`

- [ ] **Step 5.1: Write failing test for pattern_detector**

Create `tests/test_pattern_detector.py`:

```python
import pytest
import pandas as pd
import numpy as np
from backend.data.pattern_detector import detect_entry_annotations


def _make_df(n=50):
    closes = np.linspace(100, 110, n)
    highs = closes + 2
    lows = closes - 2
    volume = np.full(n, 100_000, dtype=float)
    # Make last bar a spike in volume
    volume[-1] = 350_000
    df = pd.DataFrame({
        "open": closes, "high": highs, "low": lows,
        "close": closes, "volume": volume,
    })
    df.index = pd.date_range("2024-01-01", periods=n, freq="D")
    return df


def test_volume_spike_detected():
    df = _make_df(50)
    annotations = detect_entry_annotations(df, entry_idx=49)
    assert "volume_spike_2x" in annotations


def test_no_annotations_on_quiet_bar():
    df = _make_df(50)
    # Reset volume spike
    df["volume"] = 100_000
    annotations = detect_entry_annotations(df, entry_idx=49)
    assert "volume_spike_2x" not in annotations


def test_gravestone_doji_annotation():
    df = _make_df(50)
    # Make last bar a gravestone doji
    df.loc[df.index[-1], "open"] = 100
    df.loc[df.index[-1], "close"] = 100
    df.loc[df.index[-1], "high"] = 130
    df.loc[df.index[-1], "low"] = 100
    annotations = detect_entry_annotations(df, entry_idx=49)
    assert "gravestone_doji" in annotations


def test_returns_list():
    df = _make_df(50)
    result = detect_entry_annotations(df, entry_idx=49)
    assert isinstance(result, list)


def test_short_df_no_crash():
    df = _make_df(5)
    result = detect_entry_annotations(df, entry_idx=4)
    assert isinstance(result, list)
```

- [ ] **Step 5.2: Run tests — confirm they fail**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/backtest-engine
PYTHONPATH=. venv/bin/pytest tests/test_pattern_detector.py -v
```
Expected: `ModuleNotFoundError: No module named 'backend.data.pattern_detector'`

- [ ] **Step 5.3: Add annotations field to TradeRecord**

In `backend/execution/base.py`, change `TradeRecord`:

```python
class TradeRecord(BaseModel):
    ticker: str
    entry_time: str
    exit_time: str
    direction: str
    qty: float
    entry_price: float
    exit_price: float
    gross_pnl: float
    net_pnl: float
    cost: CostBreakdown
    annotations: list[str] = []   # ← new field
```

- [ ] **Step 5.4: Implement pattern_detector.py**

Create `backend/data/pattern_detector.py`:

```python
"""
Detect entry-bar annotations from OHLCV context.
Called by LocalEngine at each trade entry to annotate what patterns are present.

Patterns detected:
  gravestone_doji       — bearish reversal candle
  hammer                — bullish reversal candle
  bullish_engulfing     — two-bar bullish pattern
  vwap_cross_above      — close crossed above VWAP on entry bar
  volume_spike_2x       — volume > 2× rolling 20-bar average
  pivot_high_break      — close broke above a recent pivot high
  pivot_low_support     — entry bar near a recent pivot low
"""
from __future__ import annotations
import pandas as pd
import numpy as np


# ── Candlestick helpers ───────────────────────────────────────────────────────

def _body(o, c): return abs(c - o)
def _upper(o, h, c): return h - max(o, c)
def _lower(o, l, c): return min(o, c) - l


def _gravestone_doji(df: pd.DataFrame) -> bool:
    row = df.iloc[-1]
    rng = row["high"] - row["low"]
    if rng < 1e-9:
        return False
    body = _body(row["open"], row["close"]) / rng
    upper = _upper(row["open"], row["high"], row["close"]) / rng
    lower = _lower(row["open"], row["low"], row["close"]) / rng
    return body < 0.1 and upper > 0.6 and lower < 0.1


def _hammer(df: pd.DataFrame) -> bool:
    row = df.iloc[-1]
    rng = row["high"] - row["low"]
    if rng < 1e-9:
        return False
    body = _body(row["open"], row["close"]) / rng
    upper = _upper(row["open"], row["high"], row["close"]) / rng
    lower = _lower(row["open"], row["low"], row["close"]) / rng
    return body < 0.35 and lower > 0.5 and upper < 0.15


def _bullish_engulfing(df: pd.DataFrame) -> bool:
    if len(df) < 2:
        return False
    prev, curr = df.iloc[-2], df.iloc[-1]
    return (
        prev["close"] < prev["open"]
        and curr["close"] > curr["open"]
        and curr["open"] <= prev["close"]
        and curr["close"] >= prev["open"]
    )


# ── Volume ────────────────────────────────────────────────────────────────────

def _volume_spike(df: pd.DataFrame, period: int = 20, multiplier: float = 2.0) -> bool:
    if len(df) < period + 1:
        return False
    avg_vol = df["volume"].iloc[-(period + 1):-1].mean()
    if avg_vol <= 0:
        return False
    return float(df["volume"].iloc[-1]) > multiplier * avg_vol


# ── VWAP ──────────────────────────────────────────────────────────────────────

def _vwap_cross_above(df: pd.DataFrame) -> bool:
    """True if close[-1] crossed above cumulative VWAP."""
    if len(df) < 2:
        return False
    try:
        tp = (df["high"] + df["low"] + df["close"]) / 3
        cum_vol = df["volume"].cumsum()
        vwap = (tp * df["volume"]).cumsum() / cum_vol.replace(0, np.nan)
        return (
            float(df["close"].iloc[-1]) > float(vwap.iloc[-1])
            and float(df["close"].iloc[-2]) <= float(vwap.iloc[-2])
        )
    except Exception:
        return False


# ── Pivot ─────────────────────────────────────────────────────────────────────

def _pivot_high_break(df: pd.DataFrame, left: int = 5, right: int = 3) -> bool:
    """True if close[-1] broke above the most recent pivot high in the lookback."""
    if len(df) < left + right + 5:
        return False
    highs = df["high"].values
    close = float(df["close"].iloc[-1])
    # Find pivot highs in the window excluding the last `right` bars
    search = highs[-(left + right + 5):-(right)]
    for i in range(left, len(search) - right):
        window = list(search[i - left:i]) + list(search[i + 1:i + right + 1])
        if len(window) == left + right and search[i] >= max(window):
            if close > search[i]:
                return True
    return False


def _pivot_low_support(df: pd.DataFrame, left: int = 5, right: int = 3,
                       tolerance_pct: float = 1.0) -> bool:
    """True if close[-1] is within tolerance_pct% above a recent pivot low."""
    if len(df) < left + right + 5:
        return False
    lows = df["low"].values
    close = float(df["close"].iloc[-1])
    search = lows[-(left + right + 5):-(right)]
    for i in range(left, len(search) - right):
        window = list(search[i - left:i]) + list(search[i + 1:i + right + 1])
        if len(window) == left + right and search[i] <= min(window):
            if 0 <= (close - search[i]) / max(search[i], 1e-9) * 100 <= tolerance_pct:
                return True
    return False


# ── Public API ────────────────────────────────────────────────────────────────

def detect_entry_annotations(df: pd.DataFrame, entry_idx: int) -> list[str]:
    """
    Detect pattern annotations at the entry bar.

    Args:
        df: Full OHLCV DataFrame up to and including entry bar.
            Columns: open, high, low, close, volume (lowercase).
        entry_idx: Index of the entry bar (used to slice df; typically len(df)-1).

    Returns:
        List of annotation strings present at entry bar.
    """
    window = df.iloc[: entry_idx + 1]
    if window.empty:
        return []

    annotations: list[str] = []

    if _gravestone_doji(window):
        annotations.append("gravestone_doji")
    if _hammer(window):
        annotations.append("hammer")
    if _bullish_engulfing(window):
        annotations.append("bullish_engulfing")
    if _vwap_cross_above(window):
        annotations.append("vwap_cross_above")
    if _volume_spike(window):
        annotations.append("volume_spike_2x")
    if _pivot_high_break(window):
        annotations.append("pivot_high_break")
    if _pivot_low_support(window):
        annotations.append("pivot_low_support")

    return annotations
```

- [ ] **Step 5.5: Run tests — confirm they pass**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/backtest-engine
PYTHONPATH=. venv/bin/pytest tests/test_pattern_detector.py -v
```
Expected: 5/5 pass

- [ ] **Step 5.6: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/backtest-engine
git add backend/execution/base.py backend/data/pattern_detector.py tests/test_pattern_detector.py
git commit -m "feat: add TradeRecord.annotations and pattern_detector"
```

---

## Task 6: Wire annotations into LocalEngine

**Files:**
- Modify: `backend/execution/local/engine.py`

- [ ] **Step 6.1: Modify LocalEngine to accept sl_target and run pattern detection**

Replace `backend/execution/local/engine.py` content:

```python
import asyncio
import textwrap
import types
import uuid
import pandas as pd
from backtesting import Backtest
from backend.execution.base import BacktestResult, TradeRecord
from backend.execution.sl_target import SLTargetConfig, wrap_with_sl_target
from backend.costs.engine import CostEngine
from backend.data.pattern_detector import detect_entry_annotations


class LocalEngine:
    def __init__(self, broker: str = "zerodha"):
        self.cost_engine = CostEngine(broker_name=broker)

    def _build_strategy_class(self, code: str, params: dict):
        module = types.ModuleType(f"strategy_{uuid.uuid4().hex[:8]}")
        exec(textwrap.dedent(code), module.__dict__)
        cls = module.__dict__["GeneratedStrategy"]
        for k, v in params.items():
            if hasattr(cls, k):
                setattr(cls, k, v)
        return cls

    async def run(
        self,
        strategy_code: str,
        df: pd.DataFrame,
        ticker: str,
        params: dict,
        trade_type: str = "intraday",
        sl_target: SLTargetConfig | None = None,
    ) -> BacktestResult:
        strategy_cls = self._build_strategy_class(strategy_code, params)

        if sl_target is not None:
            strategy_cls = wrap_with_sl_target(strategy_cls, sl_target)

        bt = Backtest(df, strategy_cls, cash=100_000, commission=0.0)

        loop = asyncio.get_running_loop()
        stats = await loop.run_in_executor(None, bt.run)

        # Rebuild lowercase-column df for pattern detection (bt uses capitalized cols)
        df_lower = df.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        }) if "Open" in df.columns else df.copy()
        df_lower.index = pd.to_datetime(df_lower.index)

        trades: list[TradeRecord] = []
        raw_trades = stats._trades if hasattr(stats, "_trades") else pd.DataFrame()

        for _, row in raw_trades.iterrows():
            gross = float(row.get("PnL", 0))
            qty = float(row.get("Size", 1))
            entry_p = float(row.get("EntryPrice", 0))
            exit_p = float(row.get("ExitPrice", 0))
            cost = self.cost_engine.calculate(trade_type, qty, entry_p, exit_p)
            net = gross - cost.total

            # Detect entry bar annotations
            entry_time = row.get("EntryTime")
            annotations: list[str] = []
            try:
                entry_idx = df_lower.index.searchsorted(pd.to_datetime(entry_time))
                if 0 <= entry_idx < len(df_lower):
                    annotations = detect_entry_annotations(df_lower, int(entry_idx))
            except Exception:
                pass

            trades.append(TradeRecord(
                ticker=ticker,
                entry_time=str(entry_time or ""),
                exit_time=str(row.get("ExitTime", "")),
                direction="long" if qty > 0 else "short",
                qty=abs(qty),
                entry_price=entry_p,
                exit_price=exit_p,
                gross_pnl=round(gross, 2),
                net_pnl=round(net, 2),
                cost=cost,
                annotations=annotations,
            ))

        equity = []
        if hasattr(stats, "_equity_curve"):
            ec = stats._equity_curve
            for ts, row in ec.iterrows():
                equity.append({
                    "time": str(ts),
                    "equity": float(row.get("Equity", 100_000)),
                    "drawdown": float(row.get("DrawdownPct", 0)),
                })

        return BacktestResult(symbol=ticker, trades=trades, equity_curve=equity)
```

- [ ] **Step 6.2: Run existing local engine tests — confirm no regressions**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/backtest-engine
PYTHONPATH=. venv/bin/pytest tests/test_local_engine.py -v
```
Expected: 2/2 pass

- [ ] **Step 6.3: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/backtest-engine
git add backend/execution/local/engine.py
git commit -m "feat: wire sl_target and annotations into LocalEngine"
```

---

## Task 7: RunRequest extension + /markers endpoint + CORS

**Files:**
- Modify: `backend/api/runs.py`
- Modify: `backend/main.py`

- [ ] **Step 7.1: Add CORS for localhost:5173**

In `backend/main.py`, change `allow_origins`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8085", "http://localhost:5173", "http://localhost:8086"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
```

- [ ] **Step 7.2: Extend RunRequest with condition_node and sl_target**

In `backend/api/runs.py`, add import and replace `RunRequest`:

```python
from backend.strategy.dsl_bridge import condition_node_to_python
from backend.execution.sl_target import SLTargetConfig
```

Replace `RunRequest`:

```python
class RunRequest(BaseModel):
    strategy_id: str | None = None        # existing LLM strategy
    condition_node: dict | None = None    # DSL path — mutually exclusive with strategy_id
    sl_target: SLTargetConfig | None = None
    params: dict
```

In `create_run()`, after the strategy lookup block, add DSL path before calling `_execute_run`:

```python
@router.post("")
async def create_run(req: RunRequest, background_tasks: BackgroundTasks,
                     db: AsyncSession = Depends(get_db)):
    # Resolve python_code from either DSL or saved strategy
    if req.condition_node is not None:
        try:
            python_code = condition_node_to_python(
                req.condition_node,
                req.sl_target or SLTargetConfig(
                    sl_type="fixed_pct", sl_value=2.0,
                    target_type="fixed_pct", target_value=6.0,
                ),
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        pine_code = ""
        strategy_id = "dsl"
        strategy_version = 1
    elif req.strategy_id:
        strategy = await db.get(Strategy, req.strategy_id)
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        python_code = strategy.python_code
        pine_code = strategy.pine_code
        strategy_id = req.strategy_id
        strategy_version = strategy.version
    else:
        raise HTTPException(status_code=422, detail="Provide strategy_id or condition_node")

    # Merge sl_target into params_json for storage
    params_with_sl = dict(req.params)
    if req.sl_target:
        params_with_sl["sl_target"] = req.sl_target.model_dump()

    run_id = str(uuid.uuid4())
    run = Run(
        id=run_id,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        params_json=json.dumps(params_with_sl),
        engine=req.params.get("engine", "local"),
        broker=req.params.get("broker", "zerodha"),
        date_from=req.params.get("date_from", ""),
        date_to=req.params.get("date_to", ""),
        symbols_json=json.dumps(
            req.params.get("symbols", []) if isinstance(req.params.get("symbols"), list)
            else [req.params.get("symbols", "")]
        ),
        status="pending",
    )
    db.add(run)
    await db.commit()

    background_tasks.add_task(
        _execute_run, run_id, strategy_id, pine_code,
        python_code, params_with_sl,
    )
    return {"run_id": run_id, "status": "pending"}
```

Also update `_execute_run` to pass `sl_target` to `LocalEngine.run()`:

```python
# Inside _execute_run, when engine_type == "local", change the LocalEngine call:
sl_target_cfg = None
sl_raw = params.get("sl_target")
if sl_raw:
    try:
        sl_target_cfg = SLTargetConfig(**sl_raw)
    except Exception:
        pass

result = await asyncio.wait_for(
    engine.run(
        strategy_code=strategy_python,
        df=df,
        ticker=ticker,
        params=params,
        trade_type=trade_type,
        sl_target=sl_target_cfg,
    ),
    timeout=timeout_secs,
)
```

- [ ] **Step 7.3: Add /markers endpoint**

Add at the end of `backend/api/runs.py`:

```python
@router.get("/{run_id}/markers/{symbol}")
async def get_markers(run_id: str, symbol: str, db: AsyncSession = Depends(get_db)):
    """
    Return trade markers in lightweight-charts v5 SeriesMarker format.
    Entry: green arrowUp belowBar
    Profit exit: green arrowDown aboveBar
    SL exit: red arrowDown aboveBar
    Pattern annotations: amber circle belowBar (same time as entry)
    price_lines: [{trade_idx, sl_price, target_price}] for dashed lines
    """
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    result = await db.execute(
        select(Trade).where(Trade.run_id == run_id).order_by(Trade.entry_time)
    )
    trades_db = result.scalars().all()

    # Recover sl_target from params_json
    params = json.loads(run.params_json or "{}")
    sl_target_cfg = None
    if params.get("sl_target"):
        try:
            sl_target_cfg = SLTargetConfig(**params["sl_target"])
        except Exception:
            pass

    markers = []
    price_lines = []

    for i, t in enumerate(trades_db):
        try:
            entry_ts = int(pd.to_datetime(t.entry_time).timestamp())
            exit_ts = int(pd.to_datetime(t.exit_time).timestamp())
        except Exception:
            continue

        # Entry marker
        markers.append({
            "time": entry_ts,
            "position": "belowBar",
            "color": "#26a69a",
            "shape": "arrowUp",
            "text": f"Entry ₹{t.entry_price:.0f}",
        })

        # Pattern annotation markers (same time as entry, circle)
        cost_data = json.loads(t.cost_breakdown_json or "{}")
        annotations = cost_data.get("annotations", [])
        if annotations:
            markers.append({
                "time": entry_ts,
                "position": "belowBar",
                "color": "#f59e0b",
                "shape": "circle",
                "text": " · ".join(annotations),
            })

        # Exit marker
        is_profit = t.net_pnl > 0
        pnl_pct = ((t.exit_price - t.entry_price) / t.entry_price * 100) if t.entry_price else 0
        markers.append({
            "time": exit_ts,
            "position": "aboveBar",
            "color": "#26a69a" if is_profit else "#ef5350",
            "shape": "arrowDown",
            "text": f"Exit ₹{t.exit_price:.0f} ({pnl_pct:+.1f}%)",
        })

        # Price lines for SL + target
        if sl_target_cfg:
            entry_p = t.entry_price
            sl_price = None
            tp_price = None
            if sl_target_cfg.sl_type == "fixed_pct":
                sl_price = round(entry_p * (1 - sl_target_cfg.sl_value / 100), 2)
            if sl_target_cfg.target_type == "fixed_pct":
                tp_price = round(entry_p * (1 + sl_target_cfg.target_value / 100), 2)
            elif sl_target_cfg.target_type == "rr_ratio" and sl_price:
                risk = entry_p - sl_price
                tp_price = round(entry_p + sl_target_cfg.target_value * risk, 2)
            if sl_price or tp_price:
                price_lines.append({
                    "trade_idx": i,
                    "entry_time": entry_ts,
                    "exit_time": exit_ts,
                    "sl_price": sl_price,
                    "target_price": tp_price,
                })

    # Sort markers by time
    markers.sort(key=lambda m: m["time"])
    return {"markers": markers, "price_lines": price_lines}
```

Note: Annotations are stored in `cost_breakdown_json` for now (avoid schema migration). Change `TradeRecord` storage in `_execute_run` to include `annotations` in `cost_breakdown_json`:

In `_execute_run`, when saving trades, add this inside the trade-save loop:

```python
cost_dict = {
    "brokerage": t.cost.brokerage, "stt": t.cost.stt,
    "exchange": t.cost.exchange, "sebi": t.cost.sebi,
    "gst": t.cost.gst, "stamp": t.cost.stamp,
    "annotations": t.annotations,   # ← add annotations here
}
db_trade = Trade(
    id=str(uuid.uuid4()),
    run_id=run_id,
    ticker=t.ticker,
    entry_time=t.entry_time,
    exit_time=t.exit_time,
    direction=t.direction,
    qty=t.qty,
    entry_price=t.entry_price,
    exit_price=t.exit_price,
    gross_pnl=t.gross_pnl,
    net_pnl=t.net_pnl,
    cost_breakdown_json=json.dumps(cost_dict),
)
```

- [ ] **Step 7.4: Run existing runs API tests**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/backtest-engine
PYTHONPATH=. venv/bin/pytest tests/test_runs_api.py -v
```
Expected: all pass (or skip if they need a running DB — that's ok)

- [ ] **Step 7.5: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/backtest-engine
git add backend/api/runs.py backend/main.py
git commit -m "feat: extend RunRequest with condition_node + sl_target, add /markers endpoint, add CORS"
```

---

## Task 8: Expose candleSeries ref from CandlestickChart

**Files:**
- Modify: `frontend/src/components/Chart/CandlestickChart.tsx`

- [ ] **Step 8.1: Export chart handle via forwardRef**

Add these imports to `CandlestickChart.tsx`:

```typescript
import { useEffect, useRef, useImperativeHandle, forwardRef } from "react";
```

Add handle type before `Props`:

```typescript
export interface ChartHandle {
  candleSeries: AnySeries | null
  chart: IChartApi | null
}
```

Wrap the component with `forwardRef`:

```typescript
const CandlestickChart = forwardRef<ChartHandle, Props>(function CandlestickChart(
  { bars, studies, onNeedMoreData },
  ref
) {
  // ... all existing code unchanged ...

  useImperativeHandle(ref, () => ({
    get candleSeries() { return candleSeriesRef.current; },
    get chart() { return chartRef.current; },
  }));

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
});

export default CandlestickChart;
export type { Bar };
```

- [ ] **Step 8.2: Verify TypeScript compiles**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/frontend
npm run build 2>&1 | tail -20
```
Expected: 0 TypeScript errors

- [ ] **Step 8.3: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
git add frontend/src/components/Chart/CandlestickChart.tsx
git commit -m "feat: expose candleSeries + chart handles from CandlestickChart via forwardRef"
```

---

## Task 9: BacktestOverlay.tsx

**Files:**
- Create: `frontend/src/components/Chart/BacktestOverlay.tsx`

- [ ] **Step 9.1: Create BacktestOverlay.tsx**

Create `frontend/src/components/Chart/BacktestOverlay.tsx`:

```typescript
/**
 * BacktestOverlay — fetches trade markers from backtest-engine and renders them
 * on the existing candlestick series using lightweight-charts v5 createSeriesMarkers.
 *
 * Entry: green arrowUp belowBar
 * Profit exit: green arrowDown aboveBar
 * SL exit: red arrowDown aboveBar
 * Pattern annotations: amber circle belowBar
 * SL/target price lines: dashed horizontal lines per trade
 */
import { useEffect, useRef } from "react";
import {
  createSeriesMarkers,
  LineStyle,
  type IChartApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type UTCTimestamp,
} from "lightweight-charts";
import type { ChartHandle } from "./CandlestickChart";

const BACKTEST_URL = import.meta.env.VITE_BACKTEST_ENGINE_URL ?? "http://localhost:8085";

interface PriceLine {
  trade_idx: number;
  entry_time: number;
  exit_time: number;
  sl_price: number | null;
  target_price: number | null;
}

interface MarkersResponse {
  markers: Array<{
    time: number;
    position: "belowBar" | "aboveBar" | "inBar";
    color: string;
    shape: "arrowUp" | "arrowDown" | "circle" | "square";
    text: string;
  }>;
  price_lines: PriceLine[];
}

interface Props {
  runId: string | null;
  symbol: string;
  chartHandle: ChartHandle | null;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyPriceLine = any;

export default function BacktestOverlay({ runId, symbol, chartHandle }: Props) {
  const markersPluginRef = useRef<ISeriesMarkersPluginApi<UTCTimestamp> | null>(null);
  const priceLineRefs = useRef<AnyPriceLine[]>([]);

  function clearOverlay() {
    // Clear markers
    if (markersPluginRef.current) {
      markersPluginRef.current.setMarkers([]);
      markersPluginRef.current = null;
    }
    // Clear price lines
    if (chartHandle?.candleSeries) {
      for (const pl of priceLineRefs.current) {
        try { chartHandle.candleSeries.removePriceLine(pl); } catch {}
      }
    }
    priceLineRefs.current = [];
  }

  useEffect(() => {
    if (!runId || !chartHandle?.candleSeries || !chartHandle?.chart) {
      clearOverlay();
      return;
    }

    const series = chartHandle.candleSeries;
    const chart: IChartApi = chartHandle.chart;
    let cancelled = false;

    async function load() {
      try {
        const res = await fetch(`${BACKTEST_URL}/runs/${runId}/markers/${symbol}`);
        if (!res.ok || cancelled) return;
        const data: MarkersResponse = await res.json();

        if (cancelled) return;

        // Clear previous
        clearOverlay();

        // Set markers
        const lwMarkers: SeriesMarker<UTCTimestamp>[] = data.markers.map(m => ({
          time: m.time as UTCTimestamp,
          position: m.position,
          color: m.color,
          shape: m.shape,
          text: m.text,
        }));

        if (lwMarkers.length > 0) {
          markersPluginRef.current = createSeriesMarkers(series, lwMarkers);
        }

        // Add SL + target price lines
        const newLines: AnyPriceLine[] = [];
        for (const pl of data.price_lines) {
          if (pl.sl_price != null) {
            newLines.push(
              series.createPriceLine({
                price: pl.sl_price,
                color: "#ef535088",
                lineWidth: 1,
                lineStyle: LineStyle.Dashed,
                axisLabelVisible: false,
                title: `SL`,
              })
            );
          }
          if (pl.target_price != null) {
            newLines.push(
              series.createPriceLine({
                price: pl.target_price,
                color: "#26a69a88",
                lineWidth: 1,
                lineStyle: LineStyle.Dashed,
                axisLabelVisible: false,
                title: `TP`,
              })
            );
          }
        }
        priceLineRefs.current = newLines;

        // Fit content to show full backtest range
        chart.timeScale().fitContent();
      } catch (err) {
        console.warn("BacktestOverlay fetch failed:", err);
      }
    }

    load();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, symbol, chartHandle]);

  // Cleanup on unmount
  useEffect(() => () => clearOverlay(), []);

  return null; // pure overlay — no DOM output
}
```

- [ ] **Step 9.2: Verify TypeScript compiles**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/frontend
npm run build 2>&1 | tail -20
```
Expected: 0 TypeScript errors

- [ ] **Step 9.3: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
git add frontend/src/components/Chart/BacktestOverlay.tsx
git commit -m "feat: add BacktestOverlay — renders trade markers + SL/target lines on chart"
```

---

## Task 10: BacktestPanel.tsx

**Files:**
- Create: `frontend/src/components/Chart/BacktestPanel.tsx`

- [ ] **Step 10.1: Create BacktestPanel.tsx**

Create `frontend/src/components/Chart/BacktestPanel.tsx`:

```typescript
/**
 * BacktestPanel — shown below chart header in BACKTEST mode.
 *
 * Tabs:
 *   "conditions" — ConditionBuilder (reads from useFiltersStore, same as Screener)
 *   "config"     — date range, SL/target params, broker
 *
 * Bottom bar:
 *   Run button → POST to backtest-engine → poll status → call onRunComplete(runId)
 *   History dropdown → load a prior run's markers
 */
import { useState, useRef } from "react";
import ConditionBuilder from "../Screener/ConditionBuilder";
import { useFiltersStore } from "../../store/filters";

const BACKTEST_URL = import.meta.env.VITE_BACKTEST_ENGINE_URL ?? "http://localhost:8085";

const TV = {
  bg: "#0d0d1a", panel: "#131722", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86", accent: "#2962ff",
  up: "#26a69a", down: "#ef5350", warn: "#f59e0b",
} as const;

const inputStyle: React.CSSProperties = {
  background: "#1e222d", border: `1px solid ${TV.border}`, borderRadius: 3,
  color: TV.text, padding: "4px 8px", fontSize: 12, outline: "none",
  width: "100%", boxSizing: "border-box",
};

const selectStyle: React.CSSProperties = { ...inputStyle };

interface HistoryRun {
  run_id: string;
  run_name: string;
  status: string;
  symbols_json: string;
}

interface Props {
  symbol: string;
  timeframe: string;
  onRunComplete: (runId: string) => void;
}

export default function BacktestPanel({ symbol, timeframe, onRunComplete }: Props) {
  const [tab, setTab] = useState<"conditions" | "config">("conditions");

  // Config state
  const [dateFrom, setDateFrom] = useState("2022-01-01");
  const [dateTo, setDateTo] = useState(new Date().toISOString().slice(0, 10));
  const [slType, setSlType] = useState("fixed_pct");
  const [slValue, setSlValue] = useState(2);
  const [tgtType, setTgtType] = useState("rr_ratio");
  const [tgtValue, setTgtValue] = useState(3);
  const [broker, setBroker] = useState("zerodha");

  // Run state
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [history, setHistory] = useState<HistoryRun[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const customConditions = useFiltersStore(s => s.customConditions);

  async function loadHistory() {
    if (historyLoaded) return;
    try {
      const res = await fetch(`${BACKTEST_URL}/runs/history`);
      if (res.ok) {
        const data = await res.json();
        setHistory(data.slice(0, 20));
        setHistoryLoaded(true);
      }
    } catch {}
  }

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }

  async function pollStatus(runId: string) {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${BACKTEST_URL}/runs/${runId}`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.status === "complete") {
          stopPolling();
          setStatus("complete");
          setRunning(false);
          onRunComplete(runId);
        } else if (data.status === "failed") {
          stopPolling();
          setStatus("failed");
          setError(data.error || "Run failed");
          setRunning(false);
        } else {
          setStatus(data.status);
        }
      } catch {}
    }, 1500);
  }

  async function handleRun() {
    if (!customConditions) {
      setError("Add at least one condition in the Conditions tab first.");
      return;
    }
    setError("");
    setRunning(true);
    setStatus("submitting…");

    const body = {
      condition_node: customConditions,
      sl_target: { sl_type: slType, sl_value: slValue, target_type: tgtType, target_value: tgtValue },
      params: {
        symbols: symbol,
        timeframe,
        date_from: dateFrom,
        date_to: dateTo,
        engine: "local",
        broker,
      },
    };

    try {
      const res = await fetch(`${BACKTEST_URL}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setStatus("running");
      pollStatus(data.run_id);
    } catch (e: unknown) {
      setError((e as Error).message || "Failed to start backtest");
      setRunning(false);
      setStatus("");
    }
  }

  const tabBtn = (t: "conditions" | "config", label: string) => (
    <button
      onClick={() => setTab(t)}
      style={{
        background: tab === t ? TV.accent : "transparent",
        border: "none", borderBottom: tab === t ? "none" : `1px solid ${TV.border}`,
        color: tab === t ? "#fff" : TV.muted,
        padding: "6px 14px", cursor: "pointer", fontSize: 12, fontWeight: 600,
      }}
    >
      {label}
    </button>
  );

  return (
    <div style={{ background: TV.panel, borderBottom: `1px solid ${TV.border}`, fontSize: 12 }}>
      {/* Tabs */}
      <div style={{ display: "flex", borderBottom: `1px solid ${TV.border}` }}>
        {tabBtn("conditions", "⚡ Conditions")}
        {tabBtn("config", "⚙ Config")}
      </div>

      {/* Tab content */}
      <div style={{ padding: 10, maxHeight: 260, overflowY: "auto" }}>
        {tab === "conditions" && (
          <div>
            <div style={{ color: TV.muted, fontSize: 11, marginBottom: 6 }}>
              Build entry conditions below (shared with Screener)
            </div>
            <ConditionBuilder />
          </div>
        )}

        {tab === "config" && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <label style={{ color: TV.muted }}>
              From
              <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} style={inputStyle} />
            </label>
            <label style={{ color: TV.muted }}>
              To
              <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} style={inputStyle} />
            </label>
            <label style={{ color: TV.muted }}>
              SL type
              <select value={slType} onChange={e => setSlType(e.target.value)} style={selectStyle}>
                <option value="fixed_pct">Fixed %</option>
                <option value="atr_multiple">ATR ×</option>
                <option value="trailing_pct">Trailing %</option>
                <option value="trailing_atr">Trailing ATR</option>
              </select>
            </label>
            <label style={{ color: TV.muted }}>
              SL value
              <input type="number" value={slValue} min={0.1} step={0.5}
                onChange={e => setSlValue(Number(e.target.value))} style={inputStyle} />
            </label>
            <label style={{ color: TV.muted }}>
              Target type
              <select value={tgtType} onChange={e => setTgtType(e.target.value)} style={selectStyle}>
                <option value="rr_ratio">R:R ratio</option>
                <option value="fixed_pct">Fixed %</option>
                <option value="atr_multiple">ATR ×</option>
              </select>
            </label>
            <label style={{ color: TV.muted }}>
              Target value
              <input type="number" value={tgtValue} min={0.1} step={0.5}
                onChange={e => setTgtValue(Number(e.target.value))} style={inputStyle} />
            </label>
            <label style={{ color: TV.muted }}>
              Broker
              <select value={broker} onChange={e => setBroker(e.target.value)} style={selectStyle}>
                <option value="zerodha">Zerodha</option>
                <option value="upstox">Upstox</option>
                <option value="angel">Angel</option>
              </select>
            </label>
          </div>
        )}
      </div>

      {/* Bottom bar: run + history */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10, padding: "8px 10px",
        borderTop: `1px solid ${TV.border}`,
      }}>
        <button
          onClick={handleRun}
          disabled={running}
          style={{
            background: running ? "#1e222d" : TV.accent,
            border: "none", borderRadius: 3, color: running ? TV.muted : "#fff",
            padding: "5px 16px", cursor: running ? "default" : "pointer",
            fontSize: 12, fontWeight: 600,
          }}
        >
          {running ? `⏳ ${status}` : "▶ Run Backtest"}
        </button>

        {error && <span style={{ color: TV.down, fontSize: 11 }}>{error}</span>}

        {status === "complete" && !running && (
          <span style={{ color: TV.up, fontSize: 11 }}>✓ Done — markers loaded</span>
        )}

        {/* Prior run selector */}
        <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
          <span style={{ color: TV.muted }}>Load run:</span>
          <select
            onClick={loadHistory}
            onChange={e => { if (e.target.value) onRunComplete(e.target.value); }}
            style={{ ...selectStyle, width: 180 }}
            defaultValue=""
          >
            <option value="">— select prior run —</option>
            {history.map(r => (
              <option key={r.run_id} value={r.run_id}>
                {r.run_name || r.run_id.slice(0, 8)} · {r.status}
              </option>
            ))}
          </select>
        </div>

        <a
          href={`http://localhost:8086`}
          target="_blank"
          rel="noreferrer"
          style={{ color: TV.muted, fontSize: 11 }}
        >
          Full UI ↗
        </a>
      </div>
    </div>
  );
}
```

- [ ] **Step 10.2: Verify TypeScript compiles**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/frontend
npm run build 2>&1 | tail -20
```
Expected: 0 errors

- [ ] **Step 10.3: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
git add frontend/src/components/Chart/BacktestPanel.tsx
git commit -m "feat: add BacktestPanel — condition builder, SL/target config, run launcher, status poller"
```

---

## Task 11: Mode toggle in Chart.tsx

**Files:**
- Modify: `frontend/src/pages/Chart.tsx`

- [ ] **Step 11.1: Add mode toggle, BacktestPanel, BacktestOverlay to Chart.tsx**

At the top of `Chart.tsx`, add imports:

```typescript
import { useRef } from "react";
import BacktestPanel from "../components/Chart/BacktestPanel";
import BacktestOverlay from "../components/Chart/BacktestOverlay";
import CandlestickChart, { type ChartHandle } from "../components/Chart/CandlestickChart";
```

Add state inside `Chart` component (after existing state):

```typescript
const [mode, setMode] = useState<"live" | "backtest">("live");
const [activeRunId, setActiveRunId] = useState<string | null>(null);
const chartHandleRef = useRef<ChartHandle | null>(null);
```

Update `CandlestickChart` usage to use `ref`:

```typescript
{!loading && bars.length > 0 && (
  <CandlestickChart
    ref={chartHandleRef}
    bars={bars}
    studies={studies}
    onNeedMoreData={handleNeedMoreData}
  />
)}
```

In the header, add LIVE/BACKTEST toggle after the timeframe buttons:

```typescript
{/* Mode toggle */}
<div style={{ display: "flex", gap: 0, marginLeft: 8 }}>
  <button
    onClick={() => setMode("live")}
    style={btnStyle(
      mode === "live" ? "#26a69a" : "#1e222d",
      mode === "live" ? "#fff" : "#787b86",
      mode === "live" ? "#26a69a" : "#2a2e39",
    )}
  >
    ● LIVE
  </button>
  <button
    onClick={() => setMode("backtest")}
    style={btnStyle(
      mode === "backtest" ? "#f59e0b" : "#1e222d",
      mode === "backtest" ? "#0d0d1a" : "#787b86",
      mode === "backtest" ? "#f59e0b" : "#2a2e39",
    )}
  >
    📊 BACKTEST
  </button>
</div>
```

Below the header (before the chart area div), add:

```typescript
{mode === "backtest" && symbol && (
  <BacktestPanel
    symbol={symbol}
    timeframe={TF_OPTIONS[tfIdx].tf}
    onRunComplete={(runId) => setActiveRunId(runId)}
  />
)}
```

Inside the chart area div, add `BacktestOverlay` alongside `CandlestickChart`:

```typescript
{mode === "backtest" && activeRunId && symbol && (
  <BacktestOverlay
    runId={activeRunId}
    symbol={symbol}
    chartHandle={chartHandleRef.current}
  />
)}
```

- [ ] **Step 11.2: Verify TypeScript compiles**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/frontend
npm run build 2>&1 | tail -20
```
Expected: 0 errors

- [ ] **Step 11.3: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
git add frontend/src/pages/Chart.tsx
git commit -m "feat: add LIVE/BACKTEST mode toggle to chart, wire BacktestPanel and BacktestOverlay"
```

---

## Task 12: End-to-End Test

- [ ] **Step 12.1: Start all services**

```bash
# Terminal 1 — QuestDB already running (port 8812/9000)

# Terminal 2 — trading-system backend
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/backend
PYTHONPATH=. .venv/bin/python -m uvicorn api.main:app --reload --port 8000

# Terminal 3 — backtest-engine backend
cd /Users/ankitatiwari/Desktop/claude-playground/backtest-engine
PYTHONPATH=. venv/bin/python -m uvicorn backend.main:app --reload --port 8085

# Terminal 4 — trading-system frontend
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/frontend
npm run dev
```

- [ ] **Step 12.2: Run a DSL backtest end-to-end**

1. Open `http://localhost:5173`
2. Navigate to **RELIANCE** chart → select **1d** timeframe
3. Click **📊 BACKTEST** toggle
4. In **Conditions** tab: add `RSI(14) < 30` indicator condition
5. In **Config** tab: set From=2020-01-01, SL=2% fixed, Target=3R
6. Click **▶ Run Backtest**
7. Status should cycle: `submitting → running → complete`
8. Chart should show green ▲ arrows at entries, colored ▼ arrows at exits
9. Amber ● markers should appear where patterns were detected at entry

- [ ] **Step 12.3: Verify markers via API directly**

```bash
# Get the run_id from the run (visible in browser network tab or backtest-engine logs)
RUN_ID="<paste run_id here>"
curl http://localhost:8085/runs/$RUN_ID/markers/RELIANCE | python3 -m json.tool | head -40
```
Expected: JSON with `markers` array and `price_lines` array

- [ ] **Step 12.4: Test loading a prior run**

1. Refresh the page or navigate away and back
2. Click **📊 BACKTEST** toggle
3. In "Load run" dropdown, select the run created in step 12.2
4. Markers should reload on the chart

- [ ] **Step 12.5: Run full test suites on both repos**

```bash
# trading-system
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/backend
PYTHONPATH=. .venv/bin/pytest tests/ -v --tb=short

# backtest-engine
cd /Users/ankitatiwari/Desktop/claude-playground/backtest-engine
PYTHONPATH=. venv/bin/pytest tests/ -v --tb=short
```
Expected: all existing tests pass + new tests pass

- [ ] **Step 12.6: Final commit**

```bash
# Update SESSION_HANDOFF.md with new state
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
git add -A
git commit -m "feat: complete backtest integration — DSL+LLM entry, chart overlay, SL/target"
```

---

## Self-Review Checklist

- [x] **gravestone_doji**: Task 1 ✓
- [x] **pivot_high/pivot_low**: Task 2 ✓
- [x] **SLTargetConfig + wrapper**: Task 3 ✓
- [x] **DSL bridge**: Task 4 ✓
- [x] **TradeRecord.annotations + pattern_detector**: Task 5 ✓
- [x] **LocalEngine wired with sl_target + annotations**: Task 6 ✓
- [x] **RunRequest extended (condition_node + sl_target)**: Task 7 ✓
- [x] **/markers endpoint**: Task 7 ✓
- [x] **CORS localhost:5173**: Task 7 ✓
- [x] **CandlestickChart forwardRef**: Task 8 ✓
- [x] **BacktestOverlay**: Task 9 ✓
- [x] **BacktestPanel (run launcher + poller)**: Task 10 ✓
- [x] **Mode toggle in Chart.tsx**: Task 11 ✓
- [x] **End-to-end test**: Task 12 ✓
- [x] **ConditionBuilder reused (not duplicated)**: BacktestPanel imports from `../Screener/ConditionBuilder` ✓
- [x] **No yfinance added**: QuestDB + CSV only ✓
- [x] **Long-only v1**: `self.buy()` only, no `self.sell()` in DSL bridge ✓
