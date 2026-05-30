# Session Handoff — 2026-05-31

## Project
`/Users/ankitatiwari/Desktop/claude-playground/trading-system`
Full-stack Indian equity + crypto trading system. FastAPI + React 19 + QuestDB + PostgreSQL + Redis + Temporal.

Companion repo: `/Users/ankitatiwari/Desktop/claude-playground/backtest-engine` (`:8085`)

---

## What Was Completed This Session

### Sub-project 4: FnO Live Analysis ✅ (7 tasks)

Full NIFTY option chain page with PCR/PCDR/PCD metrics + Open-High analysis.

**Files created:**
- `backend/workers/activities/fetch_fno_snapshot.py` — KiteMCP client + PCR/PCDR/PCD/OH compute + Temporal activity
- `backend/workers/workflows/fno_snapshot.py` — on-demand Temporal workflow
- `backend/api/routers/fno.py` — `GET /fno/snapshot` (auth-guarded)
- `frontend/src/components/Fno/types.ts` — OptionSide, StrikeRow, FnoSnapshot interfaces
- `frontend/src/components/Fno/PcrCards.tsx` — 4 summary cards
- `frontend/src/components/Fno/OptionsChainTable.tsx` — CE|Strike|PE grid with OH badges
- `frontend/src/pages/FnoLive.tsx` — layout page
- `backend/tests/unit/test_fno_snapshot.py` — 12 tests

### Sub-project 5: Multi-Chart Live Dashboard (12 tasks, ~90% complete)

Replaced `/chart/:symbol` with configurable multi-pane dashboard.

**Spec:** `docs/superpowers/specs/2026-05-30-multi-chart-dashboard-design.md`
**Plan:** `docs/superpowers/plans/2026-05-30-multi-chart-dashboard.md`

#### Backend — COMPLETE ✅
- `backend/brokers/base.py` — `BrokerAdapter` Protocol + `Quote` dataclass + `broker_prefix()`
- `backend/brokers/upstox.py` — UpstoxAdapter: OAuth + WS v3 + protobuf decode
- `backend/brokers/upstox_proto/` — compiled MarketDataFeed.proto
- `backend/brokers/hyperliquid.py` — HyperliquidAdapter: allMids WS JSON
- `backend/api/market_ws.py` — `MarketFeedManager` singleton + `/ws/market` handler (with retry+reconnect)
- `backend/api/routers/market.py` — `GET /market/ohlcv` (yfinance crypto), Upstox OAuth endpoints
- `backend/tests/unit/test_broker_base.py` — 4 tests
- `backend/tests/unit/test_hyperliquid_adapter.py` — 4 tests

#### Frontend — COMPLETE ✅ (but chart rendering has a bug)
- `frontend/src/store/dashboard.ts` — Zustand persist: paneCount + PaneConfig[] + IndicatorConfig[]
- `frontend/src/store/liveQuotes.ts` — in-memory live quotes store
- `frontend/src/lib/marketWs.ts` — singleton WS client with ref-counted subscriptions
- `frontend/src/components/Chart/types.ts` — EXTENDED with VolumeProfile + FVG StudyConfig variants
- `frontend/src/components/Chart/indicators.ts` — EXTENDED with calcVolumeProfile + calcFVG
- `frontend/src/components/Dashboard/MarketStatusBar.tsx` — India/US/Crypto open-closed strip
- `frontend/src/components/Dashboard/TickerBar.tsx` — LTP flash green/red
- `frontend/src/components/Dashboard/PaneControls.tsx` — symbol search (position:fixed dropdown) + TF
- `frontend/src/components/Dashboard/IndicatorPanel.tsx` — two-layer: list ↔ settings (Inputs/Style/Visibility)
- `frontend/src/components/Dashboard/ChartPane.tsx` — composed pane
- `frontend/src/components/Dashboard/PaneGrid.tsx` — CSS grid 1/2/4/6/8
- `frontend/src/pages/Dashboard.tsx` — top bar + pane count + Connect Upstox
- `frontend/src/App.tsx` — `/chart` → Dashboard, `/chart/:symbol` → redirect
- `frontend/src/components/Layout/Sidebar.tsx` — "Dashboard" nav item
- `frontend/e2e/dashboard.spec.ts` — 17 Playwright E2E tests (all passing with `node_modules/.bin/playwright test`)

---

## KNOWN BUG — Charts Not Rendering

**Error:** `Assertion failed: data must be asc ordered by time, index=1, time=NaN, prev time=NaN`

**Root cause:** `CandlestickChart.tsx:169` calls `tsToUnix(b.ts)` which does:
```typescript
function tsToUnix(ts: string): UTCTimestamp {
  return (new Date(ts.includes("T") ? ts + "+05:30" : ts).getTime() / 1000) as UTCTimestamp;
}
```

For crypto data from yfinance, the `ts` field has timezone info (e.g. `2026-05-30T20:00:00+00:00`). Appending `+05:30` to a string that already has `+00:00` produces `2026-05-30T20:00:00+00:00+05:30` → `NaN`.

**Fix needed in `CandlestickChart.tsx`:** Make `tsToUnix` handle both formats:
```typescript
function tsToUnix(ts: string): UTCTimestamp {
  // If ts already has timezone info, parse directly
  if (ts.includes("+") && ts.indexOf("+") > 10) {
    return (new Date(ts).getTime() / 1000) as UTCTimestamp;
  }
  // QuestDB UTC timestamps — add IST offset for NSE display
  return (new Date(ts.includes("T") ? ts + "+05:30" : ts).getTime() / 1000) as UTCTimestamp;
}
```

Or: normalize timestamps in `ChartPane.tsx` before passing to `CandlestickChart`.

**Status:** Fix not yet applied. This is the next task.

---

## Architecture

### Multi-Chart Data Flow
```
Browser ← marketWs.ts → ws://localhost:8000/ws/market
                              ↓
                    MarketFeedManager (singleton)
                    ├── NSE:*   → UpstoxAdapter (WS v3 protobuf)
                    └── CRYPTO:* → HyperliquidAdapter (allMids JSON)

Historical bars:
  NSE:*    → GET /technical/ohlcv/{symbol} (QuestDB)
  CRYPTO:* → GET /market/ohlcv?symbol=CRYPTO:BTC (yfinance)
```

### BrokerAdapter Protocol
```python
class BrokerAdapter(Protocol):
    name: str
    prefixes: list[str]  # e.g. ["NSE", "BSE"] or ["CRYPTO"]
    async def connect(self) -> None: ...
    async def subscribe(self, symbols: list[str]) -> None: ...
    async def unsubscribe(self, symbols: list[str]) -> None: ...
    async def quotes(self) -> AsyncIterator[Quote]: ...
    async def disconnect(self) -> None: ...
```

Adding new broker = one file implementing this protocol + register in `api/main.py` lifespan.

### Upstox OAuth Flow
1. User clicks "Connect Upstox" → popup opens `http://localhost:8000/auth/upstox/login`
2. Redirects to Upstox OAuth dialog → user logs in → callback to `/auth/upstox/callback?code=...`
3. Backend exchanges code for `access_token` → stores in Redis `upstox:token` (TTL 24h)
4. Backend auto-triggers `reconnect_adapter("upstox")` to start WS feed
5. Token expires daily — user re-auths each morning

### Upstox Credentials
```
# In .env (already set):
UPSTOX_API_KEY=682c3fc4-f9a7-4ce5-809a-8be7b3a042a2
UPSTOX_API_SECRET=8y9hl83m9y
```
⚠️ These were shared in chat. Should be regenerated at https://api.upstox.com/developer/apps

---

## Running Services

```bash
# Backend
cd trading-system/backend && PYTHONPATH=. .venv/bin/uvicorn api.main:app --port 8000

# Frontend
cd trading-system/frontend && npm run dev   # port 5173

# Backtest engine
cd backtest-engine && venv/bin/uvicorn backend.main:app --port 8085
```

## Tests

```bash
# Backend unit tests (102 passing)
backend/.venv/bin/python -m pytest backend/tests/unit/ -q

# Frontend E2E (17 passing)
cd frontend && node_modules/.bin/playwright test --reporter=list
# Note: use node_modules/.bin/playwright, NOT npx (version conflict with bare playwright pkg)

# TypeScript
cd frontend && npx tsc --noEmit
```

---

## Zustand Store Shape (localStorage key: "trading-dashboard")

```typescript
{
  paneCount: 1 | 2 | 4 | 6 | 8,
  panes: [
    {
      id: string,
      symbol: "NSE:RELIANCE" | "CRYPTO:BTC" | ...,
      timeframe: "1min" | "15min" | "1h" | "1d" | ...,
      dataSource: "auto",
      indicators: [
        { id, type: "EMA", inputs: { period: 20 }, style: { color: "#f7c948" }, visible: true },
        ...
      ]
    },
    ...
  ]
}
```

---

## Next Steps

1. **FIX: Chart NaN timestamp bug** — `CandlestickChart.tsx` `tsToUnix()` breaks on crypto timestamps with timezone offsets
2. **E2E test stability** — some tests use `waitForTimeout` patterns that can be flaky; consider using `waitForSelector` + test-ids throughout
3. **Volume Profile rendering** — `calcVolumeProfile()` is implemented in `indicators.ts` but not wired into `CandlestickChart.tsx` render logic (needs custom series)
4. **FVG rendering** — `calcFVG()` is implemented but not wired into chart rendering (needs rectangle overlay series)
5. **Live price flash on charts** — `liveQuotes` store updates but chart doesn't append live candle ticks yet
6. **Persist Upstox connection status** — currently shows "disconnected" after page reload until WS reconnects; could read `/auth/upstox/status` on load

---

## Overall Project Roadmap

| Sub-project | Status |
|---|---|
| 1. Technical Analysis Engine (24 tasks) | ✅ COMPLETE |
| 2. Condition Evaluation Engine (9 tasks) | ✅ COMPLETE |
| 3. Backtest Integration (12 tasks) | ✅ COMPLETE |
| 4. FnO Live Analysis (7 tasks) | ✅ COMPLETE |
| 5. Multi-Chart Dashboard (12 tasks) | 🟡 90% — chart NaN bug remaining |
| 6. Fundamental Analysis | 🔲 Not started |
| 7. Quant Models | 🔲 Not started |

---

## Known Gotchas

| Issue | Fix |
|---|---|
| `tsToUnix` NaN for crypto timestamps | Don't append `+05:30` if ts already has timezone info |
| `npx playwright test` version conflict | Use `node_modules/.bin/playwright test` directly |
| Upstox WS needs OAuth token first | Auto-reconnects after OAuth callback — token in Redis |
| Hyperliquid allMids has no OHLCV | Historical bars come from yfinance `/market/ohlcv` endpoint |
| `data.rows` not `data.bars` | All OHLCV endpoints return `{rows: [...]}` |
| gemma4 conductor writes to stdout not files | Use Write tool directly for files; conductor only reliable for single-file edits |
