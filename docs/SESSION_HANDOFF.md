# Session Handoff — 2026-06-02

## Project
`/Users/ankitatiwari/Desktop/claude-playground/trading-system`
Full-stack Indian equity + crypto trading system. FastAPI + React 19 + QuestDB + PostgreSQL + Redis + Temporal.

Companion repo: `/Users/ankitatiwari/Desktop/claude-playground/backtest-engine` (`:8085`)

---

## Current Branch
`develop` — all PRs merged.

### Merged this session
| PR | Branch | Summary |
|---|---|---|
| #1 | `feature/chart-panel-redesign` | Global indicator panel, ChartUnit, drawing tools, collapsible sidebar, Pivot/VWAP bands/EMA source, live Upstox quotes |
| #2 | `feature/kitemcp-broker` | KiteMCP Connect Kite button, session in Redis, `/auth/kite/init|status` |
| #3 | `feature/fno-chart-fix` | NFO instrument lookup, infinite render loop fix (`_EMPTY`), fitKey TF change, TF_DAYS 1d→90 |
| #4 | `feature/fno-option-chart-fix` | FnO expiry bug (today's expiry on expiry day), NFO→KiteMCP routing, auto-refresh OFF default, candles at open time |

---

## Architecture Overview

### Backend (`backend/`)
- `brokers/upstox.py` — Upstox WS v3 + REST; ISIN keys for EQ (`NSE_EQ|INE040A01034`), NFO prefixes added; auto-reconnect with 2→60s backoff
- `brokers/hyperliquid.py` — Hyperliquid WS adapter
- `brokers/base.py` — `Quote` dataclass, `BrokerAdapter` protocol
- `api/market_ws.py` — `MarketFeedManager`; fan_out + add_client at INFO log level
- `api/routers/market.py` — Upstox OAuth, KiteMCP auth (`/auth/kite/init|status`), Hyperliquid reconnect
- `api/routers/technical.py` — `/technical/symbols` (normalizes `NSE_NIFTY_50`→`NIFTY 50`), `/technical/candles`
- `api/routers/fno.py` — `/fno/snapshot`, `/fno/expiries` (KiteMCP, Redis cache)
- `core/sdk.py` — `MarketData`; NFO/BFO routes directly to KiteMCP (Upstox NFO file is 403); session from Redis first, file fallback
- `workers/activities/fetch_fno_snapshot.py` — 2 KiteMCP calls per snapshot; `_nearest_expiry` uses today when today IS expiry day

### Frontend (`frontend/src/`)
- `components/Chart/ChartUnit.tsx` — unified chart; `_EMPTY` stable ref for standalone mode; `tfOffsetSec=0` (open-time convention); `fitKey` resets fitContent on TF change
- `components/Chart/CandlestickChart.tsx` — `fitKey` prop resets `didFitContent`; `tfOffsetSec` param (now always 0)
- `components/Chart/indicators.ts` — EMA/SMA/BB/VWAP/RSI/MACD/Stoch/VolumeProfile/FVG/Pivot
- `components/Chart/types.ts` — `StudyConfig`, `OVERLAY_TYPES`, `OSCILLATOR_TYPES`
- `components/Dashboard/IndicatorPanel.tsx` — global (linkId) vs individual vs local mode
- `components/Dashboard/PaneControls.tsx` — symbol search; canonical symbols (with `:`) skip `NSE:` prefix
- `components/Dashboard/DrawingToolbar.tsx` — hline/trendline/fibonacci/long_position/short_position
- `components/Layout/Sidebar.tsx` — 44px↔220px collapsible nav, localStorage persist
- `components/Fno/FnoChartModal.tsx` — options chart modal; standalone ChartUnit (no paneId)
- `lib/marketWs.ts` — singleton WS to `/ws/market`; `ws=null` on close; onerror handler
- `store/dashboard.ts` — panes, linkId indicators, focusedPaneId persisted
- `store/liveQuotes.ts` — Zustand quotes; kiteConnected + kiteUser state
- `pages/FnoLive.tsx` — auto-refresh defaults OFF; index chart + options chain

---

## Critical Facts

### Upstox
- **EQ WS key**: `NSE_EQ|INE040A01034` (ISIN), NOT `NSE_EQ|HDFCBANK`
- **Index WS key**: `NSE_INDEX|Nifty 50` (mixed case) — hardcoded in `_INDEX_INSTRUMENT_KEYS`
- **NFO**: adapter prefixes include `NFO`/`BFO`; instruments file returns 403 → candle fallback to KiteMCP
- **WS frames**: MUST be binary (`.encode()`), NOT text
- **Token**: daily expiry; 403 on WS = expired → Redis key cleared

### KiteMCP
- Session stored as `kite:session_id` in Redis AND `.kitemcp_session` file
- `/auth/kite/init` → initializes MCP session, returns Zerodha login URL; user opens popup, polls `/auth/kite/status`
- Rate limit: 180 RPM shared bucket (`_kite_limiter`) across snapshot + candles + expiries
- **Infinite loop was hammering KiteMCP** (now fixed via `_EMPTY` ref in ChartUnit)

### FnO
- `_nearest_expiry`: `(target - weekday) % 7` — today IS allowed as expiry day (removed `or 7`)
- 2 KiteMCP calls per snapshot: `get_ltp` + `get_quotes`; cached 5min Redis
- Chart data for options: KiteMCP (Upstox NFO file 403)

### Chart Display
- `tfOffsetSec = 0` — candles at OPEN time (TradingView convention)
- `TF_DAYS["1d"] = 90` (was 365) — 3-month default view for daily charts
- `fitKey` increments on each `loadInitial` → CandlestickChart resets `didFitContent` → always refit on TF change

### Backend Startup
```
cd backend
.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000 > /tmp/backend.log 2>&1 &
```
**Do NOT use `--reload`** — file watching broken on this machine. Kill and restart after code changes.

---

## Known Gotchas

| Issue | Fix |
|---|---|
| `npx playwright test` version conflict | Use `node_modules/.bin/playwright test` |
| Docker must be running for Redis | `open -a Docker` then `docker start infra-redis-1` |
| Upstox token expires daily | Re-auth each morning via OAuth popup |
| KiteMCP session expires | Click "Connect Kite" button in Dashboard TopBar |
| FnO stale cache on MCP failure | Redis serves last snapshot with `stale: true` |
| NSE equity charts need Upstox token | ISIN lookup requires instruments file (NSE.json.gz works, NFO.json.gz is 403) |
| FnO expiry on expiry day | Shows current-day expiry; next expiry after 3:30 PM IST (manual refresh needed) |
| Symbol search indices | DB has `NSE_NIFTY_50` → normalized to `NIFTY 50` in `_build_symbol_cache` |
| ChartUnit standalone (FnO modal) | Must use `_EMPTY` const for useDashboardStore selector — never inline `[]` |
