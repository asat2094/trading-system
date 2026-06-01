"""
/ws/market — unified live market data WebSocket.

Protocol:
  Client→Server: {"action": "subscribe",   "symbols": ["NSE:RELIANCE", "CRYPTO:BTC"]}
  Client→Server: {"action": "unsubscribe", "symbols": ["NSE:RELIANCE"]}
  Server→Client: {"type": "quote", "symbol": "NSE:RELIANCE", "ltp": 2847.5, "open": ..., "high": ..., "low": ..., "close": ..., "volume": ..., "ts": "..."}
  Server→Client: {"type": "broker_status", "upstox": "connected", "hyperliquid": "disconnected"}
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
    """
    Singleton. Holds broker adapters + subscriber map.
    Created once at app startup via get_manager().

    Routing: broker_prefix(symbol) → adapter.prefixes matching.
    NSE:RELIANCE → UpstoxAdapter (prefixes=["NSE","BSE"])
    CRYPTO:BTC   → HyperliquidAdapter (prefixes=["CRYPTO"])
    """

    def __init__(self) -> None:
        self._adapters: dict[str, BrokerAdapter] = {}   # prefix → adapter
        self._subs: dict[str, set[WebSocket]] = defaultdict(set)
        self._last_quote: dict[str, dict] = {}          # symbol → last quote dict
        self._clients: set[WebSocket] = set()           # all active connections
        self._started = False

    def register(self, adapter: BrokerAdapter) -> None:
        for prefix in adapter.prefixes:
            self._adapters[prefix] = adapter

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        seen = set()
        for adapter in self._adapters.values():
            if id(adapter) in seen:
                continue
            seen.add(id(adapter))
            asyncio.create_task(self._connect_with_retry(adapter))

    async def _connect_with_retry(self, adapter: BrokerAdapter, max_retries: int = 5) -> None:
        """Try to connect an adapter, retrying with backoff on failure."""
        for attempt in range(max_retries):
            try:
                await adapter.connect()
                log.info(f"adapter_connected name={adapter.name}")
                asyncio.create_task(self._fan_out(adapter))
                # Push updated broker_status to all active WS clients
                asyncio.create_task(self._broadcast_status())
                return
            except Exception as exc:
                wait = 2 ** attempt  # 1, 2, 4, 8, 16 seconds
                log.warning(f"adapter_connect_failed name={adapter.name} error={exc!r} retry_in={wait}s")
                await asyncio.sleep(wait)
        log.error(f"adapter_failed_permanently name={adapter.name}")

    async def reconnect_adapter(self, adapter_name: str) -> None:
        """Called after OAuth token stored — reconnect a previously-failed adapter."""
        seen = set()
        for adapter in self._adapters.values():
            if id(adapter) in seen:
                continue
            seen.add(id(adapter))
            if adapter.name == adapter_name:
                log.info(f"adapter_reconnect_triggered name={adapter_name}")
                asyncio.create_task(self._connect_with_retry(adapter))

    async def _fan_out(self, adapter: BrokerAdapter) -> None:
        async for quote in adapter.quotes():
            msg_data = {"type": "quote", **quote.to_dict()}
            self._last_quote[quote.symbol] = msg_data
            ws_set = self._subs.get(quote.symbol, set())
            if not ws_set:
                continue
            log.info("fan_out %s ltp=%.2f clients=%d", quote.symbol, quote.ltp, len(ws_set))
            msg = json.dumps(msg_data)
            dead: list[WebSocket] = []
            for ws in list(ws_set):
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._cleanup_ws(ws)

    async def _broadcast_status(self) -> None:
        """Push broker_status to all active WS clients."""
        if not self._clients:
            return
        msg = json.dumps({"type": "broker_status", **self.status()})
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._cleanup_ws(ws)

    async def add_client(self, ws: WebSocket, symbols: list[str]) -> None:
        log.info("add_client symbols=%s", symbols)
        for sym in symbols:
            was_empty = not self._subs[sym]
            self._subs[sym].add(ws)
            if was_empty:
                adapter = self._adapters.get(broker_prefix(sym))
                if adapter:
                    try:
                        await adapter.subscribe([sym])
                    except Exception as exc:
                        log.debug("subscribe_error", extra={"sym": sym, "error": str(exc)})
            # Send last cached quote immediately so the client sees data right away
            last = self._last_quote.get(sym)
            if last:
                try:
                    await ws.send_text(json.dumps(last))
                except Exception:
                    pass

    async def remove_client(self, ws: WebSocket, symbols: list[str]) -> None:
        for sym in symbols:
            self._subs[sym].discard(ws)
            if not self._subs[sym]:
                adapter = self._adapters.get(broker_prefix(sym))
                if adapter:
                    try:
                        await adapter.unsubscribe([sym])
                    except Exception:
                        pass

    def _cleanup_ws(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        for ws_set in self._subs.values():
            ws_set.discard(ws)

    def status(self) -> dict:
        seen: dict[str, str] = {}
        for adapter in set(self._adapters.values()):
            running = getattr(adapter, "_running", False)
            seen[adapter.name] = "connected" if running else "disconnected"
        return seen


_manager: MarketFeedManager | None = None


def get_manager() -> MarketFeedManager:
    global _manager
    if _manager is None:
        _manager = MarketFeedManager()
    return _manager


async def market_ws_endpoint(ws: WebSocket, token: str) -> None:
    provider = _get_provider()
    user = await provider.verify_token(token)
    if user is None:
        await ws.close(code=1008)
        return

    await ws.accept()
    manager = get_manager()
    manager._clients.add(ws)
    subscribed: set[str] = set()

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
        manager._clients.discard(ws)
