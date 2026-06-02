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

# Correct instrument keys for indices (WS feed uses these exact strings)
_INDEX_INSTRUMENT_KEYS: dict[str, str] = {
    "NSE:NIFTY 50":         "NSE_INDEX|Nifty 50",
    "NSE:NIFTY BANK":       "NSE_INDEX|Nifty Bank",
    "NSE:NIFTY MID SELECT": "NSE_INDEX|NIFTY MID SELECT",
    "BSE:SENSEX":           "BSE_INDEX|SENSEX",
}

# In-process instruments cache: exchange → {trading_symbol: instrument_key}
_INSTRUMENTS_CACHE: dict[str, dict[str, str]] = {}
# Reverse: instrument_key → canonical symbol
_KEY_TO_SYMBOL: dict[str, str] = {}
# NFO instrument key cache: compact_ticker → instrument_key
# Populated from complete.json.gz on first NFO subscription
_NFO_KEY_CACHE: dict[str, str] = {}
# Tuple index: (underlying_symbol, strike_int, instrument_type, expiry_date_str) → instrument_key
_NFO_TUPLE_INDEX: dict[tuple, str] = {}
_NFO_FULL_LOADED = False

# Kite weekly expiry month-char → month number
_KITE_MONTH_CHAR = {
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
    "7": 7, "8": 8, "9": 9, "O": 10, "N": 11, "D": 12,
}


def _load_instruments(exchange: str) -> dict[str, str]:
    """Download and cache Upstox instruments (trading_symbol → instrument_key).

    EQ exchanges (NSE/BSE): only EQ type.
    Derivatives exchanges (NFO/BFO): all types (CE/PE/FUT) for options/futures lookup.
    """
    if exchange in _INSTRUMENTS_CACHE:
        return _INSTRUMENTS_CACHE[exchange]
    try:
        import gzip, json as _json, httpx as _httpx
        url  = f"https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz"
        resp = _httpx.get(url, timeout=30, follow_redirects=True)
        data = _json.loads(gzip.decompress(resp.content))
        eq_only = exchange not in ("NFO", "BFO", "CDS", "MCX")
        mapping = {
            item["trading_symbol"]: item["instrument_key"]
            for item in data
            if not eq_only or item.get("instrument_type") == "EQ"
        }
        _INSTRUMENTS_CACHE[exchange] = mapping
        return mapping
    except Exception as exc:
        log.warning("upstox_instruments_load_failed exchange=%s error=%s", exchange, exc)
        return {}


def _load_nfo_instruments() -> None:
    """Download complete.json.gz and populate _NFO_TUPLE_INDEX for NSE_FO/BSE_FO.

    Indexes by (underlying_symbol, strike_int, instrument_type, expiry_YYYY-MM-DD)
    because the compact ticker format (NIFTY2660223550CE) differs from the display
    format in the instruments file (NIFTY 23550 CE 02 JUN 26).
    """
    global _NFO_FULL_LOADED
    if _NFO_FULL_LOADED:
        return
    _NFO_FULL_LOADED = True
    try:
        import gzip, json as _json
        from datetime import datetime as _dt, timezone as _tz
        url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        if resp.status_code != 200:
            log.warning("nfo_complete_instruments_failed status=%d", resp.status_code)
            return
        data = _json.loads(gzip.decompress(resp.content))
        count = 0
        for item in data:
            seg = item.get("segment", "")
            if seg not in ("NSE_FO", "BSE_FO"):
                continue
            key = item.get("instrument_key", "")
            underlying = item.get("underlying_symbol", "") or item.get("asset_symbol", "")
            inst_type = item.get("instrument_type", "")  # CE | PE | FUT
            strike = item.get("strike_price")
            expiry_ms = item.get("expiry")
            if not (key and underlying and inst_type and expiry_ms is not None):
                continue
            # expiry is ms timestamp → YYYY-MM-DD string
            expiry_str = _dt.fromtimestamp(expiry_ms / 1000, tz=_tz.utc).strftime("%Y-%m-%d")
            strike_int = int(strike) if strike is not None else 0
            tup = (underlying, strike_int, inst_type, expiry_str)
            _NFO_TUPLE_INDEX[tup] = key
            exch = "NFO" if seg == "NSE_FO" else "BFO"
            ts_display = item.get("trading_symbol", "")
            _KEY_TO_SYMBOL[key] = f"{exch}:{ts_display}"
            count += 1
        log.info("nfo_instruments_loaded count=%d", count)
    except Exception as exc:
        log.warning("nfo_instruments_load_error error=%s", exc)
        _NFO_FULL_LOADED = False


def _parse_compact_nfo_ticker(ticker: str) -> tuple[str, int, str, str] | None:
    """Parse Kite-style compact NFO ticker to (underlying, strike_int, inst_type, expiry_YYYY-MM-DD).

    Weekly format:  NIFTY2660223550CE  → underlying=NIFTY, YY=26, month_char=6, DD=02, strike=23550, type=CE
    Monthly format: NIFTY26JUN23550CE  → underlying=NIFTY, YY=26, MMM=JUN, strike=23550, type=CE
    """
    import re
    from datetime import date as _date
    # Monthly: underlying + YY + MMM (3-char) + strike + type
    m = re.match(r"^([A-Z]+?)(\d{2})([A-Z]{3})(\d+)(CE|PE|FUT)$", ticker)
    if m:
        underlying, yy, mmm, strike_s, inst_type = m.groups()
        month_map = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
                     "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
        month = month_map.get(mmm)
        if month is None:
            return None
        year = 2000 + int(yy)
        # Monthly expiry: last Thursday of month — approximate as last day then walk back
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        d = _date(year, month, last_day)
        while d.weekday() != 3:  # 3=Thursday
            d -= __import__("datetime").timedelta(days=1)
        return underlying, int(strike_s), inst_type, d.strftime("%Y-%m-%d")
    # Weekly: underlying + YY + month_char(1 digit/char) + DD (2 digits) + strike + type
    m = re.match(r"^([A-Z]+?)(\d{2})([1-9OND])(\d{2})(\d+)(CE|PE|FUT)$", ticker)
    if m:
        underlying, yy, mchar, dd, strike_s, inst_type = m.groups()
        month = _KITE_MONTH_CHAR.get(mchar)
        if month is None:
            return None
        year = 2000 + int(yy)
        try:
            d = _date(year, month, int(dd))
        except ValueError:
            return None
        return underlying, int(strike_s), inst_type, d.strftime("%Y-%m-%d")
    return None


def _resolve_nfo_key(ticker: str, access_token: str | None = None) -> str | None:  # noqa: ARG001
    """Return NSE_FO instrument_key for a compact NFO trading symbol.

    Loads complete.json.gz on first call (cached for session). Parses the
    compact ticker to (underlying, strike, type, expiry) and looks up in index.
    """
    if ticker in _NFO_KEY_CACHE:
        return _NFO_KEY_CACHE[ticker]
    if not _NFO_FULL_LOADED:
        _load_nfo_instruments()
    parsed = _parse_compact_nfo_ticker(ticker)
    if parsed is None:
        log.warning("nfo_ticker_parse_failed ticker=%s", ticker)
        return None
    key = _NFO_TUPLE_INDEX.get(parsed)
    if key:
        _NFO_KEY_CACHE[ticker] = key  # cache for fast re-lookup
        # Override with compact symbol so fan_out uses the same symbol the client subscribed with
        exch = "NFO"  # BSE_FO would be BFO but we only get here via NFO: prefix
        _KEY_TO_SYMBOL[key] = f"{exch}:{ticker}"
        log.info("nfo_key_resolved ticker=%s key=%s tuple=%s", ticker, key, parsed)
    else:
        log.warning("nfo_key_not_found ticker=%s tuple=%s index_size=%d", ticker, parsed, len(_NFO_TUPLE_INDEX))
    return key


def _to_upstox_ws_key(symbol: str, access_token: str | None = None) -> str:
    """Instrument key for the v3 WebSocket feed.

    Indices use hardcoded name-based keys; equities require ISIN-based keys;
    NFO/BFO use Instrument Search API (instruments file returns 403).

    Examples::

        'NSE:HDFCBANK'  → 'NSE_EQ|INE040A01034'
        'NSE:NIFTY 50'  → 'NSE_INDEX|Nifty 50'
        'NFO:NIFTY2460624100CE' → 'NSE_FO|12345'
    """
    # Indices — use hardcoded correct-case keys
    if symbol in _INDEX_INSTRUMENT_KEYS:
        key = _INDEX_INSTRUMENT_KEYS[symbol]
        _KEY_TO_SYMBOL[key] = symbol
        return key
    if ":" not in symbol:
        return symbol
    exch, ticker = symbol.split(":", 1)
    # NFO/BFO — use search API instead of instruments file (403)
    if exch in ("NFO", "BFO"):
        nfo_key = _resolve_nfo_key(ticker, access_token)
        if nfo_key:
            return nfo_key
        key = f"NSE_FO|{ticker}"
        _KEY_TO_SYMBOL[key] = symbol
        return key
    # Equities — must use ISIN-based instrument key
    mapping = _load_instruments(exch)
    if ticker in mapping:
        key = mapping[ticker]
        _KEY_TO_SYMBOL[key] = symbol
        return key
    # Fallback (should rarely happen)
    key = f"{exch}_EQ|{ticker}"
    _KEY_TO_SYMBOL[key] = symbol
    return key


def _to_upstox_key(symbol: str) -> str:
    """Convert canonical symbol → Upstox instrument key (ISIN-based for equities).

    Uses instruments file for equities so the key works with both WS and REST API.
    Indices use hardcoded correct-case keys.

    Examples::

        'NSE:HDFCBANK'  → 'NSE_EQ|INE040A01034'
        'NSE:NIFTY 50'  → 'NSE_INDEX|Nifty 50'
    """
    if symbol in _INDEX_INSTRUMENT_KEYS:
        key = _INDEX_INSTRUMENT_KEYS[symbol]
        _KEY_TO_SYMBOL[key] = symbol
        return key
    if ":" not in symbol:
        return symbol
    exch, ticker = symbol.split(":", 1)
    mapping = _load_instruments(exch)
    if ticker in mapping:
        key = mapping[ticker]
        _KEY_TO_SYMBOL[key] = symbol
        return key
    # Fallback for unknown symbols
    key = f"{exch}_EQ|{ticker}"
    _KEY_TO_SYMBOL[key] = symbol
    return key


def _from_upstox_key(instrument_key: str) -> str:
    """Convert Upstox instrument key back to canonical 'EXCH:TICKER' form."""
    # Check reverse lookup first (populated when we subscribed)
    if instrument_key in _KEY_TO_SYMBOL:
        return _KEY_TO_SYMBOL[instrument_key]
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
    prefixes = ["NSE", "BSE", "NFO", "BFO"]

    def __init__(self, api_key: str, api_secret: str, redis_client) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._redis = redis_client
        self._ws = None
        self._queue: asyncio.Queue[Quote] = asyncio.Queue()
        self._subscribed: set[str] = set()
        self._running = False

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
            if resp.status_code == 401:
                # Token is stale — delete it from Redis so status shows disconnected correctly
                try:
                    await self._redis.delete("upstox:token")
                    log.warning("upstox_token_expired: cleared stale token from Redis")
                except Exception:
                    pass
            resp.raise_for_status()
            return resp.json()["data"]["authorizedRedirectUri"]

    # ------------------------------------------------------------------ #
    # Public interface (BrokerAdapter protocol)                            #
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        """Obtain WS URL from Upstox, open the connection, start recv loop."""
        if self._running:
            return
        token = await self._get_token()
        if not token:
            log.warning("upstox_no_token: call /auth/upstox/login first")
            return
        ws_url = await self._get_ws_url(token)
        try:
            self._ws = await websockets.connect(ws_url)
        except websockets.exceptions.InvalidStatus as exc:
            if exc.response.status_code in (401, 403):
                # Token expired — clear from Redis so UI shows "Connect" not "Reconnect"
                try:
                    await self._redis.delete("upstox:token")
                    log.warning("upstox_token_rejected status=%d: cleared token", exc.response.status_code)
                except Exception:
                    pass
            raise
        self._running = True
        log.info("upstox_connected url=%s", ws_url[:60])
        asyncio.create_task(self._recv_loop())
        # Re-subscribe any symbols from a previous connection
        if self._subscribed:
            await self.subscribe(list(self._subscribed))

    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to full-mode feed for the given canonical symbols.

        Upstox v3 WS requires subscription messages sent as BINARY (bytes),
        not as text frames. Uses ticker-symbol keys (NSE_EQ|HDFCBANK), not ISINs.
        """
        if not self._ws:
            log.warning("upstox_subscribe_skipped: not connected")
            return
        token = await self._get_token()
        keys = [_to_upstox_ws_key(s, access_token=token) for s in symbols]
        self._subscribed.update(symbols)
        msg = json.dumps({
            "guid": "mf-sub",
            "method": "sub",
            "data": {"mode": "full", "instrumentKeys": keys},
        }).encode()                       # ← must be binary, not text
        await self._ws.send(msg)
        log.info("upstox_subscribed keys=%s", keys)

    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from feed for the given canonical symbols."""
        if not self._ws:
            return
        keys = [_to_upstox_ws_key(s) for s in symbols]
        for s in symbols:
            self._subscribed.discard(s)
        msg = json.dumps({
            "guid": "mf-unsub",
            "method": "unsub",
            "data": {"instrumentKeys": keys},
        }).encode()                       # ← must be binary
        await self._ws.send(msg)
        log.debug("upstox_unsubscribed keys=%s", keys)

    async def quotes(self) -> AsyncIterator[Quote]:
        """Yield Quote objects as they arrive from the feed."""
        while True:
            yield await self._queue.get()

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
            log.info("upstox_disconnected")

    # ------------------------------------------------------------------ #
    # Internal receive loop + proto decode                                 #
    # ------------------------------------------------------------------ #

    async def _recv_loop(self) -> None:
        while True:
            try:
                async for raw in self._ws:
                    if isinstance(raw, bytes):
                        self._decode_and_enqueue(raw)
            except websockets.exceptions.ConnectionClosedOK:
                log.info("upstox_ws_closed_clean")
            except Exception as exc:
                log.warning("upstox_recv_error error=%s", exc)
            finally:
                self._running = False
                self._ws = None

            # Auto-reconnect with exponential backoff (stops if token invalid)
            for delay in (2, 5, 10, 30, 60):
                log.info("upstox_reconnecting in=%ds", delay)
                await asyncio.sleep(delay)
                try:
                    token = await self._get_token()
                    if not token:
                        log.warning("upstox_reconnect_no_token — user must re-login")
                        return
                    ws_url = await self._get_ws_url(token)
                    self._ws = await websockets.connect(ws_url)
                    self._running = True
                    log.info("upstox_reconnected url=%s", ws_url[:60])
                    if self._subscribed:
                        await self.subscribe(list(self._subscribed))
                    break
                except websockets.exceptions.InvalidStatus as exc:
                    if exc.response.status_code in (401, 403):
                        log.warning("upstox_reconnect_token_rejected status=%d — user must re-login", exc.response.status_code)
                        return  # Don't retry with bad token
                    log.warning("upstox_reconnect_failed error=%s", exc)
                except Exception as exc:
                    log.warning("upstox_reconnect_failed error=%s", exc)
            else:
                log.error("upstox_reconnect_exhausted — giving up")
                return

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
            if ltpc.ltp or ltpc.cp:
                ohlc_vals = _extract_day_ohlc(ff.marketOHLC)
                if ohlc_vals:
                    o, h, l, c = ohlc_vals
                else:
                    # No candle data yet — use close price as proxy
                    o = h = l = c = ltpc.cp
                price = ltpc.ltp or ltpc.cp
                return Quote(
                    symbol=symbol,
                    ltp=price,
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
            if ltpc.ltp or ltpc.cp:
                ohlc_vals = _extract_day_ohlc(ix.marketOHLC)
                if ohlc_vals:
                    o, h, l, c = ohlc_vals
                else:
                    o = h = l = c = ltpc.cp
                price = ltpc.ltp or ltpc.cp
                return Quote(
                    symbol=symbol,
                    ltp=price,
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
