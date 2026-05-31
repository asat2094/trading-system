# Session Handoff — 2026-05-31

## Project
`/Users/ankitatiwari/Desktop/claude-playground/trading-system`
Full-stack Indian equity + crypto trading system. FastAPI + React 19 + QuestDB + PostgreSQL + Redis + Temporal.

Companion repo: `/Users/ankitatiwari/Desktop/claude-playground/backtest-engine` (`:8085`)

---

## What Was Completed This Session

### Sub-project 5: Multi-Chart Live Dashboard — 100% COMPLETE ✅

All 12 tasks done. Charts render live data from Hyperliquid with real-time candle updates.

---

## BUGS FIXED THIS SESSION

### 1. Chart NaN Timestamp Bug ✅
**File:** `frontend/src/components/Chart/CandlestickChart.tsx:62-71`
**Root cause:** `tsToUnix()` appended `+05:30` to crypto timestamps that already had timezone info → `NaN`.
**Fix:** Detect existing timezone (`/[+-]\d{2}:\d{2}$/` or `Z`) and parse directly; QuestDB timestamps get `Z` appended.

### 2. Upstox Connection Status Not Updating ✅
**File:** `backend/brokers/upstox.py`
**Root cause:** `UpstoxAdapter` never set `_running` flag. `market_ws.py` checks `getattr(adapter, "_running", False)`.
**Fix:** Added `self._running` tracking in `__init__`, `connect()`, `disconnect()`, and `_recv_loop()` finally block.

### 3. Hyperliquid `data.mids` Nested Under Wrong Key ✅
**File:** `backend/brokers/hyperliquid.py:87`
**Root cause:** Hyperliquid sends `{"channel":"allMids","data":{"mids":{...}}}` but adapter read `data.get("mids")` at top level → 0 coins.
**Fix:** Changed to `data.get("data", {}).get("mids", {})`.

### 4. Live Quotes Not Reaching Frontend ✅
**Root cause:** `_fan_out` only forwarded quotes to already-subscribed clients. Quotes arriving before any client subscribed were silently dropped.
**Fix:** `MarketFeedManager` now caches `_last_quote[symbol]` and sends it immediately on `add_client`.

### 5. Chart Auto-Adjusting on Every Tick ✅
**File:** `frontend/src/components/Chart/CandlestickChart.tsx`
**Root cause:** `chart.timeScale().fitContent()` called on every `bars` change (including live ticks).
**Fix:** Added `didFitContent` ref — `fitContent()` only runs on initial data load.

### 6. Volume in Separate Pane ✅
**File:** `frontend/src/components/Chart/CandlestickChart.tsx:141-148`
**Fix:** Moved volume `HistogramSeries` from pane 1 to pane 0 with `priceScaleId: "vol"` and `scaleMargins: { top: 0.8, bottom: 0 }`.

### 7. Live Candle Updates Not Working ✅
**File:** `frontend/src/components/Dashboard/ChartPane.tsx:149-215`
**Root cause:** Timestamp mismatch between `candleFloor(tickMs)/1000` and `tsToUnix(lastBar.ts)` — floating-point precision and timezone handling differences.
**Fix:** Use `tsToUnix(last.ts)` for same-candle updates (guaranteed to match chart's internal time). Also update both candlestick and volume series via `series.update()` (TradingView pattern: same time = update in place, newer time = append).

### 8. Upstox 500 Error When Redis Down ✅
**File:** `backend/api/routers/market.py:86-123`
**Root cause:** `upstox_callback` and `upstox_status` crashed on `redis.ConnectionError`.
**Fix:** Wrapped Redis operations in try/except — returns graceful fallback when Redis is unavailable.

### 9. JWT Token Expiry ✅
**Root cause:** JWT expired after 24h, on refresh backend rejected WS connection → no live data.
**Fix:**
- `JWT_EXPIRY_HOURS` increased to 168 (7 days) in `.env` and `config.py`
- Client-side expiry check in `Dashboard.tsx` — redirects to `/login` if JWT expired
- **Redis-backed token tracking:** `LocalJWTProvider` now stores tokens in Redis (`auth:session:{token}`) with TTL. `verify_token` checks Redis existence in addition to JWT decode. `revoke_token` deletes from Redis.
- New `POST /auth/logout` endpoint revokes token from Redis.

### 10. TickerBar OHLCV for All Symbols ✅
**File:** `frontend/src/components/Dashboard/TickerBar.tsx`
**Root cause:** TickerBar only read from `useLiveQuotesStore` — showed nothing for NSE symbols without live feed.
**Fix:** Added `lastBar` prop fallback. TickerBar now shows OHLCV from last chart bar when no live quote available.

### 11. Upstox Button Shows "Reconnect" When Token Exists ✅
**File:** `frontend/src/pages/Dashboard.tsx`
**Fix:** TopBar checks `/auth/upstox/status` on mount. Shows "Reconnect Upstox" when token exists but not connected, "Connect Upstox" when no token, green dot when connected.

### 12. MarketStatusBar Auto-Subscribes to BTC ✅
**File:** `frontend/src/components/Dashboard/MarketStatusBar.tsx`
**Root cause:** MarketStatusBar read BTC price from store but never subscribed — relied on ChartPane being open.
**Fix:** Added `marketWs.subscribe(["CRYPTO:BTC"])` in useEffect on mount.

---

## Architecture

### Multi-Chart Data Flow
```
Browser ← marketWs.ts → ws://localhost:8000/ws/market
                              ↓
                    MarketFeedManager (singleton)
                    ├── NSE:*   → UpstoxAdapter (WS v3 protobuf)
                    └── CRYPTO:* → HyperliquidAdapter (allMids JSON)
                                      ↑
                          Hyperliquid sends: {"channel":"allMids","data":{"mids":{...}}}

Live tick flow:
  Hyperliquid WS → _recv_loop → _queue → _fan_out → WebSocket → marketWs.ts → liveQuotes store
                                                                         ↓
                                                              ChartPane.applyLiveTick()
                                                              → candleSeries.update()
                                                              → volumeSeries.update()

Historical bars:
  NSE:*    → GET /technical/ohlcv/{symbol} (QuestDB)
  CRYPTO:* → GET /market/ohlcv?symbol=CRYPTO:BTC (yfinance)
```

### Auth Flow (Redis-backed)
```
POST /auth/login → LocalJWTProvider.create_token() → JWT
                 → _store_token() → Redis SET auth:session:{token} TTL=168h
                 → return {access_token}

GET /any endpoint → verify_token() → jwt.decode() (check exp)
                                → Redis EXISTS auth:session:{token}
                                → both must pass

POST /auth/logout → revoke_token() → Redis DELETE auth:session:{token}
```

### BrokerAdapter Protocol
```python
class BrokerAdapter(Protocol):
    name: str
    prefixes: list[str]
    async def connect(self) -> None: ...
    async def subscribe(self, symbols: list[str]) -> None: ...
    async def unsubscribe(self, symbols: list[str]) -> None: ...
    async def quotes(self) -> AsyncIterator[Quote]: ...
    async def disconnect(self) -> None: ...
```

### Upstox OAuth Flow
1. User clicks "Reconnect/Connect Upstox" → popup opens `/auth/upstox/login`
2. Redirects to Upstox OAuth → callback to `/auth/upstox/callback?code=...`
3. Backend exchanges code → stores in Redis `upstox:token` (TTL 24h)
4. Triggers `reconnect_adapter("upstox")` to start WS feed

---

## Running Services

```bash
# Backend (port 8000)
cd trading-system/backend && PYTHONPATH=. .venv/bin/uvicorn api.main:app --port 8000 --reload

# Frontend (port 5173)
cd trading-system/frontend && npm run dev

# Redis (Docker)
docker start infra-redis-1

# Backtest engine (port 8085)
cd backtest-engine && venv/bin/uvicorn backend.main:app --port 8085
```

## Tests

```bash
# Backend unit tests (102 passing)
backend/.venv/bin/python -m pytest backend/tests/unit/ -q

# Frontend E2E (17 passing)
cd frontend && node_modules/.bin/playwright test --reporter=list

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

1. **E2E test stability** — some tests use `waitForTimeout` patterns that can be flaky
2. **Volume Profile rendering** — `calcVolumeProfile()` implemented in `indicators.ts`, not wired into chart (needs custom series)
3. **FVG rendering** — `calcFVG()` implemented, not wired into chart (needs rectangle overlay)
4. **Fundamental Analysis** — Sub-project 6 not started
5. **Quant Models** — Sub-project 7 not started

---

## Overall Project Roadmap

| Sub-project | Status |
|---|---|
| 1. Technical Analysis Engine (24 tasks) | ✅ COMPLETE |
| 2. Condition Evaluation Engine (9 tasks) | ✅ COMPLETE |
| 3. Backtest Integration (12 tasks) | ✅ COMPLETE |
| 4. FnO Live Analysis (7 tasks) | ✅ COMPLETE |
| 5. Multi-Chart Live Dashboard (12 tasks) | ✅ COMPLETE |
| 6. Fundamental Analysis | 🔲 Not started |
| 7. Quant Models | 🔲 Not started |

---

## Known Gotchas

| Issue | Fix |
|---|---|
| `npx playwright test` version conflict | Use `node_modules/.bin/playwright test` directly |
| Docker must be running for Redis | `open -a Docker` then `docker start infra-redis-1` |
| Hyperliquid allMids has no OHLCV | Historical bars from yfinance; live ticks build candles in ChartPane |
| `data.rows` not `data.bars` | All OHLCV endpoints return `{rows: [...]}` |
| Hyperliquid mids nested under `data.mids` | Not top-level `mids` — use `data.get("data",{}).get("mids",{})` |
| JWT expiry defaults to 24h | Set `JWT_EXPIRY_HOURS=168` in `.env` (7 days) |
| Upstox token expires daily | User re-auths each morning via OAuth popup |
