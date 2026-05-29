# Session Handoff — 2026-05-29

## Project
`/Users/ankitatiwari/Desktop/claude-playground/trading-system`
Full-stack Indian equity trading system. FastAPI + React + QuestDB + PostgreSQL + Redis + Temporal.

Companion repo: `/Users/ankitatiwari/Desktop/claude-playground/backtest-engine`
Python backtesting sidecar (FastAPI + SQLite + backtesting.py + Temporal). Runs on `:8085`.

---

## Stack

| Layer | Tech |
|-------|------|
| Frontend | React 18, TypeScript, Vite, lightweight-charts v5, Zustand |
| Backend API | FastAPI (Python 3.12) |
| Time-series DB | QuestDB (OHLCV 1-min, WAL + dedup on `(ts, symbol)`) |
| Metadata DB | PostgreSQL |
| Cache / pub-sub | Redis |
| Workflow engine | Temporal (`trading-main` task queue, `trading` namespace) |
| Data source | Kite MCP (`https://mcp.kite.trade/mcp`, 180 RPM budget) |

---

## Directory Layout

```
trading-system/
├── frontend/src/
│   ├── pages/
│   │   ├── Chart.tsx               # chart page + LIVE/BACKTEST mode toggle
│   │   └── Screener.tsx
│   ├── components/
│   │   ├── Chart/
│   │   │   ├── CandlestickChart.tsx     # forwardRef → ChartHandle (candleSeries + chart)
│   │   │   ├── BacktestPanel.tsx        # condition builder + SL/target config + run + poll
│   │   │   ├── BacktestOverlay.tsx      # fetches markers, calls createSeriesMarkers()
│   │   │   ├── StudyPanel.tsx
│   │   │   ├── indicators.ts
│   │   │   └── types.ts
│   │   └── Screener/
│   │       ├── ConditionBuilder.tsx     # reused in BacktestPanel
│   │       └── ResultsTable.tsx
│   └── store/filters.ts                # Zustand: ConditionGroup / customConditions
├── backend/
│   ├── technical/
│   │   ├── patterns/
│   │   │   ├── candlestick.py           # 8 patterns incl. gravestone_doji (NEW)
│   │   │   └── levels.py                # pivot_highs(), pivot_lows() (NEW)
│   ├── api/routers/technical.py
│   └── tests/unit/                      # 82 tests — all passing
│       ├── test_candlestick.py           # 21 tests (gravestone_doji added)
│       └── test_levels.py               # 6 pivot tests (NEW)
└── docs/
    └── superpowers/plans/
        ├── 2026-05-28-backtest-integration.md    # COMPLETED (12 tasks)
        └── 2026-05-29-fno-live-analysis.md       # READY TO EXECUTE (7 tasks)

backtest-engine/                                   # branch: develop
├── backend/
│   ├── execution/
│   │   ├── sl_target.py                 # SLTargetConfig + wrap_with_sl_target() (NEW)
│   │   ├── base.py                      # TradeRecord.annotations: list[str] (NEW field)
│   │   └── local/engine.py              # sl_target param wired in (MODIFIED)
│   ├── strategy/
│   │   └── dsl_bridge.py               # ConditionNode JSON → GeneratedStrategy class (NEW)
│   ├── data/
│   │   └── pattern_detector.py          # detect_entry_annotations() (NEW)
│   ├── api/
│   │   ├── runs.py                      # RunRequest + condition_node + /markers endpoint (MODIFIED)
│   │   └── main.py                      # CORS: added localhost:5173 + 8086 (MODIFIED)
│   └── tests/                           # 13 core tests passing
│       ├── test_dsl_bridge.py           # 5 tests
│       ├── test_sl_target.py            # 3 tests
│       └── test_pattern_detector.py     # 5 tests
└── venv/                                # python3.12 venv
```

---

## What Was Completed This Session

### 1. Backtest Integration (trading-system × backtest-engine)

Full end-to-end backtest workflow in chart page. All 12 tasks complete.

**trading-system commits (on `main`):**
```
8bfd223  fix: read data.notes for failed run error (poll)
6c48c51  feat: LIVE/BACKTEST toggle, wire BacktestPanel + BacktestOverlay
b6e3651  feat: BacktestOverlay + BacktestPanel components
f6cc45b  feat: CandlestickChart forwardRef → ChartHandle
4313acb  fix: docstring wording in pivot_highs
c334623  feat: pivot_highs + pivot_lows detectors
f4af8e3  fix: comment arithmetic in test_gravestone_doji_detected
de94f67  feat: gravestone_doji candlestick pattern
```

**backtest-engine commits (on `develop`, merged from `feat/llm-providers-gemini-nvidia-openrouter`):**
```
0edb1a4  merge: resolve runs.py conflict (module fetch_ohlcv + multi-symbol sl_target)
5abb8db  fix: filter markers by symbol in get_markers endpoint
929d887  feat: RunRequest + condition_node + /markers endpoint + CORS
66b343c  feat: sl_target + annotations wired into LocalEngine
c282694  feat: TradeRecord.annotations + pattern_detector
76fa84e  fix: return False for unknown indicators (DSL bridge)
7052b2b  feat: DSL bridge — ConditionNode → backtesting.py strategy
61cca91  fix: ATR NaN check (pd.isna not val == val)
a5123a8  feat: SLTargetConfig + wrap_with_sl_target
```

**Flow:**
```
Chart (BACKTEST mode)
  └── BacktestPanel
        ├── tab: Conditions → ConditionBuilder (shared with Screener, reads useFiltersStore)
        └── tab: Config → dateFrom/dateTo, slType/slValue, tgtType/tgtValue, broker
  └── POST /runs → backtest-engine
        ├── condition_node: customConditions (ConditionGroup from filters store)
        ├── sl_target: {sl_type, sl_value, target_type, target_value}
        └── params: {symbols, timeframe, date_from, date_to, engine, broker}
  └── poll GET /runs/{runId} every 1500ms
  └── onRunComplete(runId) → BacktestOverlay
        ├── GET /runs/{runId}/markers/{symbol}
        ├── createSeriesMarkers(series, lwMarkers)    # lightweight-charts v5
        └── PriceLine per trade (dashed green TP, dashed red SL)
```

### 2. Key Design Decisions

**ConditionNode wire format compatibility:**
`ConditionGroup` from `filters.ts` has `{ id, logic, children }`. The `logic` key matches DSL bridge composite node detection → directly compatible as `condition_node` in `RunRequest`.

**Annotations storage (avoids migration):**
`cost_breakdown_json = json.dumps({**t.cost.model_dump(), "annotations": t.annotations})`
No new DB column needed.

**Delta OI for FnO (upcoming):**
Track OI baseline in Redis at first daily fetch. Delta = current_OI - baseline_OI (expiry TTL at IST midnight).

### 3. Backtest-Engine Merge Resolution

Merged `feat/llm-providers-gemini-nvidia-openrouter` → `develop`. 3 conflict resolutions in `runs.py`:
1. **Conflict 1** — dropped inline yfinance helpers (develop uses `backend.execution.local.data.fetch_ohlcv` module)
2. **Conflict 2** — merged multi-symbol loop + sl_target (feature) with `FetchResult` pattern (develop)
3. **Conflict 3** — kept `delete_run` + `rerun_run` (develop) AND `local-symbols` endpoint (feature)

### 4. FnO Live Analysis Plan Written

Plan: `docs/superpowers/plans/2026-05-29-fno-live-analysis.md`

7 tasks, ready to execute:
- **Task 1**: `backend/workers/activities/fetch_fno_snapshot.py` — KiteMCP client + PCR/PCDR/PCD/OH compute
- **Task 2**: `backend/workers/workflows/fno_snapshot.py` — on-demand Temporal workflow
- **Task 3**: `backend/api/routers/fno.py` — `GET /fno/snapshot?symbol=NIFTY&strikes=10`
- **Task 4**: `frontend/src/components/Fno/types.ts` + `PcrCards.tsx`
- **Task 5**: `frontend/src/components/Fno/OptionsChainTable.tsx`
- **Task 6**: `frontend/src/pages/FnoLive.tsx`
- **Task 7**: Wire routing + sidebar nav

---

## KiteMCP Integration (critical patterns)

### Session file
```
backend/scripts/.kitemcp_session   ← session ID populated by --auth flow
backend/scripts/.kitemcp_tokens.json
backend/scripts/.kitemcp_index_tokens.json
```

### `_FnoMCPClient` pattern (used in fetch_fno_snapshot.py)

```python
class _FnoMCPClient:
    _SESSION_FILE = Path(__file__).parent.parent.parent / "scripts" / ".kitemcp_session"

    def __init__(self) -> None:
        if not self._SESSION_FILE.exists():
            raise RuntimeError("No Kite MCP session. Run: python scripts/backfill_1min_kitemcp.py --auth")
        self.session_id = self._SESSION_FILE.read_text().strip()
        self._client    = httpx.Client(timeout=30)

    def call_tool(self, name: str, arguments: dict) -> Any:
        _kite_limiter.acquire()   # shared 180 RPM from fetch_kitemcp_1min
        resp = self._client.post(
            "https://mcp.kite.trade/mcp",
            json={"jsonrpc": "2.0", "method": "tools/call",
                  "params": {"name": name, "arguments": arguments}, "id": 1},
            headers={"Content-Type": "application/json",
                     "Accept": "application/json",
                     "mcp-session-id": self.session_id},
        )
        resp.raise_for_status()
        sid = resp.headers.get("mcp-session-id", "")
        if sid:
            self.session_id = sid   # server may refresh session
        text = resp.json().get("result", {}).get("content", [{}])[0].get("text", "{}")
        return json.loads(text)
```

### NIFTY options instrument format

```
NFO:NIFTY{YY}{MMM}{STRIKE}{CE/PE}
e.g.  NFO:NIFTY26JUN24700CE    ← monthly, strike 24700, call
      NFO:NIFTY26JUN24700PE    ← monthly, strike 24700, put
```

KiteMCP `search_instruments` returns `instrument_token`, `strike`, `expiry_date`, `expiry_type`, `lot_size`. `last_price=0` in search — use `get_quotes` for live data.

`get_quotes` returns: `last_price`, `oi`, `ohlc.{open,high,low,close}`, `volume` — all in one batch call (≤500 instruments).

### NIFTY FnO parameters
- Strike step: 50 pts
- Lot size: 65 (as of 2026)
- Monthly expiry: last Thursday of month
- `expiry_prefix` for symbol: `f"NIFTY{expiry.strftime('%y%b').upper()}"` → `"NIFTY26JUN"`
- ATM rounding: `round(spot / 50) * 50`

---

## backtest-engine API

Base URL: `http://localhost:8085` (env: `VITE_BACKTEST_ENGINE_URL`)

```
POST /runs
  body: {
    condition_node: ConditionGroup | null,   # DSL path
    strategy_id: str | null,                  # LLM path
    sl_target: {sl_type, sl_value, target_type, target_value},
    params: {symbols, timeframe, date_from, date_to, engine, broker}
  }
  response: {run_id, status}

GET  /runs/{run_id}            → {status, notes, ...}
GET  /runs/history             → [{run_id, run_name, status, symbols_json}]
GET  /runs/{run_id}/markers/{symbol}
  response: {
    markers: [{time, position, color, shape, text}],   # lightweight-charts v5 SeriesMarker
    price_lines: [{trade_idx, sl_price, target_price}]
  }
```

**SLTargetConfig types:**
```python
sl_type:      "fixed_pct" | "atr_multiple" | "trailing_pct" | "trailing_atr"
target_type:  "fixed_pct" | "rr_ratio" | "atr_multiple"
```

**DSL bridge supported node types:** indicator, crossover, composite (AND/OR), candlestick, volume, trend.
`chart_pattern` raises `ValueError` (not supported in v1).

---

## Backtest-Engine Tests

```bash
cd backtest-engine
venv/bin/python -m pytest tests/test_dsl_bridge.py tests/test_sl_target.py tests/test_pattern_detector.py -v
# 13 passed
# Ignore: test_tv_engine.py, test_harness.py, test_tv_client.py (pre-existing failures, TVMCPClient import)
```

---

## Trading-System Tests

```bash
cd trading-system
backend/.venv/bin/python -m pytest backend/tests/unit/ -v
# 82 passed (gravestone_doji + pivot tests added this session)
```

---

## core/config.py — Settings Reference

```python
class Settings(BaseSettings):
    POSTGRES_URL: str
    QUESTDB_URL: str
    REDIS_URL: str
    TEMPORAL_HOST: str
    TEMPORAL_NAMESPACE: str = "trading"
    AUTH_PROVIDER: str = "local"
    JWT_SECRET: str
    JWT_EXPIRY_HOURS: int = 24
    ANTHROPIC_API_KEY: SecretStr = SecretStr("")
    LLM_MODEL: str = "claude-sonnet-4-6"
    TIMEZONE: str = "Asia/Kolkata"
    MARKET_OPEN_IST: str = "09:15"
    MARKET_CLOSE_IST: str = "15:30"
    DAILY_REFRESH_CRON: str = "45 16 * * 1-5"
```

---

## Temporal Gotchas

| Issue | Fix |
|-------|-----|
| `ZoneInfo` in workflow → `_RestrictedProxy` TypeError | `timezone(timedelta(hours=5, minutes=30))` |
| `COUNT(DISTINCT symbol)` in QuestDB → "dangling literal" | `COUNT(*) FROM (SELECT symbol FROM ... LATEST ON ts PARTITION BY symbol)` |
| `ScheduleSpec(timezone=...)` kwarg error | Correct param: `time_zone_name` |
| numpy `bool_` leaks from ConditionEvaluator | Cast `passed = bool(...)` in all `_eval_*` methods |

---

## ConditionNode Wire Format (filters.ts → backtest-engine)

```typescript
// From Zustand store (store/filters.ts)
interface ConditionGroup {
  id: string;
  logic: "AND" | "OR";
  children: (ConditionLeaf | ConditionGroup)[];
}
// Sent directly as condition_node in POST /runs
// DSL bridge detects composite by presence of "logic" key → AND/OR
```

---

## Running Services

```bash
# trading-system backend
cd trading-system/backend && PYTHONPATH=. .venv/bin/python -m uvicorn api.main:app --reload --port 8000

# trading-system worker
cd trading-system/backend && PYTHONPATH=. .venv/bin/python -m workers.main

# trading-system frontend
cd trading-system/frontend && npm run dev     # port 5173

# backtest-engine
cd backtest-engine && venv/bin/uvicorn backend.main:app --reload --port 8085

# backtest-engine frontend (optional separate UI)
cd backtest-engine/frontend && npm run dev    # port 8086

# Kite MCP auth (if session expired)
cd trading-system/backend && PYTHONPATH=. python scripts/backfill_1min_kitemcp.py --auth
```

---

## Next: FnO Live Analysis

Plan ready at `docs/superpowers/plans/2026-05-29-fno-live-analysis.md`.

**Execute with subagent-driven development. 7 tasks:**

1. `fetch_fno_snapshot.py` — `_FnoMCPClient` + `run_fno_snapshot()` + Temporal activity
2. `fno_snapshot.py` workflow — on-demand, `start_to_close_timeout=60s`
3. `fno.py` router — `GET /fno/snapshot`, wires `asyncio.to_thread(run_fno_snapshot, ...)`
4. `Fno/types.ts` + `PcrCards.tsx` — TypeScript interfaces + 3 summary cards
5. `Fno/OptionsChainTable.tsx` — CE | Strike | PE per-row, OH badge, OH-hit flash
6. `FnoLive.tsx` page — layout, refresh button, auto-refresh every 5 min during market hours
7. Wire `/fno` route in `App.tsx` + nav item in `Sidebar.tsx`

**Key constraint:** ≤3 KiteMCP calls per refresh:
1. `get_ltp(["NSE:NIFTY 50"])` → spot
2. `get_quotes([~42 instruments])` → OI + OHLC + LTP for all strikes

Delta OI via Redis baselines (no extra API calls).

---

## CandlestickChart IST Display Pattern

```tsx
const IST_OFFSET_MS = 5.5 * 3600 * 1000;
function istDate(unixSeconds: number): Date {
  return new Date(unixSeconds * 1000 + IST_OFFSET_MS);
}
// Always use getUTC* on shifted date. Never getHours() (local TZ).
```

---

## Known Gotchas

| Issue | Fix |
|-------|-----|
| `ATR == 0` falsy check | Use `val is not None and not pd.isna(val) and val > 0` |
| `BacktestPanel` poll error field | API returns `notes` not `error` — use `data.notes \|\| data.error \|\| "Run failed"` |
| `get_markers` multi-symbol runs | Filter `Trade.ticker == symbol` in WHERE (already fixed) |
| lightweight-charts v5 SeriesMarker | Use `createSeriesMarkers(series, markers)` — not v4's `series.setMarkers()` |
| `chart_pattern` in DSL bridge | Raises `ValueError` — frontend should disable this option in BacktestPanel |
| Unknown indicator in DSL bridge | Returns `"False"` (safe fallback, no crash) |
| NIFTY expiry month prefix | `expiry.strftime('%y%b').upper()` → `"26JUN"` not `"2026JUN"` |
