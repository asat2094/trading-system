# Backtest Integration Design
*2026-05-28 — updated with full workflow scope*

## Overview

Complete end-to-end backtest workflow entirely within trading-system chart page.
No context switch to backtest-engine UI required.

1. User opens `/chart/:symbol`, clicks **BACKTEST** mode.
2. Builds entry conditions with existing ConditionNode builder **or** selects a prior LLM-generated run.
3. Configures date range + SL/target params, hits **Run**.
4. trading-system POSTs to backtest-engine, polls status, auto-loads markers.
5. Chart shows entry/exit arrows + pattern annotations + SL/target lines directly on candles.

---

## What Already Exists — Do Not Rebuild

| Component | Location | Reused As-Is |
|---|---|---|
| `POST /runs` | backtest-engine `api/runs.py` | Extended (not replaced) |
| `GET /runs/{id}` status poll | backtest-engine | Unchanged |
| `GET /runs/history` run list | backtest-engine | Unchanged — powers run selector |
| `GET /runs/{id}/metrics` | backtest-engine | Unchanged |
| `GET /runs/{id}/trades` | backtest-engine | Unchanged |
| `GET /runs/{id}/equity` | backtest-engine | Unchanged |
| WebSocket `/ws` | backtest-engine `api/ws.py` | Unchanged — optional upgrade from polling |
| `LocalEngine`, `CostEngine`, `MetricsEngine` | backtest-engine | Unchanged |
| `local_ohlcv.py` (QuestDB + CSV) | backtest-engine | Already updated, unchanged |
| `StrategyGenerator` (LLM path) | backtest-engine | Unchanged |
| `ConditionBuilder.tsx` | trading-system Screener | Reused in BacktestPanel |
| `CandlestickChart.tsx` | trading-system | Unchanged — overlay is additive |
| `StudyPanel.tsx` | trading-system | Unchanged |
| 14 indicators, 7 candlestick patterns | trading-system backend | Unchanged (add gravestone_doji) |

---

## Architecture

### Two Entry Paths → One Pipeline

```
Path B (DSL) — from chart                Path A (LLM) — prior run
──────────────────────────               ─────────────────────────
ConditionNode JSON                       strategy_id (saved in SQLite)
built in BacktestPanel                   from run selector dropdown
          │                                        │
          ▼                                        │
  dsl_bridge.py (new)                              │
  → python_code string                             │
          │                                        │
          └──────────────┬─────────────────────────┘
                         ▼
              POST /runs (extended)
              body: { condition_node?, strategy_id?,
                      sl_target, params }
                         │
                         ▼
              _execute_run() — unchanged
              LocalEngine + CostEngine
                         │
                         ▼
              BacktestResult + pattern_detector (new)
              → TradeRecord.annotations[]
                         │
                         ▼
              SQLite: runs / trades / metrics
```

### Full Workflow

```
trading-system chart (localhost:5173)
  │
  │  1. POST /runs  ─────────────────────► backtest-engine (localhost:8085)
  │  2. Poll GET /runs/{id}               status: pending → running → complete
  │  3. GET /runs/{id}/markers/{symbol} ◄─ markers in lw-charts format
  │
  ▼
BacktestOverlay.tsx
createSeriesMarkers(candleSeries, markers)
  ▲ entry  ▼ exit  ● pattern  --- SL/target lines
```

---

## Services & Ports

| Service | Port |
|---|---|
| trading-system backend | 8000 |
| trading-system frontend | 5173 |
| backtest-engine backend | 8085 |
| backtest-engine frontend | 8086 |

backtest-engine CORS must allow `http://localhost:5173`.
`VITE_BACKTEST_ENGINE_URL` env var controls the URL (default `http://localhost:8085`).

---

## SL / Target — Configurable Per Run

```python
class SLTargetConfig(BaseModel):
    sl_type:      Literal["fixed_pct", "atr_multiple", "trailing_pct", "trailing_atr"]
    sl_value:     float    # % or ATR multiplier
    target_type:  Literal["fixed_pct", "rr_ratio", "atr_multiple"]
    target_value: float    # %, R-multiple, or ATR multiplier
```

Injected as a wrapper around the Strategy class in `LocalEngine.run()`.
Wrapper intercepts `next()`, checks SL/target on every bar independently of strategy logic.
Stored in `Run.params_json`. Rehydrated by `/markers` endpoint to compute price lines.

---

## New Components

### backtest-engine — new files

#### `backend/strategy/dsl_bridge.py`

```python
def condition_node_to_python(node: dict, sl_target: SLTargetConfig) -> str:
    """
    Converts ConditionNode JSON → valid Python string defining GeneratedStrategy(Strategy).
    Walks node tree, emits pandas_ta indicator calls in init(), condition eval in next().
    Supported v1: indicator, crossover, candlestick, volume, trend.
    chart_pattern deferred (look-back incompatible with bar-by-bar).
    Raises ValueError for unsupported types.
    """
```

#### `backend/data/pattern_detector.py`

```python
def detect_entry_annotations(
    df: pd.DataFrame,
    entry_idx: int,
) -> list[str]:
    """
    Run at every entry bar. Returns list of pattern names present.
    Checks: gravestone_doji, hammer, bullish_engulfing,
            vwap_cross_above, volume_spike_2x,
            pivot_high_break, pivot_low_support
    Uses same math as trading-system pattern library.
    """
```

### backtest-engine — modified files

#### `backend/execution/base.py`
Add `annotations: list[str] = []` to `TradeRecord`.

#### `backend/api/runs.py`
Extend `RunRequest`:
```python
class RunRequest(BaseModel):
    strategy_id: str | None = None      # existing LLM-generated strategy
    condition_node: dict | None = None  # NEW: DSL path
    sl_target: SLTargetConfig | None = None  # NEW: configurable SL/target
    params: dict                        # unchanged: symbols, timeframe, date_from, date_to, broker
```

Logic in `create_run`:
- If `condition_node` present → call `condition_node_to_python()` → get `python_code`
- If `strategy_id` present → load from SQLite as before
- Either way: feed `python_code` into `_execute_run()` unchanged

Add new endpoint:
```
GET /runs/{id}/markers/{symbol}
→ { markers: [...], price_lines: [...] }
```

Marker format (lightweight-charts v5 `SeriesMarker`):
```json
{ "time": 1706745600, "position": "belowBar", "color": "#26a69a",
  "shape": "arrowUp", "text": "Entry ₹2481 · RSI<30+EMA×" }
```

#### `backend/main.py`
Add `localhost:5173` to CORS `allow_origins`.

---

### trading-system — new frontend files

#### `frontend/src/components/Chart/BacktestPanel.tsx`

Rendered below chart header when BACKTEST mode active. Contains:
- **Conditions tab**: reuses `ConditionBuilder` component (imported from Screener, not copied)
- **Config tab**: date range (from/to), SL type+value, target type+value, broker selector
- **Run button**: `POST http://$VITE_BACKTEST_ENGINE_URL/runs`
- **Status indicator**: polling `GET /runs/{id}` every 1.5s until `status=complete`
- **Run history dropdown**: `GET /runs/history` — select a prior run to reload its markers

#### `frontend/src/components/Chart/BacktestOverlay.tsx`

```typescript
interface BacktestOverlayProps {
  runId: string | null
  symbol: string
  candleSeries: ISeriesApi<'Candlestick'>
  chart: IChartApi
  onClear: () => void
}
```

- Fetches `GET $VITE_BACKTEST_ENGINE_URL/runs/{runId}/markers/{symbol}`
- Calls `createSeriesMarkers(candleSeries, markers)` — lightweight-charts v5
- Adds `PriceLine` per trade: dashed green (target), dashed red (SL)
- Cleans up markers + price lines on runId change or unmount

### trading-system — modified frontend files

#### `frontend/src/pages/Chart.tsx`
- Add `mode: "live" | "backtest"` state
- Add `[ LIVE ] [ BACKTEST ]` toggle to header (right side, before Indicators button)
- Mount `BacktestPanel` below header when `mode === "backtest"`
- Pass `candleSeriesRef` and `chartRef` down to `BacktestOverlay`
- Expose `candleSeriesRef` from `CandlestickChart` via ref callback (currently internal)

#### `frontend/src/components/Chart/CandlestickChart.tsx`
- Export `candleSeriesRef` to parent via `useImperativeHandle` or ref prop
- No logic changes — purely exposing the existing series ref

---

### trading-system — new backend files

#### `backend/technical/patterns/candlestick.py` (addition)

`gravestone_doji`:
```
body  = |close - open| / (high - low)  < 0.1
upper = (high - max(open, close)) / (high - low) > 0.6
lower = (min(open, close) - low)  / (high - low) < 0.1
confidence = upper_wick_ratio   direction: bearish
```

#### `backend/technical/patterns/levels.py` (addition)

```python
def pivot_highs(df: pd.DataFrame, left: int = 5, right: int = 5) -> list[int]:
    """Indices where high[i] > all highs in left+right window."""

def pivot_lows(df: pd.DataFrame, left: int = 5, right: int = 5) -> list[int]:
    """Indices where low[i] < all lows in left+right window."""
```

Used by `pattern_detector.py` for `pivot_high_break` / `pivot_low_support` annotations.

---

## Build Sequence

| Step | What | Files | Repo |
|---|---|---|---|
| 1 | New patterns | `candlestick.py` + `levels.py` | trading-system |
| 2 | DSL bridge | `dsl_bridge.py` | backtest-engine |
| 3 | SL/target wrapper | `LocalEngine` + `SLTargetConfig` | backtest-engine |
| 4 | Annotations + markers API | `pattern_detector.py`, `base.py`, `runs.py` | backtest-engine |
| 5 | CORS + RunRequest extension | `main.py`, `runs.py` | backtest-engine |
| 6 | Chart series ref exposure | `CandlestickChart.tsx` | trading-system |
| 7 | BacktestOverlay + BacktestPanel | new `.tsx` files | trading-system |
| 8 | Mode toggle wiring | `Chart.tsx` | trading-system |
| 9 | End-to-end test | RELIANCE 1d, RSI<30+EMA cross, 2020–2024 | both |

---

## Tests

**trading-system:**
- `tests/unit/test_candlestick.py` — gravestone_doji: 3 valid + 3 false positives
- `tests/unit/test_levels.py` — pivot_high/low on synthetic OHLCV series

**backtest-engine:**
- `tests/test_dsl_bridge.py` — 3 ConditionNode trees, assert signals fire on known bars
- `tests/test_pattern_detector.py` — annotations on synthetic entry bar
- `tests/test_sl_wrapper.py` — fixed_pct SL exits at correct bar; ATR_multiple target hits correctly

---

## Constraints

- Long-only v1.
- `chart_pattern` ConditionNode type unsupported in DSL bridge v1.
- `ConditionBuilder` imported from Screener path — no duplication.
- `CandlestickChart` series ref exposed via `useImperativeHandle` — no logic changes to chart.

---

## Out of Scope (v1)

- Walk-forward validation UI (engine exists in backtest-engine, no UI trigger)
- Multi-symbol batch from trading-system chart
- Short selling
- Portfolio-level P&L
- Live signal → auto-backtest trigger
