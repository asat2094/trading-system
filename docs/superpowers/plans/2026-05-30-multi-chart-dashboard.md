# Multi-Chart Live Trading Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `/chart/:symbol` with a configurable multi-pane live dashboard — 1/2/4/6/8 panes, Upstox WS v3 + Hyperliquid WS for live prices, two-layer indicator panel (Volume Profile + FVG added), market status bar, all settings persisted to localStorage.

**Architecture:** Backend exposes a single `/ws/market` WebSocket that routes symbols to broker adapters (`NSE:*` → UpstoxAdapter, `CRYPTO:*` → HyperliquidAdapter) and normalises all quotes to `{symbol, ltp, open, high, low, close, volume, ts}` before broadcasting to browser clients. Frontend uses Zustand `persist` for pane configs (symbol, TF, indicators) and a separate in-memory `liveQuotes` store for tick data. `CandlestickChart` is reused unchanged inside each pane.

**Tech Stack:** Python 3.12, FastAPI, websockets, protobuf 5.x, redis-py; React 19, TypeScript, Zustand 5 (persist), lightweight-charts v5, Vite

---

## File Structure

```
backend/
  brokers/__init__.py
  brokers/base.py                     ← BrokerAdapter Protocol + Quote
  brokers/upstox.py                   ← OAuth + WS v3 + protobuf decode
  brokers/hyperliquid.py              ← WS allMids JSON
  brokers/upstox_proto/
    __init__.py
    MarketDataFeed_pb2.py             ← generated, committed
  api/market_ws.py                    ← /ws/market handler + MarketFeedManager
  api/routers/market.py               ← GET /market/ohlcv, GET /auth/upstox/*
  core/config.py                      ← +UPSTOX_API_KEY, UPSTOX_API_SECRET
  api/main.py                         ← wire new routes

frontend/src/
  store/dashboard.ts                  ← Zustand persist: paneCount + panes[]
  store/liveQuotes.ts                 ← Zustand in-memory: symbol→Quote
  lib/marketWs.ts                     ← WS client singleton
  components/Dashboard/
    MarketStatusBar.tsx               ← India/US/Crypto open+closed strip
    PaneGrid.tsx                      ← CSS grid 1/2/4/6/8
    ChartPane.tsx                     ← composed pane
    TickerBar.tsx                     ← LTP flash bar
    PaneControls.tsx                  ← symbol search + TF dropdown
    IndicatorPanel.tsx                ← two-layer list↔settings
  components/Chart/types.ts           ← +VolumeProfile +FVG union variants
  components/Chart/indicators.ts      ← +calcVolumeProfile +calcFVG
  pages/Dashboard.tsx                 ← new chart page
  App.tsx                             ← /chart route → Dashboard
  components/Layout/Sidebar.tsx       ← Charts → /chart
```

---

## Task 1: Backend deps + config + BrokerAdapter protocol

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/core/config.py`
- Create: `backend/brokers/__init__.py`
- Create: `backend/brokers/base.py`
- Create: `backend/tests/unit/test_broker_base.py`

- [ ] **Step 1: Add dependencies to pyproject.toml**

Open `backend/pyproject.toml`. In the `dependencies` list add:
```
"websockets>=12.0",
"protobuf>=5.0",
```

- [ ] **Step 2: Install**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/backend
.venv/bin/pip install "websockets>=12.0" "protobuf>=5.0"
```

- [ ] **Step 3: Add settings to core/config.py**

Open `backend/core/config.py`. After `SHOONYA_MAX_CONCURRENT`:
```python
    # Upstox
    UPSTOX_API_KEY: str = ""
    UPSTOX_API_SECRET: str = ""
```

- [ ] **Step 4: Add to .env**

Open `/Users/ankitatiwari/Desktop/claude-playground/trading-system/.env` and append:
```
UPSTOX_API_KEY=<your-key>
UPSTOX_API_SECRET=<your-secret>
```

- [ ] **Step 5: Create brokers/__init__.py**

```python
# backend/brokers/__init__.py
```

- [ ] **Step 6: Write failing test**

Create `backend/tests/unit/test_broker_base.py`:
```python
"""Tests for Quote dataclass and symbol-routing helpers."""
from datetime import datetime, timezone
from brokers.base import Quote, broker_prefix


def test_quote_fields():
    q = Quote(
        symbol="NSE:RELIANCE", ltp=2847.5, open=2831.0,
        high=2860.0, low=2820.0, close=2847.5, volume=1_000_000,
        ts=datetime(2026, 5, 30, 9, 30, tzinfo=timezone.utc),
    )
    assert q.symbol == "NSE:RELIANCE"
    assert q.ltp == 2847.5


def test_broker_prefix_nse():
    assert broker_prefix("NSE:RELIANCE") == "NSE"


def test_broker_prefix_crypto():
    assert broker_prefix("CRYPTO:BTC") == "CRYPTO"


def test_broker_prefix_no_colon():
    assert broker_prefix("RELIANCE") == ""
```

- [ ] **Step 7: Run — expect fail**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
backend/.venv/bin/python -m pytest backend/tests/unit/test_broker_base.py -v 2>&1 | head -15
```
Expected: `ModuleNotFoundError: No module named 'brokers'`

- [ ] **Step 8: Implement brokers/base.py**

```python
"""Shared types and protocol for broker adapters."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import AsyncIterator, Protocol, runtime_checkable


@dataclass
class Quote:
    symbol: str       # canonical: "NSE:RELIANCE", "CRYPTO:BTC"
    ltp: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    ts: datetime

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d


def broker_prefix(symbol: str) -> str:
    """Return exchange prefix, e.g. 'NSE' from 'NSE:RELIANCE'. '' if no colon."""
    return symbol.split(":")[0] if ":" in symbol else ""


@runtime_checkable
class BrokerAdapter(Protocol):
    """One file per broker. Implement this protocol to add a data source."""
    name: str            # e.g. "upstox"
    prefixes: list[str]  # e.g. ["NSE", "BSE"]

    async def connect(self) -> None: ...
    async def subscribe(self, symbols: list[str]) -> None: ...
    async def unsubscribe(self, symbols: list[str]) -> None: ...
    async def quotes(self) -> AsyncIterator[Quote]: ...
    async def disconnect(self) -> None: ...
```

- [ ] **Step 9: Run — expect pass**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/test_broker_base.py -v
```
Expected: 4 passed.

- [ ] **Step 10: Commit**

```bash
git add backend/pyproject.toml backend/core/config.py backend/brokers/__init__.py backend/brokers/base.py backend/tests/unit/test_broker_base.py
git commit -m "feat: add BrokerAdapter protocol + Quote dataclass + Upstox/Hyperliquid config"
```

---

## Task 2: Upstox protobuf + UpstoxAdapter

**Files:**
- Create: `backend/brokers/upstox_proto/__init__.py`
- Create: `backend/brokers/upstox_proto/MarketDataFeed_pb2.py` (generated)
- Create: `backend/brokers/upstox.py`

- [ ] **Step 1: Download and compile Upstox proto**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/backend/brokers
mkdir -p upstox_proto
curl -o upstox_proto/MarketDataFeed.proto \
  https://assets.upstox.com/feed/market-data-feed/v3/MarketDataFeed.proto

# Install grpcio-tools for protoc
.venv/bin/pip install grpcio-tools

# Compile
.venv/bin/python -m grpc_tools.protoc \
  -I upstox_proto \
  --python_out=upstox_proto \
  upstox_proto/MarketDataFeed.proto

touch upstox_proto/__init__.py
ls upstox_proto/
```

Expected output includes `MarketDataFeed_pb2.py`.

- [ ] **Step 2: Verify proto import**

```bash
PYTHONPATH=. .venv/bin/python -c "
from brokers.upstox_proto import MarketDataFeed_pb2
print('Proto OK:', dir(MarketDataFeed_pb2))
"
```

- [ ] **Step 3: Implement brokers/upstox.py**

```python
"""Upstox broker adapter — WS v3 + protobuf market data feed."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncIterator

import httpx
import websockets

from brokers.base import BrokerAdapter, Quote
from brokers.upstox_proto import MarketDataFeed_pb2

log = logging.getLogger(__name__)

_UPSTOX_AUTH_URL = "https://api.upstox.com/v2/login/authorization/token"
_UPSTOX_FEED_AUTH = "https://api.upstox.com/v3/feed/market-data-feed/authorize"

# NSE index tickers that need NSE_INDEX| prefix (not NSE_EQ|)
_NSE_INDICES = {"NIFTY 50", "NIFTY50", "BANKNIFTY", "NIFTY BANK", "MIDCPNIFTY",
                "FINNIFTY", "SENSEX"}


def _to_upstox_key(symbol: str) -> str:
    """'NSE:RELIANCE' → 'NSE_EQ|RELIANCE'  |  'NSE:NIFTY 50' → 'NSE_INDEX|Nifty 50'"""
    if ":" not in symbol:
        return symbol
    exch, ticker = symbol.split(":", 1)
    if ticker.upper().replace(" ", "") in {i.upper().replace(" ", "") for i in _NSE_INDICES}:
        return f"{exch}_INDEX|{ticker}"
    return f"{exch}_EQ|{ticker}"


class UpstoxAdapter:
    name = "upstox"
    prefixes = ["NSE", "BSE"]

    def __init__(self, api_key: str, api_secret: str, redis_client) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._redis = redis_client
        self._ws = None
        self._queue: asyncio.Queue[Quote] = asyncio.Queue()
        self._subscribed: set[str] = set()

    async def _get_token(self) -> str | None:
        return await self._redis.get("upstox:token")

    async def _get_ws_url(self, token: str) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                _UPSTOX_FEED_AUTH,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()["data"]["authorizedRedirectUri"]

    async def connect(self) -> None:
        token = await self._get_token()
        if not token:
            log.warning("upstox_no_token: call /auth/upstox/login first")
            return
        ws_url = await self._get_ws_url(token)
        self._ws = await websockets.connect(ws_url)
        log.info("upstox_connected")
        asyncio.create_task(self._recv_loop())

    async def subscribe(self, symbols: list[str]) -> None:
        if not self._ws:
            return
        keys = [_to_upstox_key(s) for s in symbols]
        self._subscribed.update(symbols)
        msg = json.dumps({
            "guid": "mf-sub",
            "method": "sub",
            "data": {"mode": "full", "instrumentKeys": keys},
        })
        await self._ws.send(msg)

    async def unsubscribe(self, symbols: list[str]) -> None:
        if not self._ws:
            return
        keys = [_to_upstox_key(s) for s in symbols]
        for s in symbols:
            self._subscribed.discard(s)
        msg = json.dumps({
            "guid": "mf-unsub",
            "method": "unsub",
            "data": {"instrumentKeys": keys},
        })
        await self._ws.send(msg)

    async def _recv_loop(self) -> None:
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    self._decode_and_enqueue(raw)
        except Exception as exc:
            log.warning("upstox_recv_error", error=str(exc))

    def _decode_and_enqueue(self, data: bytes) -> None:
        try:
            feed_resp = MarketDataFeed_pb2.FeedResponse()
            feed_resp.ParseFromString(data)
            for instrument_key, feed in feed_resp.feeds.items():
                # Convert "NSE_EQ|RELIANCE" back to "NSE:RELIANCE"
                symbol = instrument_key.replace("_EQ|", ":").replace("_INDEX|", ":").replace("_FO|", ":")
                ff = feed.ff.marketFF if feed.HasField("ff") else None
                if ff is None:
                    continue
                q = Quote(
                    symbol=symbol,
                    ltp=ff.ltpc.ltp,
                    open=ff.ohlc.open,
                    high=ff.ohlc.high,
                    low=ff.ohlc.low,
                    close=ff.ohlc.close,
                    volume=ff.ltpc.ltq,  # last traded quantity; sum for day volume below
                    ts=datetime.now(timezone.utc),
                )
                self._queue.put_nowait(q)
        except Exception as exc:
            log.debug("upstox_decode_error", error=str(exc))

    async def quotes(self) -> AsyncIterator[Quote]:
        while True:
            yield await self._queue.get()

    async def disconnect(self) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None
```

- [ ] **Step 4: Smoke-test import**

```bash
PYTHONPATH=backend backend/.venv/bin/python -c "
from brokers.upstox import UpstoxAdapter, _to_upstox_key
assert _to_upstox_key('NSE:RELIANCE') == 'NSE_EQ|RELIANCE'
assert _to_upstox_key('NSE:NIFTY 50') == 'NSE_INDEX|NIFTY 50'
print('UpstoxAdapter import OK')
"
```

- [ ] **Step 5: Commit**

```bash
git add backend/brokers/upstox_proto/ backend/brokers/upstox.py
git commit -m "feat: add UpstoxAdapter with WS v3 + protobuf decode"
```

---

## Task 3: HyperliquidAdapter

**Files:**
- Create: `backend/brokers/hyperliquid.py`
- Create: `backend/tests/unit/test_hyperliquid_adapter.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_hyperliquid_adapter.py
"""Tests for HyperliquidAdapter symbol parsing."""
from brokers.hyperliquid import _to_hl_coin, _from_hl_coin


def test_to_hl_coin():
    assert _to_hl_coin("CRYPTO:BTC") == "BTC"
    assert _to_hl_coin("CRYPTO:ETH") == "ETH"


def test_from_hl_coin():
    assert _from_hl_coin("BTC") == "CRYPTO:BTC"
    assert _from_hl_coin("SOL") == "CRYPTO:SOL"
```

- [ ] **Step 2: Run — expect fail**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/test_hyperliquid_adapter.py -v 2>&1 | head -10
```

- [ ] **Step 3: Implement brokers/hyperliquid.py**

```python
"""Hyperliquid broker adapter — allMids WebSocket feed."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncIterator

import websockets

from brokers.base import Quote

log = logging.getLogger(__name__)

_HL_WS_URL = "wss://api.hyperliquid.xyz/ws"

# Top perpetuals available on Hyperliquid
SUPPORTED_COINS = [
    "BTC", "ETH", "SOL", "BNB", "DOGE", "XRP", "AVAX",
    "MATIC", "ARB", "OP", "SUI", "APT", "INJ", "TIA",
]


def _to_hl_coin(symbol: str) -> str:
    """'CRYPTO:BTC' → 'BTC'"""
    return symbol.split(":", 1)[1] if ":" in symbol else symbol


def _from_hl_coin(coin: str) -> str:
    """'BTC' → 'CRYPTO:BTC'"""
    return f"CRYPTO:{coin}"


class HyperliquidAdapter:
    name = "hyperliquid"
    prefixes = ["CRYPTO"]

    def __init__(self) -> None:
        self._ws = None
        self._queue: asyncio.Queue[Quote] = asyncio.Queue()
        self._subscribed: set[str] = set()
        self._last_mids: dict[str, float] = {}

    async def connect(self) -> None:
        self._ws = await websockets.connect(_HL_WS_URL)
        log.info("hyperliquid_connected")
        asyncio.create_task(self._recv_loop())
        # Subscribe to allMids — one subscription covers all coins
        await self._ws.send(json.dumps({
            "method": "subscribe",
            "subscription": {"type": "allMids"},
        }))

    async def subscribe(self, symbols: list[str]) -> None:
        for s in symbols:
            self._subscribed.add(s)

    async def unsubscribe(self, symbols: list[str]) -> None:
        for s in symbols:
            self._subscribed.discard(s)

    async def _recv_loop(self) -> None:
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if msg.get("channel") == "allMids":
                    mids: dict[str, str] = msg.get("data", {}).get("mids", {})
                    ts = datetime.now(timezone.utc)
                    for coin, mid_str in mids.items():
                        canonical = _from_hl_coin(coin)
                        if canonical not in self._subscribed:
                            continue
                        try:
                            ltp = float(mid_str)
                        except ValueError:
                            continue
                        prev = self._last_mids.get(coin, ltp)
                        self._last_mids[coin] = ltp
                        # Hyperliquid allMids has no OHLCV — use ltp for all price fields
                        # Historical OHLCV comes from yfinance via /market/ohlcv endpoint
                        q = Quote(
                            symbol=canonical,
                            ltp=ltp,
                            open=prev,   # approximate; will be overridden by REST history
                            high=max(ltp, prev),
                            low=min(ltp, prev),
                            close=ltp,
                            volume=0.0,
                            ts=ts,
                        )
                        self._queue.put_nowait(q)
        except Exception as exc:
            log.warning("hyperliquid_recv_error", error=str(exc))

    async def quotes(self) -> AsyncIterator[Quote]:
        while True:
            yield await self._queue.get()

    async def disconnect(self) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None
```

- [ ] **Step 4: Run tests**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/test_hyperliquid_adapter.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/brokers/hyperliquid.py backend/tests/unit/test_hyperliquid_adapter.py
git commit -m "feat: add HyperliquidAdapter (allMids WS feed)"
```

---

## Task 4: MarketFeedManager + /ws/market handler + /market router

**Files:**
- Create: `backend/api/market_ws.py`
- Create: `backend/api/routers/market.py`
- Modify: `backend/api/main.py`

- [ ] **Step 1: Create backend/api/market_ws.py**

```python
"""
/ws/market — unified live market data WebSocket.

Protocol:
  Client→Server: {"action": "subscribe",   "symbols": ["NSE:RELIANCE", "CRYPTO:BTC"]}
  Client→Server: {"action": "unsubscribe", "symbols": ["NSE:RELIANCE"]}
  Server→Client: {"type": "quote", "symbol": "NSE:RELIANCE", "ltp": 2847.5, ...}
  Server→Client: {"type": "broker_status", "upstox": "connected", "hyperliquid": "connected"}
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket, WebSocketDisconnect

from brokers.base import BrokerAdapter, Quote, broker_prefix
from core.auth.middleware import _get_provider

log = logging.getLogger(__name__)


class MarketFeedManager:
    """Singleton. Holds broker adapters + subscriber map. Created once at app startup."""

    def __init__(self) -> None:
        self._adapters: dict[str, BrokerAdapter] = {}   # prefix → adapter
        # symbol → set of WebSocket clients
        self._subs: dict[str, set[WebSocket]] = defaultdict(set)
        self._started = False

    def register(self, adapter: BrokerAdapter) -> None:
        for prefix in adapter.prefixes:
            self._adapters[prefix] = adapter

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        for adapter in set(self._adapters.values()):
            try:
                await adapter.connect()
                asyncio.create_task(self._fan_out(adapter))
            except Exception as exc:
                log.warning("adapter_connect_failed", adapter=adapter.name, error=str(exc))

    async def _fan_out(self, adapter: BrokerAdapter) -> None:
        async for quote in adapter.quotes():
            ws_set = self._subs.get(quote.symbol, set())
            if not ws_set:
                continue
            msg = json.dumps({"type": "quote", **quote.to_dict()})
            dead: list[WebSocket] = []
            for ws in list(ws_set):
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._cleanup_ws(ws)

    async def add_client(self, ws: WebSocket, symbols: list[str]) -> None:
        for sym in symbols:
            was_empty = not self._subs[sym]
            self._subs[sym].add(ws)
            if was_empty:
                prefix = broker_prefix(sym)
                adapter = self._adapters.get(prefix)
                if adapter:
                    try:
                        await adapter.subscribe([sym])
                    except Exception as exc:
                        log.debug("subscribe_error", sym=sym, error=str(exc))

    async def remove_client(self, ws: WebSocket, symbols: list[str]) -> None:
        for sym in symbols:
            self._subs[sym].discard(ws)
            if not self._subs[sym]:
                prefix = broker_prefix(sym)
                adapter = self._adapters.get(prefix)
                if adapter:
                    try:
                        await adapter.unsubscribe([sym])
                    except Exception:
                        pass

    def _cleanup_ws(self, ws: WebSocket) -> None:
        for sym, ws_set in self._subs.items():
            ws_set.discard(ws)

    def status(self) -> dict:
        result = {}
        for prefix, adapter in self._adapters.items():
            result[adapter.name] = "connected" if getattr(adapter, "_ws", None) else "disconnected"
        return result


# Module-level singleton — created in lifespan
_manager: MarketFeedManager | None = None


def get_manager() -> MarketFeedManager:
    global _manager
    if _manager is None:
        _manager = MarketFeedManager()
    return _manager


async def market_ws_endpoint(ws: WebSocket, token: str) -> None:
    """FastAPI WebSocket handler for /ws/market."""
    provider = _get_provider()
    user = await provider.verify_token(token)
    if user is None:
        await ws.close(code=1008)
        return

    await ws.accept()
    manager = get_manager()
    subscribed: set[str] = set()

    # Send initial broker status
    await ws.send_text(json.dumps({"type": "broker_status", **manager.status()}))

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            action = msg.get("action")
            symbols: list[str] = msg.get("symbols", [])
            if action == "subscribe":
                await manager.add_client(ws, symbols)
                subscribed.update(symbols)
            elif action == "unsubscribe":
                await manager.remove_client(ws, symbols)
                subscribed.difference_update(symbols)
    except WebSocketDisconnect:
        pass
    finally:
        await manager.remove_client(ws, list(subscribed))
```

- [ ] **Step 2: Create backend/api/routers/market.py**

```python
"""
Market data REST endpoints:
  GET /market/ohlcv          — historical OHLCV (crypto via yfinance, NSE via QuestDB)
  GET /auth/upstox/login     — redirect to Upstox OAuth dialog
  GET /auth/upstox/callback  — exchange code for token, store in Redis
  GET /auth/upstox/status    — check if token present in Redis
"""
from __future__ import annotations

from datetime import datetime

import httpx
import yfinance as yf
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from core.auth.middleware import get_current_user
from core.auth.provider import User
from core.cache import get_redis
from core.config import settings

router = APIRouter(tags=["market"])

_CRYPTO_MAP = {
    "BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD",
    "BNB": "BNB-USD", "DOGE": "DOGE-USD", "XRP": "XRP-USD",
    "AVAX": "AVAX-USD", "MATIC": "MATIC-USD", "ARB": "ARB-USD",
    "OP": "OP-USD", "SUI": "SUI-USD", "APT": "APT-USD",
}

_TF_MAP = {
    "1min": "1m", "3min": "3m", "5min": "5m", "15min": "15m",
    "30min": "30m", "1h": "1h", "1d": "1d", "1w": "1wk",
}


@router.get("/market/ohlcv")
async def get_market_ohlcv(
    symbol: str = Query(..., description="e.g. CRYPTO:BTC"),
    tf: str = Query("1d"),
    from_dt: datetime = Query(...),
    to_dt: datetime = Query(...),
    user: User = Depends(get_current_user),
):
    """Return OHLCV bars for crypto symbols via yfinance."""
    if not symbol.startswith("CRYPTO:"):
        raise HTTPException(400, "Only CRYPTO: prefix supported via this endpoint")
    coin = symbol.split(":", 1)[1]
    ticker_sym = _CRYPTO_MAP.get(coin, f"{coin}-USD")
    yf_interval = _TF_MAP.get(tf, "1d")
    try:
        tkr = yf.Ticker(ticker_sym)
        df = tkr.history(start=from_dt.date(), end=to_dt.date(), interval=yf_interval)
        if df.empty:
            return {"rows": []}
        rows = [
            {
                "ts": idx.isoformat(),
                "open": row["Open"], "high": row["High"],
                "low": row["Low"], "close": row["Close"],
                "volume": row["Volume"],
            }
            for idx, row in df.iterrows()
        ]
        return {"rows": rows}
    except Exception as exc:
        raise HTTPException(500, f"yfinance error: {exc}") from exc


@router.get("/auth/upstox/login")
async def upstox_login():
    """Redirect browser to Upstox OAuth dialog."""
    if not settings.UPSTOX_API_KEY:
        raise HTTPException(503, "UPSTOX_API_KEY not configured")
    url = (
        f"https://api.upstox.com/v2/login/authorization/dialog"
        f"?response_type=code"
        f"&client_id={settings.UPSTOX_API_KEY}"
        f"&redirect_uri=http://127.0.0.1:8000/auth/upstox/callback"
    )
    return RedirectResponse(url)


@router.get("/auth/upstox/callback")
async def upstox_callback(code: str = Query(...)):
    """Exchange auth code for access token; store in Redis with 24h TTL."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.upstox.com/v2/login/authorization/token",
            data={
                "code": code,
                "client_id": settings.UPSTOX_API_KEY,
                "client_secret": settings.UPSTOX_API_SECRET,
                "redirect_uri": "http://127.0.0.1:8000/auth/upstox/callback",
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"Upstox token exchange failed: {resp.text}")
    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(502, "No access_token in Upstox response")
    redis = get_redis()
    await redis.setex("upstox:token", 86400, access_token)
    # Close tab / show success
    return {"status": "ok", "message": "Upstox connected. You can close this tab."}


@router.get("/auth/upstox/status")
async def upstox_status(user: User = Depends(get_current_user)):
    """Return whether a valid Upstox token exists in Redis."""
    redis = get_redis()
    token = await redis.get("upstox:token")
    ttl = await redis.ttl("upstox:token") if token else 0
    return {"connected": bool(token), "ttl_seconds": ttl}
```

- [ ] **Step 3: Wire into api/main.py**

Open `backend/api/main.py`. Add imports at the top with other imports:
```python
from api.market_ws import market_ws_endpoint, get_manager
from api.routers.market import router as market_router
```

Inside `create_app()`, after existing `app.include_router(fno.router)`:
```python
    app.include_router(market_router)

    @app.websocket("/ws/market")
    async def market_ws(ws: WebSocket, token: str):
        await market_ws_endpoint(ws, token)
```

Inside the `lifespan` function, after `asyncio.create_task(warm_symbol_cache())`:
```python
    # Start market feed adapters
    from brokers.upstox import UpstoxAdapter
    from brokers.hyperliquid import HyperliquidAdapter
    from core.cache import get_redis

    mgr = get_manager()
    redis = get_redis()
    if settings.UPSTOX_API_KEY:
        mgr.register(UpstoxAdapter(settings.UPSTOX_API_KEY, settings.UPSTOX_API_SECRET, redis))
    mgr.register(HyperliquidAdapter())
    asyncio.create_task(mgr.start())
```

- [ ] **Step 4: Smoke-test backend starts**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/backend
PYTHONPATH=. .venv/bin/python -c "
from api.main import app
routes = [r.path for r in app.routes if hasattr(r, 'path')]
assert '/ws/market' in routes
assert '/market/ohlcv' in routes
assert '/auth/upstox/login' in routes
print('All routes registered OK')
print([r for r in routes if 'market' in r or 'upstox' in r])
"
```

- [ ] **Step 5: Full unit test suite — no regressions**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/ -q --tb=short 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add backend/api/market_ws.py backend/api/routers/market.py backend/api/main.py
git commit -m "feat: add /ws/market + MarketFeedManager + /market/ohlcv + Upstox OAuth endpoints"
```

---

## Task 5: Frontend Zustand stores

**Files:**
- Create: `frontend/src/store/dashboard.ts`
- Create: `frontend/src/store/liveQuotes.ts`

- [ ] **Step 1: Create frontend/src/store/dashboard.ts**

```typescript
/**
 * Dashboard persistent store.
 * Saved to localStorage key "trading-dashboard".
 * Pane configs survive page reload.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type IndicatorType =
  | "EMA" | "SMA" | "BB" | "VWAP" | "RSI" | "MACD" | "Stoch"
  | "VolumeProfile" | "FVG";

export interface IndicatorConfig {
  id: string;
  type: IndicatorType;
  inputs: Record<string, number | string | boolean>;
  style: Record<string, string>;
  visible: boolean;
}

export interface PaneConfig {
  id: string;
  symbol: string;      // "NSE:RELIANCE" | "CRYPTO:BTC"
  timeframe: string;   // "1min" | "5min" | "15min" | "1h" | "1d" etc.
  dataSource: "auto" | "upstox" | "hyperliquid";
  indicators: IndicatorConfig[];
}

const DEFAULT_INDICATOR_INPUTS: Record<IndicatorType, Record<string, number | string | boolean>> = {
  EMA:           { period: 20 },
  SMA:           { period: 20 },
  BB:            { period: 20, std: 2 },
  VWAP:          {},
  RSI:           { period: 14 },
  MACD:          { fast: 12, slow: 26, signal: 9 },
  Stoch:         { k: 14, d: 3, smooth: 3 },
  VolumeProfile: { rows: 24, valueAreaPct: 70 },
  FVG:           { minGapPct: 0.1, showLabels: true, extendBoxes: true },
};

const DEFAULT_INDICATOR_STYLE: Record<IndicatorType, Record<string, string>> = {
  EMA:           { color: "#f7c948" },
  SMA:           { color: "#4caf50" },
  BB:            { upperColor: "#2196f3", midColor: "#888888", lowerColor: "#2196f3" },
  VWAP:          { color: "#ff9800" },
  RSI:           { color: "#ce93d8" },
  MACD:          { macdColor: "#2196f3", signalColor: "#f7c948" },
  Stoch:         { kColor: "#2196f3", dColor: "#f7c948" },
  VolumeProfile: { upColor: "#26a69a88", downColor: "#ef535088", pocColor: "#f59e0b" },
  FVG:           { bullColor: "#26a69a", bearColor: "#ef5350", opacity: "0.15" },
};

function newPane(symbol: string, timeframe = "15min"): PaneConfig {
  return {
    id: Math.random().toString(36).slice(2, 10),
    symbol,
    timeframe,
    dataSource: "auto",
    indicators: [],
  };
}

const DEFAULT_PANES: PaneConfig[] = [
  newPane("NSE:RELIANCE", "15min"),
  newPane("NSE:NIFTY 50", "15min"),
  newPane("CRYPTO:BTC",   "1h"),
  newPane("CRYPTO:ETH",   "1h"),
];

interface DashboardStore {
  paneCount: 1 | 2 | 4 | 6 | 8;
  panes: PaneConfig[];
  focusedPaneId: string | null;
  // actions
  setPaneCount: (n: 1 | 2 | 4 | 6 | 8) => void;
  setPaneSymbol: (paneId: string, symbol: string) => void;
  setPaneTimeframe: (paneId: string, tf: string) => void;
  setFocusedPane: (paneId: string | null) => void;
  addIndicator: (paneId: string, type: IndicatorType) => void;
  updateIndicator: (paneId: string, ind: IndicatorConfig) => void;
  removeIndicator: (paneId: string, indicatorId: string) => void;
}

export function makeDefaultIndicator(type: IndicatorType): IndicatorConfig {
  return {
    id: Math.random().toString(36).slice(2, 10),
    type,
    inputs: { ...DEFAULT_INDICATOR_INPUTS[type] },
    style: { ...DEFAULT_INDICATOR_STYLE[type] },
    visible: true,
  };
}

export const useDashboardStore = create<DashboardStore>()(
  persist(
    (set, get) => ({
      paneCount: 4,
      panes: DEFAULT_PANES,
      focusedPaneId: DEFAULT_PANES[0].id,

      setPaneCount: (n) => set((s) => {
        const cur = s.panes;
        if (n > cur.length) {
          const extras = Array.from({ length: n - cur.length }, (_, i) =>
            newPane(["NSE:RELIANCE", "CRYPTO:BTC", "NSE:INFY", "CRYPTO:ETH",
                     "NSE:TCS", "CRYPTO:SOL", "NSE:HDFC", "CRYPTO:BNB"][cur.length + i] ?? "NSE:RELIANCE")
          );
          return { paneCount: n, panes: [...cur, ...extras] };
        }
        return { paneCount: n, panes: cur.slice(0, n) };
      }),

      setPaneSymbol: (paneId, symbol) => set((s) => ({
        panes: s.panes.map((p) => p.id === paneId ? { ...p, symbol } : p),
      })),

      setPaneTimeframe: (paneId, tf) => set((s) => ({
        panes: s.panes.map((p) => p.id === paneId ? { ...p, timeframe: tf } : p),
      })),

      setFocusedPane: (paneId) => set({ focusedPaneId: paneId }),

      addIndicator: (paneId, type) => set((s) => ({
        panes: s.panes.map((p) =>
          p.id === paneId
            ? { ...p, indicators: [...p.indicators, makeDefaultIndicator(type)] }
            : p
        ),
      })),

      updateIndicator: (paneId, ind) => set((s) => ({
        panes: s.panes.map((p) =>
          p.id === paneId
            ? { ...p, indicators: p.indicators.map((i) => i.id === ind.id ? ind : i) }
            : p
        ),
      })),

      removeIndicator: (paneId, indicatorId) => set((s) => ({
        panes: s.panes.map((p) =>
          p.id === paneId
            ? { ...p, indicators: p.indicators.filter((i) => i.id !== indicatorId) }
            : p
        ),
      })),
    }),
    {
      name: "trading-dashboard",
      // focusedPaneId is transient — don't persist it
      partialize: (s) => ({ paneCount: s.paneCount, panes: s.panes }),
    }
  )
);
```

- [ ] **Step 2: Create frontend/src/store/liveQuotes.ts**

```typescript
/**
 * In-memory live quotes store — NOT persisted.
 * Populated by marketWs.ts on each incoming quote message.
 */
import { create } from "zustand";

export interface LiveQuote {
  symbol: string;
  ltp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ts: string;
  prevLtp: number;    // previous tick — used for flash direction
}

interface LiveQuotesStore {
  quotes: Record<string, LiveQuote>;
  setQuote: (q: Omit<LiveQuote, "prevLtp">) => void;
  brokerStatus: Record<string, string>;
  setBrokerStatus: (status: Record<string, string>) => void;
}

export const useLiveQuotesStore = create<LiveQuotesStore>()((set, get) => ({
  quotes: {},
  brokerStatus: {},

  setQuote: (q) => set((s) => {
    const prev = s.quotes[q.symbol];
    return {
      quotes: {
        ...s.quotes,
        [q.symbol]: { ...q, prevLtp: prev?.ltp ?? q.ltp },
      },
    };
  }),

  setBrokerStatus: (status) => set({ brokerStatus: status }),
}));
```

- [ ] **Step 3: TypeScript compile check**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/frontend
npx tsc --noEmit 2>&1 | head -20
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/store/dashboard.ts frontend/src/store/liveQuotes.ts
git commit -m "feat: add dashboard (persist) + liveQuotes Zustand stores"
```

---

## Task 6: marketWs.ts — WebSocket client singleton

**Files:**
- Create: `frontend/src/lib/marketWs.ts`

- [ ] **Step 1: Create frontend/src/lib/marketWs.ts**

```typescript
/**
 * Singleton WebSocket client for /ws/market.
 *
 * Manages one connection shared across all panes.
 * Reference-counts subscriptions: unsubscribes only when last pane drops a symbol.
 * Call connect() once (e.g. in Dashboard.tsx useEffect).
 */
import { useLiveQuotesStore } from "../store/liveQuotes";

const API_BASE = (import.meta.env.VITE_API_BASE ?? "http://localhost:8000")
  .replace(/^http/, "ws");

let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

// symbol → count of panes currently subscribing
const refCounts: Map<string, number> = new Map();

function send(msg: object) {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  }
}

function handleMessage(evt: MessageEvent) {
  try {
    const msg = JSON.parse(evt.data as string);
    const store = useLiveQuotesStore.getState();
    if (msg.type === "quote") {
      store.setQuote({
        symbol: msg.symbol,
        ltp: msg.ltp,
        open: msg.open,
        high: msg.high,
        low: msg.low,
        close: msg.close,
        volume: msg.volume,
        ts: msg.ts,
      });
    } else if (msg.type === "broker_status") {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { type, ...status } = msg;
      store.setBrokerStatus(status);
    }
  } catch {
    // malformed message — ignore
  }
}

export function connect(token: string) {
  if (ws && ws.readyState !== WebSocket.CLOSED) return;

  ws = new WebSocket(`${API_BASE}/ws/market?token=${encodeURIComponent(token)}`);

  ws.onmessage = handleMessage;

  ws.onopen = () => {
    // Re-subscribe all currently tracked symbols after reconnect
    const symbols = Array.from(refCounts.keys()).filter((s) => (refCounts.get(s) ?? 0) > 0);
    if (symbols.length) send({ action: "subscribe", symbols });
  };

  ws.onclose = () => {
    // Auto-reconnect after 3 s
    reconnectTimer = setTimeout(() => connect(token), 3000);
  };
}

export function disconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  ws?.close();
  ws = null;
  refCounts.clear();
}

export function subscribe(symbols: string[]) {
  const newSymbols: string[] = [];
  for (const sym of symbols) {
    const count = refCounts.get(sym) ?? 0;
    refCounts.set(sym, count + 1);
    if (count === 0) newSymbols.push(sym);
  }
  if (newSymbols.length) send({ action: "subscribe", symbols: newSymbols });
}

export function unsubscribe(symbols: string[]) {
  const dropSymbols: string[] = [];
  for (const sym of symbols) {
    const count = refCounts.get(sym) ?? 0;
    const next = Math.max(0, count - 1);
    refCounts.set(sym, next);
    if (next === 0) dropSymbols.push(sym);
  }
  if (dropSymbols.length) send({ action: "unsubscribe", symbols: dropSymbols });
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/frontend
npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/marketWs.ts
git commit -m "feat: add marketWs singleton WebSocket client with ref-counted subscriptions"
```

---

## Task 7: Extend indicators.ts + types.ts (VolumeProfile + FVG)

**Files:**
- Modify: `frontend/src/components/Chart/types.ts`
- Modify: `frontend/src/components/Chart/indicators.ts`

- [ ] **Step 1: Extend types.ts**

Open `frontend/src/components/Chart/types.ts`. Replace the entire file:

```typescript
export type StudyType =
  | "EMA" | "SMA" | "BB" | "VWAP" | "RSI" | "MACD" | "Stoch"
  | "VolumeProfile" | "FVG";

export type StudyConfig =
  | { id: string; type: "EMA";           period: number; color: string }
  | { id: string; type: "SMA";           period: number; color: string }
  | { id: string; type: "BB";            period: number; std: number; upperColor: string; midColor: string; lowerColor: string }
  | { id: string; type: "VWAP";          color: string }
  | { id: string; type: "RSI";           period: number; color: string }
  | { id: string; type: "MACD";          fast: number; slow: number; signal: number; macdColor: string; signalColor: string }
  | { id: string; type: "Stoch";         k: number; d: number; smooth: number; kColor: string; dColor: string }
  | { id: string; type: "VolumeProfile"; rows: number; valueAreaPct: number; upColor: string; downColor: string; pocColor: string }
  | { id: string; type: "FVG";           minGapPct: number; showLabels: boolean; extendBoxes: boolean; bullColor: string; bearColor: string; opacity: number };

export const OVERLAY_TYPES: StudyType[] = ["EMA", "SMA", "BB", "VWAP", "VolumeProfile", "FVG"];
export const OSCILLATOR_TYPES: StudyType[] = ["RSI", "MACD", "Stoch"];

export const STUDY_DEFAULTS: Record<StudyType, Omit<StudyConfig, "id">> = {
  EMA:           { type: "EMA",           period: 20, color: "#f7c948" },
  SMA:           { type: "SMA",           period: 20, color: "#4caf50" },
  BB:            { type: "BB",            period: 20, std: 2, upperColor: "#2196f3", midColor: "#888888", lowerColor: "#2196f3" },
  VWAP:          { type: "VWAP",          color: "#ff9800" },
  RSI:           { type: "RSI",           period: 14, color: "#ce93d8" },
  MACD:          { type: "MACD",          fast: 12, slow: 26, signal: 9, macdColor: "#2196f3", signalColor: "#f7c948" },
  Stoch:         { type: "Stoch",         k: 14, d: 3, smooth: 3, kColor: "#2196f3", dColor: "#f7c948" },
  VolumeProfile: { type: "VolumeProfile", rows: 24, valueAreaPct: 70, upColor: "#26a69a88", downColor: "#ef535088", pocColor: "#f59e0b" },
  FVG:           { type: "FVG",           minGapPct: 0.1, showLabels: true, extendBoxes: true, bullColor: "#26a69a", bearColor: "#ef5350", opacity: 0.15 },
};

export function studyLabel(s: StudyConfig): string {
  switch (s.type) {
    case "EMA":           return `EMA(${s.period})`;
    case "SMA":           return `SMA(${s.period})`;
    case "BB":            return `BB(${s.period}, ${s.std})`;
    case "VWAP":          return "VWAP";
    case "RSI":           return `RSI(${s.period})`;
    case "MACD":          return `MACD(${s.fast},${s.slow},${s.signal})`;
    case "Stoch":         return `Stoch(${s.k},${s.d})`;
    case "VolumeProfile": return `VP(${s.rows})`;
    case "FVG":           return "FVG";
  }
}
```

- [ ] **Step 2: Add calcVolumeProfile and calcFVG to indicators.ts**

Open `frontend/src/components/Chart/indicators.ts`. Append at the end:

```typescript
// ---------------------------------------------------------------------------
// Volume Profile
// ---------------------------------------------------------------------------

export interface VolumeProfileBucket {
  priceFrom: number;
  priceTo:   number;
  upVol:     number;
  downVol:   number;
  isPoc:     boolean;
}

/**
 * Compute volume profile from OHLCV bars.
 * Returns buckets sorted by price ascending + POC marked.
 */
export function calcVolumeProfile(
  bars: Bar[],
  rows: number,
): VolumeProfileBucket[] {
  if (bars.length === 0) return [];

  const minPrice = Math.min(...bars.map((b) => b.low));
  const maxPrice = Math.max(...bars.map((b) => b.high));
  const step     = (maxPrice - minPrice) / rows;
  if (step === 0) return [];

  const upVols   = new Float64Array(rows);
  const downVols = new Float64Array(rows);

  for (const bar of bars) {
    const idx = Math.min(
      Math.floor((bar.close - minPrice) / step),
      rows - 1,
    );
    if (bar.close >= bar.open) {
      upVols[idx]   += bar.volume;
    } else {
      downVols[idx] += bar.volume;
    }
  }

  let maxTotal = 0;
  let pocIdx   = 0;
  for (let i = 0; i < rows; i++) {
    const total = upVols[i] + downVols[i];
    if (total > maxTotal) { maxTotal = total; pocIdx = i; }
  }

  return Array.from({ length: rows }, (_, i) => ({
    priceFrom: minPrice + i * step,
    priceTo:   minPrice + (i + 1) * step,
    upVol:     upVols[i],
    downVol:   downVols[i],
    isPoc:     i === pocIdx,
  }));
}

// ---------------------------------------------------------------------------
// Fair Value Gap
// ---------------------------------------------------------------------------

export interface FVGZone {
  time:      number;  // unix seconds of the middle candle
  high:      number;  // upper edge of gap
  low:       number;  // lower edge of gap
  direction: "bull" | "bear";
}

/**
 * Detect Fair Value Gaps from OHLCV bars.
 * Bull FVG: bars[i+2].low > bars[i].high  (upward gap)
 * Bear FVG: bars[i+2].high < bars[i].low  (downward gap)
 */
export function calcFVG(bars: Bar[], minGapPct = 0.1): FVGZone[] {
  const zones: FVGZone[] = [];
  for (let i = 0; i < bars.length - 2; i++) {
    const a = bars[i];
    const b = bars[i + 1];
    const c = bars[i + 2];

    // Bull FVG
    if (c.low > a.high) {
      const gapPct = ((c.low - a.high) / a.high) * 100;
      if (gapPct >= minGapPct) {
        zones.push({
          time:      new Date(b.ts.includes("T") ? b.ts + "+05:30" : b.ts).getTime() / 1000,
          high:      c.low,
          low:       a.high,
          direction: "bull",
        });
      }
    }

    // Bear FVG
    if (c.high < a.low) {
      const gapPct = ((a.low - c.high) / a.low) * 100;
      if (gapPct >= minGapPct) {
        zones.push({
          time:      new Date(b.ts.includes("T") ? b.ts + "+05:30" : b.ts).getTime() / 1000,
          high:      a.low,
          low:       c.high,
          direction: "bear",
        });
      }
    }
  }
  return zones;
}
```

- [ ] **Step 3: TypeScript check**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/frontend
npx tsc --noEmit 2>&1 | head -20
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Chart/types.ts frontend/src/components/Chart/indicators.ts
git commit -m "feat: add VolumeProfile + FVG to StudyConfig types and indicator calculations"
```

---

## Task 8: MarketStatusBar component

**Files:**
- Create: `frontend/src/components/Dashboard/MarketStatusBar.tsx`

- [ ] **Step 1: Create MarketStatusBar.tsx**

```tsx
/**
 * MarketStatusBar — India / US / Crypto open/closed strip.
 * Pure frontend: no API calls. Recomputes every 30 seconds.
 */
import { useState, useEffect } from "react";
import { useLiveQuotesStore } from "../../store/liveQuotes";

const TV = {
  bg: "#131722", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86",
  up: "#26a69a", down: "#ef5350", warn: "#f59e0b",
} as const;

// --- time helpers -----------------------------------------------------------

function nowIn(tz: string): Date {
  return new Date(new Date().toLocaleString("en-US", { timeZone: tz }));
}

function fmt2(n: number) { return String(n).padStart(2, "0"); }

function timeStr(d: Date) { return `${fmt2(d.getHours())}:${fmt2(d.getMinutes())}`; }

function dayName(d: Date) {
  return ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][d.getDay()];
}

function minutesUntil(target: { h: number; m: number }, now: Date): number {
  return (target.h * 60 + target.m) - (now.getHours() * 60 + now.getMinutes());
}

function fmtCountdown(minutes: number): string {
  const abs = Math.abs(minutes);
  const h = Math.floor(abs / 60);
  const m = abs % 60;
  return h > 0 ? `${h}h ${fmt2(m)}m` : `${m}m`;
}

// --- market status computation ----------------------------------------------

type MarketStatus = "OPEN" | "PRE" | "AFTER" | "CLOSED" | "WEEKEND";

interface MarketInfo {
  label: string;
  status: MarketStatus;
  statusLabel: string;
  detail: string;
  localTime: string;
  dotColor: string;
}

function indiaStatus(): MarketInfo {
  const d = nowIn("Asia/Kolkata");
  const day = d.getDay(); // 0=Sun 6=Sat
  const mins = d.getHours() * 60 + d.getMinutes();

  const OPEN_M  = 9 * 60 + 15;
  const CLOSE_M = 15 * 60 + 30;
  const PRE_M   = 9 * 60;

  let status: MarketStatus;
  let detail = "";

  if (day === 0 || day === 6) {
    status = "WEEKEND";
    const daysToMon = (8 - day) % 7 || 7;
    detail = `opens ${daysToMon === 1 ? "Mon" : dayName(d)} 09:15`;
  } else if (mins >= PRE_M && mins < OPEN_M) {
    status = "PRE";
    detail = `opens in ${fmtCountdown(OPEN_M - mins)}`;
  } else if (mins >= OPEN_M && mins < CLOSE_M) {
    status = "OPEN";
    detail = `closes in ${fmtCountdown(CLOSE_M - mins)}`;
  } else {
    status = "CLOSED";
    const minsTomorrow = OPEN_M + (day === 5 ? 3 * 24 * 60 : 24 * 60) - mins;
    detail = `opens in ${fmtCountdown(minsTomorrow)}`;
  }

  return {
    label: "🇮🇳 India NSE",
    status,
    statusLabel: status === "WEEKEND" ? "CLOSED" : status,
    detail,
    localTime: `${timeStr(d)} IST`,
    dotColor: status === "OPEN" ? TV.up : status === "PRE" ? TV.warn : TV.muted,
  };
}

function usStatus(): MarketInfo {
  const d = nowIn("America/New_York");
  const day = d.getDay();
  const mins = d.getHours() * 60 + d.getMinutes();

  const PRE_M   = 4 * 60;
  const OPEN_M  = 9 * 60 + 30;
  const CLOSE_M = 16 * 60;
  const AFTER_M = 20 * 60;

  let status: MarketStatus;
  let detail = "";

  if (day === 0 || day === 6) {
    status = "WEEKEND";
    const daysToMon = (8 - day) % 7 || 7;
    detail = `opens ${daysToMon === 1 ? "Mon" : dayName(d)} 09:30`;
  } else if (mins >= PRE_M && mins < OPEN_M) {
    status = "PRE";
    detail = `opens in ${fmtCountdown(OPEN_M - mins)}`;
  } else if (mins >= OPEN_M && mins < CLOSE_M) {
    status = "OPEN";
    detail = `closes in ${fmtCountdown(CLOSE_M - mins)}`;
  } else if (mins >= CLOSE_M && mins < AFTER_M) {
    status = "AFTER";
    detail = "after-hours";
  } else {
    status = "CLOSED";
    const minsTomorrow = OPEN_M + (day === 5 ? 3 * 24 * 60 : 24 * 60) - mins;
    detail = `opens in ${fmtCountdown(minsTomorrow)}`;
  }

  return {
    label: "🇺🇸 US NYSE",
    status,
    statusLabel: status,
    detail,
    localTime: `${timeStr(d)} ET`,
    dotColor: status === "OPEN" ? TV.up : (status === "PRE" || status === "AFTER") ? TV.warn : TV.muted,
  };
}

function cryptoInfo(btcLtp: number | null): MarketInfo {
  const d = nowIn("UTC");
  const btcStr = btcLtp ? btcLtp.toLocaleString("en-US", { maximumFractionDigits: 0 }) : "—";
  return {
    label: "₿ Crypto 24/7",
    status: "OPEN",
    statusLabel: "24/7",
    detail: btcLtp ? `BTC ${btcStr}` : "connecting…",
    localTime: `${timeStr(d)} UTC`,
    dotColor: TV.up,
  };
}

// --- component --------------------------------------------------------------

function StatusCard({ info }: { info: MarketInfo }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "4px 14px", borderRight: `1px solid ${TV.border}`,
      minWidth: 220,
    }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: info.dotColor, flexShrink: 0, display: "inline-block" }} />
      <div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: TV.text }}>{info.label}</span>
          <span style={{
            fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 3,
            background: info.dotColor + "22", color: info.dotColor,
          }}>{info.statusLabel}</span>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 1 }}>
          <span style={{ fontSize: 10, color: TV.muted }}>{info.detail}</span>
          <span style={{ fontSize: 10, color: "#363c4e" }}>{info.localTime}</span>
        </div>
      </div>
    </div>
  );
}

export default function MarketStatusBar() {
  const btcQuote = useLiveQuotesStore((s) => s.quotes["CRYPTO:BTC"]);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  void tick; // triggers recompute on interval

  const markets = [
    indiaStatus(),
    usStatus(),
    cryptoInfo(btcQuote?.ltp ?? null),
  ];

  return (
    <div style={{
      display: "flex", background: TV.bg,
      borderBottom: `1px solid ${TV.border}`,
      overflowX: "auto", flexShrink: 0,
    }}>
      {markets.map((m) => <StatusCard key={m.label} info={m} />)}
    </div>
  );
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/frontend
npx tsc --noEmit 2>&1 | head -10
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Dashboard/MarketStatusBar.tsx
git commit -m "feat: add MarketStatusBar (India/US/Crypto open-closed strip)"
```

---

## Task 9: TickerBar + PaneControls

**Files:**
- Create: `frontend/src/components/Dashboard/TickerBar.tsx`
- Create: `frontend/src/components/Dashboard/PaneControls.tsx`

- [ ] **Step 1: Create TickerBar.tsx**

```tsx
/**
 * TickerBar — live LTP with green/red flash on tick direction.
 * Shows: Symbol · TF · LTP · Change% · O · H · L · C · Vol
 */
import { useEffect, useRef, useState } from "react";
import { useLiveQuotesStore } from "../../store/liveQuotes";

const TV = {
  bg: "#1a1e2e", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86",
  up: "#26a69a", down: "#ef5350",
} as const;

function fmtVol(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000)     return `${(v / 1_000).toFixed(1)}K`;
  return String(Math.round(v));
}

interface Props {
  symbol: string;
  timeframe: string;
  onOpenIndicators?: () => void;
}

export default function TickerBar({ symbol, timeframe, onOpenIndicators }: Props) {
  const quote = useLiveQuotesStore((s) => s.quotes[symbol]);
  const [flash, setFlash] = useState<"up" | "down" | null>(null);
  const prevLtpRef = useRef<number | null>(null);

  useEffect(() => {
    if (!quote) return;
    const prev = prevLtpRef.current;
    if (prev !== null && quote.ltp !== prev) {
      setFlash(quote.ltp > prev ? "up" : "down");
      const t = setTimeout(() => setFlash(null), 600);
      return () => clearTimeout(t);
    }
    prevLtpRef.current = quote.ltp;
  }, [quote?.ltp]);

  const ltp     = quote?.ltp ?? null;
  const open    = quote?.open ?? null;
  const change  = ltp != null && open != null && open !== 0
    ? ((ltp - open) / open) * 100 : null;
  const isUp    = change != null && change >= 0;
  const priceColor = ltp == null ? TV.muted : isUp ? TV.up : TV.down;

  const flashBg = flash === "up"
    ? "#26a69a33"
    : flash === "down" ? "#ef535033" : "transparent";

  return (
    <div style={{
      background: flashBg, transition: "background 0.3s",
      borderBottom: `1px solid ${TV.border}`,
      padding: "3px 8px", display: "flex", gap: 8, alignItems: "center",
      fontSize: 11, flexWrap: "nowrap", overflow: "hidden",
    }}>
      <span style={{ fontWeight: 700, color: TV.text, fontFamily: "monospace", flexShrink: 0 }}>
        {symbol.split(":")[1] ?? symbol}
      </span>
      <span style={{ color: TV.muted, fontSize: 10 }}>{timeframe}</span>
      <span style={{ fontFamily: "monospace", fontWeight: 700, color: priceColor, flexShrink: 0 }}>
        {ltp != null ? ltp.toFixed(2) : "—"}
      </span>
      {change != null && (
        <span style={{
          fontSize: 10, padding: "1px 4px", borderRadius: 3,
          background: isUp ? "#26a69a22" : "#ef535022",
          color: isUp ? TV.up : TV.down, flexShrink: 0,
        }}>
          {isUp ? "+" : ""}{change.toFixed(2)}%
        </span>
      )}
      {quote && (
        <span style={{ color: TV.muted, fontSize: 10, display: "flex", gap: 5 }}>
          <span>O <b style={{ color: TV.text }}>{quote.open.toFixed(2)}</b></span>
          <span>H <b style={{ color: TV.up   }}>{quote.high.toFixed(2)}</b></span>
          <span>L <b style={{ color: TV.down }}>{quote.low.toFixed(2)}</b></span>
          <span>C <b style={{ color: TV.text }}>{quote.close.toFixed(2)}</b></span>
          <span>V <b style={{ color: TV.muted }}>{fmtVol(quote.volume)}</b></span>
        </span>
      )}
      <div style={{ flex: 1 }} />
      {onOpenIndicators && (
        <button
          onClick={onOpenIndicators}
          style={{
            background: "transparent", border: `1px solid ${TV.border}`,
            borderRadius: 3, color: TV.muted, fontSize: 10, padding: "1px 6px",
            cursor: "pointer", flexShrink: 0,
          }}
        >
          ⊕ Indicators
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create PaneControls.tsx**

```tsx
/**
 * PaneControls — symbol search dropdown + timeframe dropdown for a single pane.
 */
import { useState, useRef, useEffect } from "react";
import { apiClient } from "../../api/client";
import { useDashboardStore } from "../../store/dashboard";

const TV = {
  bg: "#131722", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86", accent: "#2962ff",
} as const;

const TF_OPTIONS = [
  { label: "1m",  value: "1min"  },
  { label: "5m",  value: "5min"  },
  { label: "15m", value: "15min" },
  { label: "30m", value: "30min" },
  { label: "1h",  value: "1h"    },
  { label: "4h",  value: "4h"    },
  { label: "1d",  value: "1d"    },
  { label: "1w",  value: "1w"    },
];

// Top Hyperliquid perpetuals (prefixed)
const CRYPTO_SYMBOLS = [
  "CRYPTO:BTC", "CRYPTO:ETH", "CRYPTO:SOL", "CRYPTO:BNB",
  "CRYPTO:DOGE", "CRYPTO:XRP", "CRYPTO:AVAX", "CRYPTO:MATIC",
  "CRYPTO:ARB", "CRYPTO:OP", "CRYPTO:SUI", "CRYPTO:APT",
];

interface Props {
  paneId: string;
  symbol: string;
  timeframe: string;
}

export default function PaneControls({ paneId, symbol, timeframe }: Props) {
  const { setPaneSymbol, setPaneTimeframe } = useDashboardStore();
  const [query, setQuery]     = useState("");
  const [results, setResults] = useState<string[]>([]);
  const [open, setOpen]       = useState(false);
  const debounceRef           = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapRef               = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Fetch NSE symbols + filter crypto on keystroke
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const q = query.trim().toUpperCase();
    if (q.length < 2) { setResults([]); setOpen(false); return; }

    const ctrl = new AbortController();
    debounceRef.current = setTimeout(async () => {
      try {
        const { data } = await apiClient.get("/technical/symbols", {
          params: { q, limit: 15 },
          signal: ctrl.signal,
        });
        const nse: string[] = (data.symbols ?? []).map((s: string) => `NSE:${s}`);
        const crypto = CRYPTO_SYMBOLS.filter((s) => s.toUpperCase().includes(q));
        setResults([...crypto, ...nse].slice(0, 20));
        setOpen(true);
      } catch { /* aborted or error */ }
    }, 200);

    return () => { ctrl.abort(); if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query]);

  const pick = (sym: string) => {
    setPaneSymbol(paneId, sym);
    setQuery("");
    setOpen(false);
  };

  const inputStyle: React.CSSProperties = {
    background: TV.bg, border: `1px solid ${TV.border}`, borderRadius: 3,
    color: TV.text, padding: "2px 7px", fontSize: 11, outline: "none",
    width: 130,
  };

  const selectStyle: React.CSSProperties = {
    background: TV.bg, border: `1px solid ${TV.border}`, borderRadius: 3,
    color: TV.text, padding: "2px 5px", fontSize: 11, cursor: "pointer",
  };

  return (
    <div style={{ display: "flex", gap: 5, alignItems: "center" }} ref={wrapRef}>
      {/* Current symbol label */}
      <span style={{ fontSize: 11, fontWeight: 700, color: TV.text, fontFamily: "monospace" }}>
        {symbol.split(":")[1] ?? symbol}
      </span>

      {/* Symbol search */}
      <div style={{ position: "relative" }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && results[0]) pick(results[0]); if (e.key === "Escape") { setOpen(false); setQuery(""); } }}
          placeholder="Change…"
          style={inputStyle}
          autoComplete="off"
          spellCheck={false}
        />
        {open && results.length > 0 && (
          <div style={{
            position: "absolute", top: "calc(100% + 2px)", left: 0, zIndex: 9999,
            background: "#1e222d", border: `1px solid ${TV.border}`, borderRadius: 4,
            minWidth: 180, maxHeight: 240, overflowY: "auto",
            boxShadow: "0 8px 24px rgba(0,0,0,0.6)",
          }}>
            {results.map((s) => (
              <div
                key={s}
                onMouseDown={() => pick(s)}
                style={{
                  padding: "5px 10px", cursor: "pointer", fontSize: 11,
                  fontFamily: "monospace", color: TV.text,
                  borderBottom: `1px solid ${TV.border}22`,
                }}
              >
                <span style={{ color: TV.muted, fontSize: 9 }}>{s.split(":")[0]}</span>
                {" "}{s.split(":")[1]}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Timeframe dropdown */}
      <select
        value={timeframe}
        onChange={(e) => setPaneTimeframe(paneId, e.target.value)}
        style={selectStyle}
      >
        {TF_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}
```

- [ ] **Step 3: TypeScript check**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/frontend
npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Dashboard/TickerBar.tsx frontend/src/components/Dashboard/PaneControls.tsx
git commit -m "feat: add TickerBar (flash animation) + PaneControls (symbol+TF dropdowns)"
```

---

## Task 10: IndicatorPanel — two-layer (list + settings)

**Files:**
- Create: `frontend/src/components/Dashboard/IndicatorPanel.tsx`

- [ ] **Step 1: Create IndicatorPanel.tsx**

```tsx
/**
 * IndicatorPanel — two-layer slide-in panel.
 *
 * Layer 1: searchable list grouped by Overlays / Oscillators
 * Layer 2: per-indicator settings (Inputs / Style / Visibility tabs)
 *
 * Renders as position:absolute overlay on the right side of the pane.
 */
import { useState } from "react";
import { useDashboardStore, IndicatorConfig, IndicatorType, makeDefaultIndicator } from "../../store/dashboard";
import { STUDY_DEFAULTS, studyLabel } from "../Chart/types";

const TV = {
  bg: "#1e222d", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86",
  accent: "#2962ff", up: "#26a69a", down: "#ef5350",
} as const;

const OVERLAY_TYPES: IndicatorType[]    = ["EMA", "SMA", "BB", "VWAP", "VolumeProfile", "FVG"];
const OSCILLATOR_TYPES: IndicatorType[] = ["RSI", "MACD", "Stoch"];

const INDICATOR_LABELS: Record<IndicatorType, string> = {
  EMA: "EMA", SMA: "SMA", BB: "Bollinger Bands", VWAP: "VWAP",
  RSI: "RSI", MACD: "MACD", Stoch: "Stochastic",
  VolumeProfile: "Volume Profile", FVG: "Fair Value Gap",
};

const INDICATOR_DESCRIPTIONS: Record<IndicatorType, string> = {
  EMA: "Exponential Moving Average", SMA: "Simple Moving Average",
  BB: "Bollinger Bands (20, 2σ)", VWAP: "Volume Weighted Avg Price",
  RSI: "Relative Strength Index", MACD: "MACD (12, 26, 9)",
  Stoch: "Stochastic Oscillator", VolumeProfile: "Price×Volume histogram",
  FVG: "Fair Value Gap zones",
};

interface Props {
  paneId: string;
  indicators: IndicatorConfig[];
  onClose: () => void;
}

// --- Layer 2: settings for one indicator ------------------------------------

function SettingsLayer({
  paneId, indicator, onBack,
}: { paneId: string; indicator: IndicatorConfig; onBack: () => void }) {
  const { updateIndicator } = useDashboardStore();
  const [draft, setDraft] = useState<IndicatorConfig>({ ...indicator, inputs: { ...indicator.inputs }, style: { ...indicator.style } });
  const [tab, setTab] = useState<"inputs" | "style" | "visibility">("inputs");

  const setInput  = (k: string, v: number | string | boolean) =>
    setDraft((d) => ({ ...d, inputs: { ...d.inputs, [k]: v } }));
  const setStyle  = (k: string, v: string) =>
    setDraft((d) => ({ ...d, style: { ...d.style, [k]: v } }));

  const apply = () => { updateIndicator(paneId, draft); onBack(); };

  const inputField = (key: string, val: number | string | boolean) => {
    if (typeof val === "boolean") {
      return (
        <div key={key} style={{ marginBottom: 8 }}>
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 11, color: TV.text }}>
            <input type="checkbox" checked={val} onChange={(e) => setInput(key, e.target.checked)} />
            {key}
          </label>
        </div>
      );
    }
    return (
      <div key={key} style={{ marginBottom: 8 }}>
        <div style={{ fontSize: 10, color: TV.muted, marginBottom: 2 }}>{key}</div>
        <input
          type={typeof val === "number" ? "number" : "text"}
          value={String(val)}
          step={typeof val === "number" && val < 10 ? 0.1 : 1}
          onChange={(e) => setInput(key, typeof val === "number" ? Number(e.target.value) : e.target.value)}
          style={{ background: "#131722", border: `1px solid ${TV.border}`, borderRadius: 3, padding: "2px 6px", color: TV.text, fontSize: 11, width: "100%", boxSizing: "border-box" }}
        />
      </div>
    );
  };

  const colorField = (key: string, val: string) => (
    <div key={key} style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 10, color: TV.muted, marginBottom: 2 }}>{key}</div>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <input type="color" value={val.slice(0, 7)} onChange={(e) => setStyle(key, e.target.value)}
          style={{ width: 28, height: 22, border: "none", background: "none", cursor: "pointer", padding: 0 }} />
        <input value={val} onChange={(e) => setStyle(key, e.target.value)}
          style={{ flex: 1, background: "#131722", border: `1px solid ${TV.border}`, borderRadius: 3, padding: "2px 6px", color: TV.text, fontSize: 10 }} />
      </div>
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
      <div style={{ padding: "6px 10px", borderBottom: `1px solid ${TV.border}`, display: "flex", gap: 8, alignItems: "center" }}>
        <button onClick={onBack} style={{ background: "none", border: "none", color: TV.accent, cursor: "pointer", fontSize: 11, padding: 0 }}>← Back</button>
        <span style={{ fontSize: 11, fontWeight: 700, color: TV.text, flex: 1 }}>{INDICATOR_LABELS[indicator.type]}</span>
      </div>
      <div style={{ display: "flex", borderBottom: `1px solid ${TV.border}` }}>
        {(["inputs", "style", "visibility"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} style={{
            flex: 1, padding: "5px 0", background: "none", border: "none",
            fontSize: 10, cursor: "pointer", textTransform: "capitalize",
            color: tab === t ? TV.accent : TV.muted,
            borderBottom: tab === t ? `2px solid ${TV.accent}` : "2px solid transparent",
          }}>{t}</button>
        ))}
      </div>
      <div style={{ flex: 1, overflow: "auto", padding: 10 }}>
        {tab === "inputs" && Object.entries(draft.inputs).map(([k, v]) => inputField(k, v))}
        {tab === "style"  && Object.entries(draft.style).map(([k, v]) => colorField(k, v))}
        {tab === "visibility" && (
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 11, color: TV.text }}>
            <input type="checkbox" checked={draft.visible} onChange={(e) => setDraft((d) => ({ ...d, visible: e.target.checked }))} />
            Visible on chart
          </label>
        )}
      </div>
      <div style={{ padding: "6px 10px", borderTop: `1px solid ${TV.border}`, display: "flex", gap: 6, justifyContent: "flex-end" }}>
        <button onClick={onBack} style={{ background: "none", border: `1px solid ${TV.border}`, borderRadius: 3, color: TV.muted, fontSize: 10, padding: "3px 10px", cursor: "pointer" }}>Cancel</button>
        <button onClick={apply} style={{ background: TV.accent, border: "none", borderRadius: 3, color: "#fff", fontSize: 10, padding: "3px 10px", cursor: "pointer" }}>Apply</button>
      </div>
    </div>
  );
}

// --- Layer 1: indicator list ------------------------------------------------

export default function IndicatorPanel({ paneId, indicators, onClose }: Props) {
  const { addIndicator, removeIndicator } = useDashboardStore();
  const [search, setSearch]               = useState("");
  const [editing, setEditing]             = useState<IndicatorConfig | null>(null);

  const activeIds = new Set(indicators.map((i) => i.type));

  const filtered = (types: IndicatorType[]) =>
    types.filter((t) =>
      !search || INDICATOR_LABELS[t].toLowerCase().includes(search.toLowerCase())
    );

  const Section = ({ title, types }: { title: string; types: IndicatorType[] }) => {
    const items = filtered(types);
    if (!items.length) return null;
    return (
      <>
        <div style={{ padding: "4px 10px 2px", fontSize: 9, color: TV.accent, textTransform: "uppercase", letterSpacing: 0.5 }}>{title}</div>
        {items.map((type) => {
          const active = activeIds.has(type);
          const ind = indicators.find((i) => i.type === type);
          return (
            <div key={type} style={{
              padding: "5px 10px", display: "flex", alignItems: "center", gap: 6,
              borderRadius: 3, margin: "1px 4px",
              background: active ? `${TV.accent}11` : "transparent",
            }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 11, color: TV.text }}>{INDICATOR_LABELS[type]}</div>
                <div style={{ fontSize: 9, color: TV.muted }}>{INDICATOR_DESCRIPTIONS[type]}</div>
              </div>
              {active && ind ? (
                <>
                  <button onClick={() => setEditing(ind)}
                    style={{ background: "none", border: `1px solid ${TV.border}`, borderRadius: 3, color: TV.muted, fontSize: 10, padding: "1px 5px", cursor: "pointer" }}>⚙</button>
                  <button onClick={() => removeIndicator(paneId, ind.id)}
                    style={{ background: "none", border: `1px solid ${TV.border}`, borderRadius: 3, color: TV.down, fontSize: 10, padding: "1px 5px", cursor: "pointer" }}>✕</button>
                </>
              ) : (
                <button onClick={() => addIndicator(paneId, type)}
                  style={{ background: `${TV.accent}22`, border: `1px solid ${TV.accent}44`, borderRadius: 3, color: TV.accent, fontSize: 10, padding: "1px 8px", cursor: "pointer" }}>+</button>
              )}
            </div>
          );
        })}
      </>
    );
  };

  return (
    <div style={{
      position: "absolute", top: 0, right: 0, bottom: 0,
      width: 240, background: TV.bg, borderLeft: `1px solid ${TV.border}`,
      display: "flex", flexDirection: "column", zIndex: 100,
      boxShadow: "-4px 0 16px rgba(0,0,0,0.4)",
    }}>
      <div style={{ padding: "6px 10px", borderBottom: `1px solid ${TV.border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: TV.text }}>Indicators</span>
        <button onClick={onClose} style={{ background: "none", border: "none", color: TV.muted, cursor: "pointer", fontSize: 14 }}>✕</button>
      </div>

      {editing ? (
        <SettingsLayer paneId={paneId} indicator={editing} onBack={() => setEditing(null)} />
      ) : (
        <>
          <div style={{ padding: "6px 8px" }}>
            <input
              placeholder="🔍 Search indicators..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ width: "100%", boxSizing: "border-box", background: "#131722", border: `1px solid ${TV.border}`, borderRadius: 3, padding: "3px 8px", color: TV.text, fontSize: 11, outline: "none" }}
            />
          </div>
          <div style={{ flex: 1, overflowY: "auto" }}>
            <Section title="Overlays"    types={OVERLAY_TYPES} />
            <Section title="Oscillators" types={OSCILLATOR_TYPES} />
          </div>

          {/* Active indicators strip */}
          {indicators.length > 0 && (
            <div style={{ borderTop: `1px solid ${TV.border}`, padding: "6px 8px" }}>
              <div style={{ fontSize: 9, color: TV.muted, marginBottom: 4, textTransform: "uppercase" }}>Active</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {indicators.map((ind) => (
                  <div key={ind.id} style={{
                    display: "flex", alignItems: "center", gap: 3,
                    background: "#131722", border: `1px solid ${TV.border}`,
                    borderRadius: 3, padding: "1px 5px",
                  }}>
                    <span style={{ fontSize: 9, color: TV.text }}>{INDICATOR_LABELS[ind.type]}</span>
                    <button onClick={() => setEditing(ind)}
                      style={{ background: "none", border: "none", color: TV.muted, cursor: "pointer", fontSize: 9, padding: 0 }}>⚙</button>
                    <button onClick={() => removeIndicator(paneId, ind.id)}
                      style={{ background: "none", border: "none", color: TV.muted, cursor: "pointer", fontSize: 9, padding: 0 }}>✕</button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/frontend
npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Dashboard/IndicatorPanel.tsx
git commit -m "feat: add IndicatorPanel two-layer (list + settings with Inputs/Style/Visibility tabs)"
```

---

## Task 11: ChartPane + PaneGrid + Dashboard page + routing

**Files:**
- Create: `frontend/src/components/Dashboard/ChartPane.tsx`
- Create: `frontend/src/components/Dashboard/PaneGrid.tsx`
- Create: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout/Sidebar.tsx`

- [ ] **Step 1: Create ChartPane.tsx**

```tsx
/**
 * ChartPane — a single chart pane in the dashboard grid.
 * Composes: PaneControls + TickerBar + CandlestickChart + IndicatorPanel
 */
import { useState, useCallback, useRef, useEffect } from "react";
import { useDashboardStore } from "../../store/dashboard";
import { apiClient } from "../../api/client";
import CandlestickChart from "../Chart/CandlestickChart";
import type { ChartHandle } from "../Chart/CandlestickChart";
import type { Bar } from "../Chart/indicators";
import type { StudyConfig } from "../Chart/types";
import { STUDY_DEFAULTS } from "../Chart/types";
import TickerBar from "./TickerBar";
import PaneControls from "./PaneControls";
import IndicatorPanel from "./IndicatorPanel";
import * as marketWs from "../../lib/marketWs";

const TV = { bg: "#131722", border: "#2a2e39", accent: "#2962ff" } as const;

// Map dashboard IndicatorConfig → StudyConfig for CandlestickChart
function toStudyConfig(ind: import("../../store/dashboard").IndicatorConfig): StudyConfig | null {
  const base = { id: ind.id, ...STUDY_DEFAULTS[ind.type as keyof typeof STUDY_DEFAULTS] };
  if (!base) return null;
  // Merge user inputs + style into the defaults
  const merged = { ...base };
  for (const [k, v] of Object.entries(ind.inputs))  (merged as Record<string, unknown>)[k] = v;
  for (const [k, v] of Object.entries(ind.style))   (merged as Record<string, unknown>)[k] = v;
  if (!ind.visible) return null;
  return merged as StudyConfig;
}

// Date helpers for OHLCV fetch
const TF_DAYS: Record<string, number> = {
  "1min": 3, "5min": 7, "15min": 14, "30min": 21,
  "1h": 60, "4h": 120, "1d": 365, "1w": 730,
};

function toISO(d: Date, end = false) {
  const s = d.toISOString().split("T")[0];
  return end ? s + "T23:59:59" : s + "T00:00:00";
}

interface Props {
  paneId: string;
  focused: boolean;
  onFocus: () => void;
}

export default function ChartPane({ paneId, focused, onFocus }: Props) {
  const pane            = useDashboardStore((s) => s.panes.find((p) => p.id === paneId));
  const [bars, setBars] = useState<Bar[]>([]);
  const [loading, setLoading] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const chartRef  = useRef<ChartHandle | null>(null);
  const oldestRef = useRef<Date | null>(null);
  const loadingMoreRef = useRef(false);

  const symbol    = pane?.symbol    ?? "NSE:RELIANCE";
  const timeframe = pane?.timeframe ?? "15min";
  const isNse     = symbol.startsWith("NSE:") || symbol.startsWith("BSE:");
  const indicators = pane?.indicators ?? [];

  // Subscribe to live feed
  useEffect(() => {
    marketWs.subscribe([symbol]);
    return () => { marketWs.unsubscribe([symbol]); };
  }, [symbol]);

  // Load historical bars
  const loadBars = useCallback(async (sym: string, tf: string, fromDt: Date, toDt: Date) => {
    if (isNse) {
      const { data } = await apiClient.get(`/technical/ohlcv/${sym.split(":")[1]}`, {
        params: { tf, from_dt: toISO(fromDt), to_dt: toISO(toDt, true) },
      });
      return data.rows as Bar[];
    } else {
      const { data } = await apiClient.get("/market/ohlcv", {
        params: { symbol: sym, tf, from_dt: toISO(fromDt), to_dt: toISO(toDt, true) },
      });
      return data.rows as Bar[];
    }
  }, [isNse]);

  const loadInitial = useCallback(async () => {
    setLoading(true);
    setBars([]);
    oldestRef.current = null;
    const now    = new Date();
    const days   = TF_DAYS[timeframe] ?? 30;
    const fromDt = new Date(now.getTime() - days * 86400_000);
    try {
      const rows = await loadBars(symbol, timeframe, fromDt, now);
      setBars(rows);
      oldestRef.current = fromDt;
    } catch { /* show empty */ }
    finally  { setLoading(false); }
  }, [symbol, timeframe, loadBars]);

  useEffect(() => { loadInitial(); }, [loadInitial]);

  const handleNeedMoreData = useCallback(async () => {
    if (loadingMoreRef.current || !oldestRef.current) return;
    loadingMoreRef.current = true;
    const toDt   = new Date(oldestRef.current.getTime() - 1000);
    const days   = TF_DAYS[timeframe] ?? 30;
    const fromDt = new Date(toDt.getTime() - days * 86400_000);
    try {
      const older = await loadBars(symbol, timeframe, fromDt, toDt);
      if (older.length) { setBars((p) => [...older, ...p]); oldestRef.current = fromDt; }
    } finally { loadingMoreRef.current = false; }
  }, [symbol, timeframe, loadBars]);

  const studies = indicators
    .map(toStudyConfig)
    .filter((s): s is StudyConfig => s !== null);

  return (
    <div
      onClick={onFocus}
      style={{
        display: "flex", flexDirection: "column", height: "100%",
        background: TV.bg,
        outline: focused ? `2px solid ${TV.accent}` : `1px solid ${TV.border}`,
        position: "relative",
      }}
    >
      {/* Header: controls */}
      <div style={{ padding: "3px 8px", background: "#1a1e2e", borderBottom: `1px solid ${TV.border}`, display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
        <PaneControls paneId={paneId} symbol={symbol} timeframe={timeframe} />
      </div>

      {/* Ticker bar */}
      <TickerBar
        symbol={symbol}
        timeframe={timeframe}
        onOpenIndicators={() => { onFocus(); setPanelOpen((v) => !v); }}
      />

      {/* Chart area */}
      <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
        {loading && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "#787b86", fontSize: 12 }}>
            Loading…
          </div>
        )}
        {!loading && bars.length > 0 && (
          <CandlestickChart
            ref={chartRef}
            bars={bars}
            studies={studies}
            onNeedMoreData={handleNeedMoreData}
          />
        )}
        {!loading && bars.length === 0 && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "#787b86", fontSize: 12 }}>
            No data · {symbol}
          </div>
        )}

        {/* Indicator panel slides in */}
        {panelOpen && pane && (
          <IndicatorPanel
            paneId={paneId}
            indicators={pane.indicators}
            onClose={() => setPanelOpen(false)}
          />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create PaneGrid.tsx**

```tsx
/**
 * PaneGrid — CSS grid layout for 1/2/4/6/8 chart panes.
 */
import ChartPane from "./ChartPane";
import { useDashboardStore } from "../../store/dashboard";

const GRID_STYLES: Record<number, React.CSSProperties> = {
  1: { gridTemplateColumns: "1fr",                   gridTemplateRows: "1fr"      },
  2: { gridTemplateColumns: "1fr 1fr",               gridTemplateRows: "1fr"      },
  4: { gridTemplateColumns: "1fr 1fr",               gridTemplateRows: "1fr 1fr"  },
  6: { gridTemplateColumns: "1fr 1fr 1fr",           gridTemplateRows: "1fr 1fr"  },
  8: { gridTemplateColumns: "1fr 1fr 1fr 1fr",       gridTemplateRows: "1fr 1fr"  },
};

export default function PaneGrid() {
  const { paneCount, panes, focusedPaneId, setFocusedPane } = useDashboardStore();
  const gridStyle = GRID_STYLES[paneCount] ?? GRID_STYLES[4];
  const visiblePanes = panes.slice(0, paneCount);

  return (
    <div style={{ flex: 1, display: "grid", ...gridStyle, gap: 2, overflow: "hidden" }}>
      {visiblePanes.map((pane) => (
        <ChartPane
          key={pane.id}
          paneId={pane.id}
          focused={focusedPaneId === pane.id}
          onFocus={() => setFocusedPane(pane.id)}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Create Dashboard.tsx**

```tsx
/**
 * Dashboard page — multi-pane chart grid.
 * Replaces the old /chart/:symbol single-chart page.
 */
import { useEffect } from "react";
import { useDashboardStore } from "../store/dashboard";
import { useLiveQuotesStore } from "../store/liveQuotes";
import MarketStatusBar from "../components/Dashboard/MarketStatusBar";
import PaneGrid from "../components/Dashboard/PaneGrid";
import * as marketWs from "../lib/marketWs";

const TV = { bg: "#0d0d1a", border: "#2a2e39", text: "#d1d4dc", muted: "#787b86", accent: "#2962ff" } as const;

const PANE_COUNTS = [1, 2, 4, 6, 8] as const;

function TopBar() {
  const { paneCount, setPaneCount } = useDashboardStore();
  const brokerStatus = useLiveQuotesStore((s) => s.brokerStatus);
  const upstoxConnected = brokerStatus["upstox"] === "connected";

  const handleConnectUpstox = () => {
    window.open("http://localhost:8000/auth/upstox/login", "_blank", "width=600,height=700");
  };

  return (
    <div style={{
      background: "#131722", borderBottom: `1px solid ${TV.border}`,
      padding: "6px 14px", display: "flex", gap: 10, alignItems: "center", flexShrink: 0,
    }}>
      <span style={{ fontSize: 13, fontWeight: 700, color: TV.accent }}>📊 Dashboard</span>

      {/* Pane count selector */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: 10 }}>
        <span style={{ fontSize: 11, color: TV.muted }}>Panes:</span>
        <select
          value={paneCount}
          onChange={(e) => setPaneCount(Number(e.target.value) as typeof paneCount)}
          style={{
            background: "#1e222d", border: `1px solid ${TV.border}`, borderRadius: 4,
            color: TV.text, padding: "3px 8px", fontSize: 12, cursor: "pointer",
          }}
        >
          {PANE_COUNTS.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </div>

      <div style={{ flex: 1 }} />

      {/* Broker connection status */}
      <button
        onClick={handleConnectUpstox}
        style={{
          background: upstoxConnected ? "#26a69a22" : "#1e222d",
          border: `1px solid ${upstoxConnected ? "#26a69a44" : TV.border}`,
          borderRadius: 4, color: upstoxConnected ? "#26a69a" : TV.muted,
          padding: "4px 12px", cursor: "pointer", fontSize: 11, fontWeight: 600,
        }}
      >
        {upstoxConnected ? "● Upstox" : "Connect Upstox"}
      </button>

      <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#26a69a", display: "inline-block" }} />
        <span style={{ fontSize: 10, color: TV.muted }}>Hyperliquid</span>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const token = localStorage.getItem("access_token") ?? "";

  useEffect(() => {
    marketWs.connect(token);
    return () => { /* keep WS alive while mounted */ };
  }, [token]);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: TV.bg, overflow: "hidden" }}>
      <TopBar />
      <MarketStatusBar />
      <PaneGrid />
    </div>
  );
}
```

- [ ] **Step 4: Update App.tsx**

Open `frontend/src/App.tsx`. Replace:
```tsx
import Chart from "./pages/Chart";
```
with:
```tsx
import Dashboard from "./pages/Dashboard";
```

Replace the chart route:
```tsx
          <Route path="/chart/:symbol" element={
            <ProtectedRoute><AppLayout><Chart /></AppLayout></ProtectedRoute>
          } />
```
with:
```tsx
          <Route path="/chart" element={
            <ProtectedRoute><AppLayout><Dashboard /></AppLayout></ProtectedRoute>
          } />
          <Route path="/chart/:symbol" element={<Navigate to="/chart" replace />} />
```

- [ ] **Step 5: Update Sidebar.tsx**

Open `frontend/src/components/Layout/Sidebar.tsx`. Change:
```tsx
  { path: "/chart/RELIANCE", icon: "📈", label: "Charts" },
```
to:
```tsx
  { path: "/chart", icon: "📊", label: "Dashboard" },
```

- [ ] **Step 6: TypeScript check**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/frontend
npx tsc --noEmit 2>&1
```
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Dashboard/ChartPane.tsx \
        frontend/src/components/Dashboard/PaneGrid.tsx \
        frontend/src/pages/Dashboard.tsx \
        frontend/src/App.tsx \
        frontend/src/components/Layout/Sidebar.tsx
git commit -m "feat: add ChartPane + PaneGrid + Dashboard page, replace /chart/:symbol route"
```

---

## Task 12: Update session handoff + final verification

**Files:**
- Modify: `docs/SESSION_HANDOFF.md`

- [ ] **Step 1: Restart backend and verify routes**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/backend
PYTHONPATH=. .venv/bin/uvicorn api.main:app --reload --port 8000 &
sleep 3
curl -s http://localhost:8000/health
curl -s http://localhost:8000/openapi.json | python3 -c "import sys,json; paths=json.load(sys.stdin)['paths']; print([p for p in paths if 'market' in p or 'upstox' in p])"
```

Expected: routes `/ws/market`, `/market/ohlcv`, `/auth/upstox/login`, `/auth/upstox/callback`, `/auth/upstox/status` all present.

- [ ] **Step 2: Start frontend and verify dashboard loads**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/frontend
npm run dev &
sleep 4
curl -s -o /dev/null -w "%{http_code}" http://localhost:5173
```
Expected: `200`.

- [ ] **Step 3: Run all backend unit tests**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
backend/.venv/bin/python -m pytest backend/tests/unit/ -q --tb=short
```
Expected: all pass (≥96 tests, 4 new for broker_base + hyperliquid).

- [ ] **Step 4: Commit handoff**

```bash
git add docs/SESSION_HANDOFF.md
git commit -m "docs: update session handoff — multi-chart dashboard complete"
```

---

## Self-Review Checklist

| Requirement | Task |
|---|---|
| 1/2/4/6/8 pane grid | Task 11 — PaneGrid.tsx |
| Grid choice persisted | Task 5 — dashboard store `paneCount` |
| Per-pane symbol + TF picker | Task 9 — PaneControls.tsx |
| Per-pane state persisted | Task 5 — Zustand persist |
| Upstox WS v3 + protobuf | Task 2 — UpstoxAdapter |
| Hyperliquid WS allMids | Task 3 — HyperliquidAdapter |
| Unified /ws/market | Task 4 — MarketFeedManager |
| Pluggable broker adapter | Task 1 — BrokerAdapter Protocol |
| Ticker bar + flash | Task 9 — TickerBar.tsx |
| Two-layer indicator panel | Task 10 — IndicatorPanel.tsx |
| Volume Profile calc | Task 7 — calcVolumeProfile() |
| FVG calc | Task 7 — calcFVG() |
| VolumeProfile + FVG in StudyConfig | Task 7 — types.ts extended |
| Market status bar | Task 8 — MarketStatusBar.tsx |
| Upstox OAuth flow | Task 4 — /auth/upstox/login + callback |
| Crypto OHLCV via yfinance | Task 4 — /market/ohlcv |
| /chart route change | Task 11 — App.tsx |
| Old /chart/:symbol redirect | Task 11 — App.tsx Navigate |
| Sidebar nav update | Task 11 — Sidebar.tsx |
