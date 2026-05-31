# brokers/hyperliquid.py
"""
Hyperliquid WS adapter — uses the `trades` subscription (per coin) so the
chart receives actual executed prices with real OHLCV movement, not the
mid-price from allMids which barely changes.

Protocol:
  subscribe:   {"method": "subscribe",   "subscription": {"type": "trades", "coin": "BTC"}}
  unsubscribe: {"method": "unsubscribe", "subscription": {"type": "trades", "coin": "BTC"}}
  message:     {"channel": "trades", "data": [{"coin":"BTC","px":"74032.5","sz":"0.5","time":1234567890123,...}]}
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Dict, List

import websockets

from brokers.base import Quote

log = logging.getLogger(__name__)


class HyperliquidAdapter:
    name = "hyperliquid"
    prefixes = ["CRYPTO"]
    SUPPORTED_COINS: List[str] = [
        "BTC", "ETH", "SOL", "BNB", "DOGE", "XRP",
        "AVAX", "MATIC", "ARB", "OP", "SUI", "APT", "INJ", "TIA",
    ]

    def __init__(self):
        self._ws = None
        self._queue: asyncio.Queue[Quote] = asyncio.Queue()
        self._subscribed: set[str] = set()          # bare coins, e.g. "BTC"
        self._last_price: Dict[str, float] = {}     # coin → last trade price (for open/high/low)
        self._recv_task: asyncio.Task | None = None
        self._running = False

    # ── Symbol helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _to_hl_coin(symbol: str) -> str:
        return symbol[len("CRYPTO:"):] if symbol.startswith("CRYPTO:") else symbol

    @staticmethod
    def _from_hl_coin(coin: str) -> str:
        return f"CRYPTO:{coin}"

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        if self._running:
            return
        self._ws = await websockets.connect("wss://api.hyperliquid.xyz/ws")
        self._running = True
        log.info("hyperliquid connected.")

        # Re-subscribe any coins tracked from a previous connection
        for coin in list(self._subscribed):
            await self._ws.send(json.dumps(
                {"method": "subscribe", "subscription": {"type": "trades", "coin": coin}}
            ))

        self._recv_task = asyncio.create_task(self._recv_loop())

    async def disconnect(self) -> None:
        self._running = False
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None

    # ── Subscription management ───────────────────────────────────────────────

    async def subscribe(self, symbols: List[str]) -> None:
        for symbol in symbols:
            coin = self._to_hl_coin(symbol)
            if coin not in self._subscribed:
                self._subscribed.add(coin)
                if self._ws and self._running:
                    await self._ws.send(json.dumps(
                        {"method": "subscribe", "subscription": {"type": "trades", "coin": coin}}
                    ))
                    log.info("hyperliquid_subscribed coin=%s", coin)

    async def unsubscribe(self, symbols: List[str]) -> None:
        for symbol in symbols:
            coin = self._to_hl_coin(symbol)
            if coin in self._subscribed:
                self._subscribed.discard(coin)
                if self._ws and self._running:
                    await self._ws.send(json.dumps(
                        {"method": "unsubscribe", "subscription": {"type": "trades", "coin": coin}}
                    ))

    # ── Receive loop ──────────────────────────────────────────────────────────

    async def _recv_loop(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                    if msg.get("channel") != "trades":
                        continue
                    for trade in msg.get("data", []):
                        coin = trade.get("coin", "")
                        if coin not in self._subscribed:
                            continue
                        try:
                            ltp = float(trade["px"])
                            volume = float(trade.get("sz", 0.0))
                            ts = datetime.fromtimestamp(
                                trade["time"] / 1000, tz=timezone.utc
                            )
                        except (KeyError, ValueError, TypeError):
                            continue

                        prev = self._last_price.get(coin, ltp)
                        self._last_price[coin] = ltp

                        await self._queue.put(Quote(
                            symbol=self._from_hl_coin(coin),
                            ltp=ltp,
                            open=prev,
                            high=max(ltp, prev),
                            low=min(ltp, prev),
                            close=ltp,
                            volume=volume,
                            ts=ts,
                        ))
                except Exception as exc:
                    log.error("hyperliquid_recv_error: %s", exc)

        except websockets.ConnectionClosedOK:
            log.info("hyperliquid ws closed normally.")
        except websockets.ConnectionClosedError as exc:
            log.error("hyperliquid ws closed abruptly: %s", exc)
        except Exception as exc:
            log.error("hyperliquid recv_loop unexpected: %s", exc)
        finally:
            self._running = False
            self._ws = None

    # ── Quote stream ──────────────────────────────────────────────────────────

    async def quotes(self) -> AsyncIterator[Quote]:
        while True:
            try:
                yield await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                return
