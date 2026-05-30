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

_UPSTOX_AUTH_URL  = "https://api.upstox.com/v2/login/authorization/token"
_UPSTOX_FEED_AUTH = "https://api.upstox.com/v3/feed/market-data-feed/authorize"

# Interval string used in MarketOHLC.ohlc repeated list for the daily candle.
# Upstox sends "1d" for the day OHLC entry inside MarketOHLC.
_DAY_INTERVAL = "1d"

_NSE_INDICES = {
    "NIFTY 50", "NIFTY50", "BANKNIFTY", "NIFTY BANK",
    "MIDCPNIFTY", "FINNIFTY", "SENSEX",
}


def _to_upstox_key(symbol: str) -> str:
    """Convert canonical symbol to Upstox instrument key.

    Examples::

        'NSE:RELIANCE'  → 'NSE_EQ|RELIANCE'
        'NSE:NIFTY 50'  → 'NSE_INDEX|NIFTY 50'
    """
    if ":" not in symbol:
        return symbol
    exch, ticker = symbol.split(":", 1)
    normalised = ticker.upper().replace(" ", "")
    if normalised in {i.upper().replace(" ", "") for i in _NSE_INDICES}:
        return f"{exch}_INDEX|{ticker}"
    return f"{exch}_EQ|{ticker}"


def _from_upstox_key(instrument_key: str) -> str:
    """Convert Upstox instrument key back to canonical 'EXCH:TICKER' form."""
    return (
        instrument_key
        .replace("_EQ|", ":")
        .replace("_INDEX|", ":")
        .replace("_FO|", ":")
    )


def _extract_day_ohlc(market_ohlc) -> tuple[float, float, float, float] | None:
    """Return (open, high, low, close) for the day candle, or None if absent."""
    for candle in market_ohlc.ohlc:
        if candle.interval == _DAY_INTERVAL:
            return candle.open, candle.high, candle.low, candle.close
    # Fallback: take the first available candle if no "1d" entry
    if market_ohlc.ohlc:
        c = market_ohlc.ohlc[0]
        return c.open, c.high, c.low, c.close
    return None


class UpstoxAdapter:
    """Broker adapter for Upstox WS v3 market-data feed (protobuf).

    Proto field layout (relevant subset)::

        FeedResponse
          .feeds: map<string, Feed>
          .type: Type enum  (initial_feed | live_feed | market_info)

        Feed
          .ltpc: LTPC            — ltp, ltt, ltq, cp
          .fullFeed: FullFeed
            .marketFF: MarketFullFeed
              .ltpc: LTPC
              .marketOHLC: MarketOHLC
                .ohlc[]: OHLC   — interval, open, high, low, close, vol, ts
              .vtt: int64        — volume traded today
            .indexFF: IndexFullFeed
              .ltpc: LTPC
              .marketOHLC: MarketOHLC
    """

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
        """Fetch the stored Upstox access token from Redis."""
        raw = await self._redis.get("upstox:token")
        if isinstance(raw, bytes):
            return raw.decode()
        return raw

    async def _get_ws_url(self, token: str) -> str:
        """Call the Upstox feed-auth endpoint to get the authorised WS URL."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                _UPSTOX_FEED_AUTH,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            return resp.json()["data"]["authorizedRedirectUri"]

    # ------------------------------------------------------------------ #
    # Public interface (BrokerAdapter protocol)                            #
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        """Obtain WS URL from Upstox, open the connection, start recv loop."""
        token = await self._get_token()
        if not token:
            log.warning("upstox_no_token: call /auth/upstox/login first")
            return
        ws_url = await self._get_ws_url(token)
        self._ws = await websockets.connect(ws_url)
        log.info("upstox_connected url=%s", ws_url[:60])
        asyncio.create_task(self._recv_loop())

    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to full-mode feed for the given canonical symbols."""
        if not self._ws:
            log.warning("upstox_subscribe_skipped: not connected")
            return
        keys = [_to_upstox_key(s) for s in symbols]
        self._subscribed.update(symbols)
        msg = json.dumps({
            "guid": "mf-sub",
            "method": "sub",
            "data": {"mode": "full", "instrumentKeys": keys},
        })
        await self._ws.send(msg)
        log.debug("upstox_subscribed keys=%s", keys)

    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from feed for the given canonical symbols."""
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
        log.debug("upstox_unsubscribed keys=%s", keys)

    async def quotes(self) -> AsyncIterator[Quote]:
        """Yield Quote objects as they arrive from the feed."""
        while True:
            yield await self._queue.get()

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._ws = None
            log.info("upstox_disconnected")

    # ------------------------------------------------------------------ #
    # Internal receive loop + proto decode                                 #
    # ------------------------------------------------------------------ #

    async def _recv_loop(self) -> None:
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    self._decode_and_enqueue(raw)
        except websockets.exceptions.ConnectionClosedOK:
            log.info("upstox_ws_closed_clean")
        except Exception as exc:
            log.warning("upstox_recv_error error=%s", exc)

    def _decode_and_enqueue(self, data: bytes) -> None:
        """Decode a FeedResponse protobuf frame and push Quote(s) onto the queue.

        Proto navigation::

            FeedResponse.feeds[instrument_key]   → Feed
              Feed.fullFeed.marketFF              → MarketFullFeed  (equities)
              Feed.fullFeed.indexFF               → IndexFullFeed   (indices)
              Feed.ltpc                           → LTPC-only feed  (fallback)

        OHLC is inside MarketOHLC.ohlc (repeated), filtered by interval == "1d".
        Volume for the day is MarketFullFeed.vtt (volume traded today).
        """
        try:
            feed_resp = MarketDataFeed_pb2.FeedResponse()
            feed_resp.ParseFromString(data)
        except Exception as exc:
            log.debug("upstox_proto_parse_error error=%s", exc)
            return

        now = datetime.now(timezone.utc)

        for instrument_key, feed in feed_resp.feeds.items():
            symbol = _from_upstox_key(instrument_key)
            quote = self._build_quote(symbol, feed, now)
            if quote is not None:
                self._queue.put_nowait(quote)

    def _build_quote(
        self,
        symbol: str,
        feed: "MarketDataFeed_pb2.Feed",
        ts: datetime,
    ) -> Quote | None:
        """Try every field path in order of richness; return None on total failure."""

        # ── Path 1: fullFeed.marketFF  (equities / derivatives) ──────────
        try:
            ff = feed.fullFeed.marketFF
            ltpc = ff.ltpc
            if ltpc.ltp:
                ohlc_vals = _extract_day_ohlc(ff.marketOHLC)
                if ohlc_vals:
                    o, h, l, c = ohlc_vals
                else:
                    # No candle data yet — use close price as proxy
                    o = h = l = c = ltpc.cp
                return Quote(
                    symbol=symbol,
                    ltp=ltpc.ltp,
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=float(ff.vtt),  # volume traded today
                    ts=ts,
                )
        except Exception:
            pass

        # ── Path 2: fullFeed.indexFF  (NSE/BSE indices) ───────────────────
        try:
            ix = feed.fullFeed.indexFF
            ltpc = ix.ltpc
            if ltpc.ltp:
                ohlc_vals = _extract_day_ohlc(ix.marketOHLC)
                if ohlc_vals:
                    o, h, l, c = ohlc_vals
                else:
                    o = h = l = c = ltpc.cp
                return Quote(
                    symbol=symbol,
                    ltp=ltpc.ltp,
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=0.0,  # indices have no volume
                    ts=ts,
                )
        except Exception:
            pass

        # ── Path 3: feed.ltpc  (LTPC-only / compact feed) ────────────────
        try:
            ltpc = feed.ltpc
            if ltpc.ltp:
                return Quote(
                    symbol=symbol,
                    ltp=ltpc.ltp,
                    open=ltpc.cp,
                    high=ltpc.cp,
                    low=ltpc.cp,
                    close=ltpc.cp,
                    volume=0.0,
                    ts=ts,
                )
        except Exception:
            pass

        log.debug("upstox_no_usable_feed symbol=%s", symbol)
        return None
