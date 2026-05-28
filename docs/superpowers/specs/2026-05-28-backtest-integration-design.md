# Backtest Integration Design
*2026-05-28*

## Overview

Integrate `backtest-engine` (sidecar FastAPI service) with `trading-system` so that:

1. Users define entry signals via the existing Screener ConditionNode DSL **or** natural-language LLM prompts.
2. `backtest-engine` runs bar-by-bar simulation using `backtesting.py` against QuestDB historical data (286M 1-min bars, 2019–2026).
3. Trade results (entries, exits, pattern annotations) render as overlays on the existing lightweight-charts candlestick chart in `trading-system`.

---

## Architecture

### Two Entry Paths → One Pipeline

```
Path B (DSL)                          Path A (LLM)
─────────────────────                 ─────────────────────────────
ConditionNode JSON                    Natural language prompt
(Screener builder)                    (backtest-engine chat)
        │                                     │
        ▼                                     ▼
dsl_bridge.py                         StrategyGenerator (existing)
(new in backtest-engine)              LLM → Python code
        │                                     │
        └──────────────┬───────────────────────┘
                       ▼
             backtesting.py Strategy class
                       │
          ┌────────────┼────────────────────┐
          ▼            ▼                    ▼
    local_ohlcv.py  CostEngine         SL/Target params
    (QuestDB→CSV)   (Zerodha)          (runtime, configurable)
          │
          ▼
    LocalEngine.run()
          │
          ▼
    BacktestResult → MetricsEngine (quantstats)
          │
          ▼
    SQLite: runs / trades / symbol_results / metrics
          +
    TradeRecord.annotations[]  (patterns at entry bar)
```

### Visualization Bridge

```
backtest-engine
  GET /runs/{id}/markers/{symbol}
       │  returns lightweight-charts marker format
       ▼
trading-system chart
  BacktestOverlay.tsx
  createSeriesMarkers(candleSeries, markers)
       │
       ▼
  Chart shows: ▲ entry · ▼ exit · ● pattern · --- SL/target lines
```

---

## Services & Ports

| Service | Port | Tech |
|---|---|---|
| trading-system backend | 8000 | FastAPI |
| trading-system frontend | 5173 | Vite + React |
| backtest-engine backend | 8085 | FastAPI |
| backtest-engine frontend | 8086 | Vite + React |

No merging of services. backtest-engine is a sidecar.

backtest-engine CORS must allow `http://localhost:5173` (trading-system frontend) so `BacktestOverlay.tsx` can call `/runs/{id}/markers/{symbol}` directly from the browser.

---

## SL / Target Rules

Configurable per run. Not baked into strategy code.

```python
class SLTargetConfig(BaseModel):
    sl_type:      Literal["fixed_pct", "atr_multiple", "trailing_pct", "trailing_atr"]
    sl_value:     float          # % or ATR multiplier
    target_type:  Literal["fixed_pct", "rr_ratio", "atr_multiple"]
    target_value: float          # %, R multiple, or ATR multiplier
```

Applied via a wrapper injected around the generated Strategy class in `LocalEngine`.
The wrapper intercepts `next()` and manages SL/target checks independently of strategy logic.

`SLTargetConfig` serialized and stored in `Run.params_json` alongside other run parameters. Rehydrated on result load so markers endpoint can compute SL/target prices from trades.

---

## Data Layer

`backtest-engine/backend/data/local_ohlcv.py` (already updated):
- Primary: QuestDB `postgresql://admin:quest@localhost:8812/qdb`
- Fallback: `trading-system/rawdata/` CSV files
- Output: backtesting.py-compatible DataFrame (tz-naive DatetimeIndex, OHLCV columns)
- Symbol map: `NSE:RELIANCE` → `RELIANCE`, `NSE:NIFTY` → `NSE_NIFTY_50`

---

## New Components

### backtest-engine additions

#### `backend/strategy/dsl_bridge.py`
Converts ConditionNode JSON (trading-system scanner DSL) into a `backtesting.py` Strategy class.

```python
def condition_node_to_strategy(
    node: dict,           # ConditionNode serialized as dict
    sl_target: SLTargetConfig,
) -> type:               # returns Strategy subclass
    """
    Walks ConditionNode tree, generates pandas_ta indicator calls,
    evaluates condition on each bar in Strategy.next().
    Uses same 14-indicator registry logic as trading-system evaluator.
    Raises ValueError for unsupported node types.
    """
```

Supported node types in v1: `indicator`, `crossover`, `candlestick`, `volume`, `trend`.
`chart_pattern` deferred to v2 (needs look-back window incompatible with bar-by-bar).

#### `backend/data/pattern_detector.py`
Detects named patterns on the entry bar and surrounding context. Called by `LocalEngine` at each entry signal.

```python
def detect_entry_annotations(
    df: pd.DataFrame,   # full OHLCV up to entry bar
    entry_idx: int,
    indicators: dict,   # pre-computed for efficiency
) -> list[str]:
    """
    Returns list of pattern names present at entry.
    Patterns: gravestone_doji, hammer, bullish_engulfing,
              vwap_cross_above, volume_spike_2x, pivot_high_break,
              pivot_low_support
    """
```

#### `TradeRecord` extension
Add `annotations: list[str] = []` field to `backend/execution/base.py`.

#### `GET /runs/{id}/markers/{symbol}` endpoint
Returns markers in lightweight-charts format:

```json
{
  "markers": [
    {
      "time": 1706745600,
      "position": "belowBar",
      "color": "#26a69a",
      "shape": "arrowUp",
      "text": "Entry ₹2481 · RSI<30+EMA×"
    },
    {
      "time": 1706832000,
      "position": "aboveBar",
      "color": "#ef5350",
      "shape": "arrowDown",
      "text": "SL ₹2432 (-2.0%)"
    },
    {
      "time": 1706745600,
      "position": "belowBar",
      "color": "#f59e0b",
      "shape": "circle",
      "text": "gravestone_doji · volume_spike_2x"
    }
  ],
  "price_lines": [
    { "trade_idx": 0, "sl_price": 2432.0, "target_price": 2629.0 }
  ]
}
```

---

### trading-system additions

#### New candlestick patterns — `backend/technical/patterns/candlestick.py`

`gravestone_doji(df)` — long upper wick, near-zero body, near-zero lower wick. Confidence proportional to upper wick / range ratio.

#### New pivot detectors — `backend/technical/patterns/levels.py`

```python
def pivot_highs(df: pd.DataFrame, left: int = 5, right: int = 5) -> list[int]:
    """Bar indices where high[i] > max(high[i-left:i]) and high[i] > max(high[i+1:i+right+1])"""

def pivot_lows(df: pd.DataFrame, left: int = 5, right: int = 5) -> list[int]:
    """Bar indices where low[i] < min(low[i-left:i]) and low[i] < min(low[i+1:i+right+1])"""
```

#### `frontend/src/components/Chart/BacktestOverlay.tsx`

```typescript
interface BacktestOverlayProps {
  runId: string
  symbol: string
  series: ISeriesApi<'Candlestick'>   // ref from CandlestickChart
  chart: IChartApi
}
```

- Fetches `GET http://localhost:8085/runs/{runId}/markers/{symbol}`
- Calls `createSeriesMarkers(series, markers)` from `lightweight-charts`
- Adds dashed horizontal `PriceLine` objects per trade for SL + target
- Cleans up on unmount or runId change

#### `frontend/src/pages/Chart.tsx` — LIVE / BACKTEST mode toggle

Add to chart header:
```
[ LIVE ] [ BACKTEST ]
```

BACKTEST mode renders:
- Config bar below header: run selector (dropdown of recent runs from backtest-engine) + direct link to backtest-engine UI
- `BacktestOverlay` component mounted with selected `runId`

The chart itself (`CandlestickChart`) is unchanged. Overlay is additive.

---

## New Patterns Detail

### gravestone_doji
```
Conditions:
  body = |close - open| / (high - low)  < 0.1
  upper_wick = high - max(open, close)
  lower_wick = min(open, close) - low
  upper_wick / (high - low) > 0.6
  lower_wick / (high - low) < 0.1
Confidence: upper_wick / (high - low)   [0.6 → 1.0]
Direction: bearish
```

### pivot_high / pivot_low
Standard zigzag definition with configurable `left` and `right` lookback (default 5 bars each side). Used in:
- `pattern_detector.py` — "entry near pivot_high" annotation
- `levels.py` — exposed via `find_support_resistance` (extends existing)

---

## Build Sequence

| Step | Files | Where |
|---|---|---|
| 1 | `candlestick.py` + `levels.py` (gravestone_doji, pivot_high/low) | trading-system backend |
| 2 | `dsl_bridge.py` (ConditionNode → backtesting.py strategy) | backtest-engine |
| 3 | `pattern_detector.py` + `TradeRecord.annotations` + `/markers` API | backtest-engine |
| 4 | `BacktestOverlay.tsx` + mode toggle in `Chart.tsx` | trading-system frontend |
| 5 | Wire + end-to-end test: RELIANCE 1d, RSI<30+EMA cross DSL, 2020–2024 | both |

---

## Tests

- `tests/unit/test_candlestick.py` — add gravestone_doji cases (3 bullish, 3 false positives)
- `tests/unit/test_levels.py` — pivot_high/pivot_low on synthetic series
- `backtest-engine/tests/test_dsl_bridge.py` — 3 ConditionNode trees → verify signal fires on known bars
- `backtest-engine/tests/test_pattern_detector.py` — annotations on synthetic entry bar

---

## Constraints

- Direction: long-only in v1.
- `chart_pattern` ConditionNode type not supported in DSL bridge v1 (look-back incompatibility with backtesting.py's bar-by-bar model).
- backtest-engine frontend URL hardcoded as `http://localhost:8085` in BacktestOverlay — configurable via env var `VITE_BACKTEST_ENGINE_URL`.
- QuestDB timestamps are UTC; `local_ohlcv.py` strips timezone for backtesting.py compatibility.

---

## Out of Scope (v1)

- Walk-forward validation UI (engine exists, no UI trigger yet)
- Multi-symbol batch backtest from trading-system
- Short selling
- Portfolio-level P&L (per-symbol runs only)
- Live signal → auto-backtest trigger
