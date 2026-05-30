# Multi-Chart Live Trading Dashboard — Design Spec

**Date:** 2026-05-30
**Status:** Approved
**Replaces:** `/chart/:symbol` single-chart page

---

## Goal

Replace the existing single-symbol chart page with a configurable multi-pane live trading dashboard. Up to 8 independent chart panes, each with its own symbol, timeframe, live price feed, and indicator set. All configuration persists across page reloads.

---

## Scope

### In scope (Phase 1)

- Market Status Bar: persistent strip above the grid showing live open/closed status for Indian, US, and crypto markets
- Multi-pane grid: 1 / 2 / 4 / 6 / 8 panes with optimal layouts
- Per-pane: symbol picker, timeframe picker, candlestick chart, ticker bar
- Live prices: Upstox WebSocket v3 (NSE equities) + Hyperliquid WebSocket (crypto)
- Backend unified `/ws/market` endpoint — frontend never talks to brokers directly
- Pluggable broker adapter protocol — adding a new broker = one file
- Two-layer indicator panel: list view → per-indicator settings (Inputs / Style / Visibility)
- Indicator library: EMA, SMA, BB, VWAP, RSI, MACD, Stoch (existing) + Volume Profile + Fair Value Gap (new)
- Color-coded ticker bar per pane — flashes green/red on each price tick
- All settings (pane count, symbols, timeframes, indicators + their config) persisted via Zustand + localStorage
- Upstox OAuth: manual daily re-auth via "Connect Upstox" button in top bar
- Historical OHLCV: existing `/technical/ohlcv/{symbol}` for NSE; new `/market/ohlcv?symbol=CRYPTO:BTC&tf=1h` using yfinance (`BTC-USD` mapping) for crypto history

### Out of scope (Phase 2)

- Custom indicator scripting (Pine Script-like extensibility)
- Automated Upstox token refresh via Notifier Webhook
- Order execution from chart panes
- Alpaca / Binance / Zerodha adapters (protocol defined, implementations deferred)
- Backtest panel per pane (backtest remains on the existing single-chart page for now)

---

## Architecture

### Frontend

```
frontend/src/
├── pages/
│   └── Dashboard.tsx               # Replaces Chart.tsx. Grid + pane count selector.
├── components/
│   ├── Dashboard/
│   │   ├── PaneGrid.tsx            # CSS grid renderer: 1→full, 2→50/50, 4→2×2, 6→3×2, 8→4×2
│   │   ├── ChartPane.tsx           # Single pane: TickerBar + CandlestickChart + active-indicator strip
│   │   ├── TickerBar.tsx           # Symbol · TF · LTP (flash) · Change% · O H L C V
│   │   ├── PaneControls.tsx        # Symbol dropdown (search) + TF dropdown per pane
│   │   └── IndicatorPanel.tsx      # Two-layer slide-in panel (list → settings)
│   └── Chart/
│       ├── CandlestickChart.tsx    # UNCHANGED (reused inside each pane)
│       ├── indicators.ts           # EXTENDED: add calcVolumeProfile(), calcFVG()
│       └── types.ts                # EXTENDED: IndicatorDef registry type
├── store/
│   ├── dashboard.ts                # Zustand: paneCount, panes[{id, symbol, tf, dataSource, indicators[]}], persist
│   └── liveQuotes.ts               # Zustand: symbol → Quote (ltp, open, high, low, close, volume, ts)
└── lib/
    └── marketWs.ts                 # WebSocket client for /ws/market; manages subscribe/unsubscribe
```

### Backend

```
backend/
├── brokers/
│   ├── base.py                     # BrokerAdapter Protocol + Quote dataclass
│   ├── upstox.py                   # UpstoxAdapter: OAuth flow, WS v3, protobuf decode
│   └── hyperliquid.py              # HyperliquidAdapter: direct WS, JSON
├── api/
│   ├── market_ws.py                # /ws/market handler: subscribe/unsubscribe, fan-out
│   └── routers/
│       └── market.py               # GET /market/ohlcv (yfinance fallback for crypto history)
│                                   # GET /auth/upstox/login + GET /auth/upstox/callback
└── workers/
    └── market_feed_manager.py      # Singleton: broker connections + subscriber map
```

---

## Data Flow

```
Browser
  └── marketWs.ts
        ├── connect: ws://localhost:8000/ws/market?token=JWT
        ├── send: {"action":"subscribe","symbols":["NSE:RELIANCE","CRYPTO:BTC"]}
        └── recv: {"symbol":"NSE:RELIANCE","ltp":2847.50,"open":2831,"high":2860,"low":2820,"close":2847,"volume":1234567,"ts":"2026-05-30T09:30:00Z"}

FastAPI /ws/market
  └── MarketFeedManager (singleton)
        ├── NSE:* → UpstoxAdapter (WS v3 protobuf → decode → normalize Quote)
        └── CRYPTO:* → HyperliquidAdapter (WS JSON → normalize Quote)

UpstoxAdapter
  ├── GET /auth/upstox/callback → store access_token in Redis (key: upstox:token)
  ├── GET /v2/feed/market-data-feed/authorize → get authorized WS URL
  ├── connect WSS with binary protobuf messages
  ├── decode with MarketDataFeed.proto → normalize to Quote
  └── fan-out to all subscribed browser clients
```

---

## Broker Adapter Protocol

```python
# backend/brokers/base.py
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Protocol

@dataclass
class Quote:
    symbol: str          # canonical: "NSE:RELIANCE", "CRYPTO:BTC"
    ltp: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    ts: datetime

class BrokerAdapter(Protocol):
    """Implement this to add a new broker. One file, one class."""
    name: str
    symbol_prefix: str   # e.g. "NSE", "BSE", "CRYPTO", "US"

    async def connect(self) -> None: ...
    async def subscribe(self, symbols: list[str]) -> None: ...
    async def unsubscribe(self, symbols: list[str]) -> None: ...
    async def quotes(self) -> AsyncIterator[Quote]: ...
    async def disconnect(self) -> None: ...
```

**Adding a new broker:** Create `backend/brokers/alpaca.py`, implement `BrokerAdapter`, register in `MarketFeedManager`. No other files change.

---

## Symbol Routing

| Symbol prefix | Adapter | Example |
|---|---|---|
| `NSE:` | UpstoxAdapter | `NSE:RELIANCE`, `NSE:NIFTY50` |
| `BSE:` | UpstoxAdapter | `BSE:500325` |
| `CRYPTO:` | HyperliquidAdapter | `CRYPTO:BTC`, `CRYPTO:ETH` |
| `US:` | *(Phase 2 — AlpacaAdapter)* | `US:AAPL` |

Symbol picker in each pane shows a dropdown that searches both NSE symbols (from existing `/technical/symbols` endpoint) and a hardcoded list of top Hyperliquid perpetuals (BTC, ETH, SOL, BNB, DOGE, XRP, AVAX, MATIC, ARB, OP).

---

## Grid Layouts

| Pane count | CSS grid | Layout |
|---|---|---|
| 1 | `1fr` | Full screen |
| 2 | `1fr 1fr` | Side by side |
| 4 | `1fr 1fr / 1fr 1fr` | 2×2 |
| 6 | `1fr 1fr 1fr / 1fr 1fr` | 3×2 |
| 8 | `1fr 1fr 1fr 1fr / 1fr 1fr` | 4×2 |

Pane count selector: dropdown at top bar (`1 / 2 / 4 / 6 / 8`). Adding panes initializes new panes with defaults; removing panes preserves remaining pane configs.

---

## Per-Pane State (persisted to localStorage)

```typescript
interface PaneConfig {
  id: string;                    // stable uuid
  symbol: string;                // e.g. "NSE:RELIANCE"
  timeframe: string;             // e.g. "15min"
  dataSource: "upstox" | "hyperliquid" | "auto"; // auto = route by prefix
  indicators: IndicatorConfig[]; // per-pane indicator list
}

interface IndicatorConfig {
  id: string;           // uuid, stable across sessions
  type: IndicatorType;  // "EMA" | "SMA" | "BB" | "VWAP" | "RSI" | "MACD" | "Stoch" | "VolumeProfile" | "FVG"
  inputs: Record<string, number | string | boolean>;  // e.g. { period: 9 }
  style: Record<string, string>;                      // e.g. { color: "#f59e0b" }
  visible: boolean;
}
```

---

## Market Status Bar

Persistent strip rendered **above** the chart grid (below the top bar controls). Pure frontend — no API calls. Recomputes every 30 seconds via `setInterval`.

### Markets displayed

| Market | Exchange | Session (local time) | Timezone | Pre/After hours |
|---|---|---|---|---|
| 🇮🇳 India | NSE / BSE | 09:15 – 15:30 Mon–Fri | Asia/Kolkata (IST) | Pre: 09:00–09:15 |
| 🇺🇸 US | NYSE / NASDAQ | 09:30 – 16:00 Mon–Fri | America/New_York (ET) | Pre: 04:00–09:30 · After: 16:00–20:00 |
| ₿ Crypto | 24/7 | Always open | UTC | — |

### Status states per market

- **OPEN** — green dot + green label + countdown to close (`closes in 2h 14m`)
- **PRE-MARKET** — amber dot + "PRE" label (US only)
- **AFTER-HOURS** — amber dot + "AFTER" label (US only)
- **CLOSED** — grey dot + "CLOSED" + countdown to next open (`opens in 17h 30m`)
- **WEEKEND** — grey dot + "CLOSED" + `opens Mon 09:15 IST`

### Layout (each market card)

```
[● OPEN]  India NSE     09:15–15:30 IST    closes in 2h 14m    13:16 IST
[● PRE ]  US NYSE       09:30–16:00 ET     opens in 0h 22m     22:08 IST
[∞ 24/7]  Crypto        Always open        BTC 67,420          UTC 17:38
```

Each card shows: status dot · market name · session hours · time remaining · current local time for that market.

Crypto card shows live BTC LTP from `liveQuotes` store instead of a countdown (since it never closes).

### Component

```
frontend/src/components/Dashboard/MarketStatusBar.tsx
```

Pure computation using `Intl.DateTimeFormat` for timezone conversion. No external dependency. Updates every 30 seconds. Mounts once at Dashboard level, always visible regardless of pane count.

---

## Ticker Bar

Displayed at the top of each pane. Fields: `Symbol | Timeframe | LTP | Change% | O | H | L | C | Volume`

Flash behaviour:
- LTP ticks **up** → green flash (CSS `@keyframes flash-green`: background `#26a69a33` → transparent, 600ms)
- LTP ticks **down** → red flash (CSS `@keyframes flash-red`: background `#ef535033` → transparent, 600ms)
- Flash triggered by comparing new `ltp` vs previous `ltp` in `liveQuotes` Zustand store

---

## Indicator Panel — Two Layers

### Layer 1: List view
- Triggered by clicking "⊕ Indicators" button in the focused pane's active-indicator strip
- Slides in from the right (CSS transform transition)
- Header: "Indicators" + close ✕
- Search box (filters the list)
- Two sections: **Overlays** and **Oscillators**
- Each row: indicator name + action button
  - Not added: `+` button → adds with defaults, stays on list
  - Already added: `⚙` button → drills to Layer 2

### Layer 2: Settings view
- Triggered by clicking ⚙ on any active indicator
- Header: `← Back` (returns to Layer 1) + indicator name + close ✕
- Three tabs: **Inputs** | **Style** | **Visibility**
  - **Inputs**: numeric/boolean fields specific to each indicator (see table below)
  - **Style**: color swatches + line width for each series in the indicator
  - **Visibility**: checkboxes for which timeframes/panes to show on
- Footer: **Cancel** | **Apply** (Apply updates Zustand + rerenders chart)

### Indicator definitions (Phase 1 hardcoded)

| Type | Inputs | Style |
|---|---|---|
| EMA | period (int) | color |
| SMA | period (int) | color |
| Bollinger Bands | period (int), std (float) | upper color, mid color, lower color |
| VWAP | *(none)* | color |
| RSI | period (int) | color, overbought level, oversold level |
| MACD | fast (int), slow (int), signal (int) | macd color, signal color |
| Stochastic | k (int), d (int), smooth (int) | k color, d color |
| Volume Profile | rows (int), value area pct (int) | up color, down color, poc color, show poc (bool) |
| Fair Value Gap | min gap pct (float), show labels (bool), extend boxes (bool) | bull color, bear color, opacity |

---

## Volume Profile Implementation

Computed on the frontend from the visible bars:
1. Find `[minLow, maxHigh]` across all bars in view
2. Divide into `rows` equal price buckets
3. For each bar, add volume to the bucket that contains its close price
4. Split each bucket into up-volume (close ≥ open) and down-volume (close < open)
5. Find POC (Point of Control) = bucket with highest total volume
6. Render using lightweight-charts custom series (horizontal histogram)

---

## Fair Value Gap Implementation

Computed on the frontend from OHLC bars:
- **Bullish FVG**: `bars[i+2].low > bars[i].high` (gap up — candle i's high doesn't overlap candle i+2's low)
- **Bearish FVG**: `bars[i+2].high < bars[i].low` (gap down)
- Rendered as semi-transparent rectangle overlays on the chart using lightweight-charts v5 custom series (filled price-range boxes)
- Boxes extend to the right unless `extend_boxes = false`
- Optional label: "FVG" text at the left edge

---

## Upstox OAuth Flow

1. Top bar shows **"Connect Upstox"** button when no token in Redis
2. User clicks → browser opens `https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id={API_KEY}&redirect_uri=http://127.0.0.1:8000/auth/upstox/callback`
3. User logs in to Upstox → redirected to `/auth/upstox/callback?code=XYZ`
4. Backend exchanges code for `access_token` → stores in Redis key `upstox:token` (TTL: 24h)
5. Top bar button changes to **"● Upstox"** (green dot)
6. `UpstoxAdapter` reads token from Redis on connect

Config (`.env`):
```
UPSTOX_API_KEY=<your-api-key>
UPSTOX_API_SECRET=<your-api-secret>
```

---

## Persistent State

All dashboard config stored via Zustand `persist` middleware:

```typescript
// localStorage key: "trading-dashboard"
{
  paneCount: 4,
  panes: [
    { id: "abc", symbol: "NSE:RELIANCE", timeframe: "15min", dataSource: "auto", indicators: [...] },
    { id: "def", symbol: "CRYPTO:BTC",   timeframe: "1h",    dataSource: "auto", indicators: [...] },
    ...
  ]
}
```

On reload: grid reconstructs from localStorage → each pane loads its saved symbol/TF/indicators immediately → subscribes to live feed.

---

## Routing Changes

| Before | After |
|---|---|
| `/chart/:symbol` | `/chart` (no param — dashboard is the page) |
| Sidebar "Charts" → `/chart/RELIANCE` | Sidebar "Charts" → `/chart` |

Old `/chart/:symbol` links redirect to `/chart` (React Router `<Navigate>`).

---

## Backend Dependencies (new)

- `upstox-python` or raw `websockets` + `protobuf` (for Upstox WS v3 binary decoding)
- `MarketDataFeed.proto` from `https://assets.upstox.com/feed/market-data-feed/v3/MarketDataFeed.proto`
- `websockets` (already likely available; used for Hyperliquid WS)
- `yfinance` (already available; fallback for crypto OHLCV history)

---

## Frontend Dependencies (new)

- `zustand` (already present)
- No new packages — custom series for Volume Profile uses existing lightweight-charts v5 API

---

## File Change Summary

| File | Change |
|---|---|
| `frontend/src/pages/Dashboard.tsx` | NEW |
| `frontend/src/pages/Chart.tsx` | DELETE (replaced by Dashboard) |
| `frontend/src/components/Dashboard/MarketStatusBar.tsx` | NEW |
| `frontend/src/components/Dashboard/PaneGrid.tsx` | NEW |
| `frontend/src/components/Dashboard/ChartPane.tsx` | NEW |
| `frontend/src/components/Dashboard/TickerBar.tsx` | NEW |
| `frontend/src/components/Dashboard/PaneControls.tsx` | NEW |
| `frontend/src/components/Dashboard/IndicatorPanel.tsx` | NEW |
| `frontend/src/components/Chart/indicators.ts` | EXTEND (add VP + FVG) |
| `frontend/src/components/Chart/types.ts` | EXTEND (IndicatorDef registry) |
| `frontend/src/store/dashboard.ts` | NEW |
| `frontend/src/store/liveQuotes.ts` | NEW |
| `frontend/src/lib/marketWs.ts` | NEW |
| `frontend/src/App.tsx` | MODIFY (route `/chart` → Dashboard) |
| `frontend/src/components/Layout/Sidebar.tsx` | MODIFY (Charts nav → `/chart`) |
| `backend/brokers/base.py` | NEW |
| `backend/brokers/upstox.py` | NEW |
| `backend/brokers/hyperliquid.py` | NEW |
| `backend/api/market_ws.py` | NEW |
| `backend/api/routers/market.py` | NEW |
| `backend/workers/market_feed_manager.py` | NEW |
| `backend/api/main.py` | MODIFY (add /ws/market, /auth/upstox/*, /market router) |
| `backend/core/config.py` | MODIFY (add UPSTOX_API_KEY, UPSTOX_API_SECRET) |

---

## Phase 2 Hooks (not implemented now, designed for extensibility)

- `IndicatorDef` registry: array of `{ type, label, category, defaultInputs, defaultStyle, compute, render }` — adding an indicator = push to this array
- `BrokerAdapter` protocol already defined — Alpaca/Binance = one file each
- `IndicatorConfig.inputs` is `Record<string, any>` — arbitrary inputs supported without schema changes
