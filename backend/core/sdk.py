from __future__ import annotations
import asyncio
from datetime import datetime, date
import pandas as pd
import pandas_ta as ta
from core.config import settings
from core.db import get_questdb_conn
from core.storage import get_storage

SCANNER_DSL_VERSION = settings.SCANNER_DSL_VERSION

TF_TABLE = {"1min": "ohlcv_1min", "1h": "ohlcv_hourly", "1d": "ohlcv_daily"}

# All supported timeframes and their pandas resample frequency strings.
# None = no resampling needed (already 1min base).
RESAMPLE_FREQ: dict[str, str | None] = {
    "1min":  None,
    "3min":  "3min",
    "5min":  "5min",
    "15min": "15min",
    "30min": "30min",
    "1h":    "1h",
    "4h":    "4h",
    "1d":    "1D",
    "1w":    "1W",
    "1M":    "1ME",
}

_UPSTOX_BASE = "https://api.upstox.com/v2"

# Hardcoded index mappings (canonical symbol → Upstox historical-candle instrument key)
_INDEX_UPSTOX_KEYS: dict[str, str] = {
    "NSE:NIFTY 50":         "NSE_INDEX|Nifty 50",
    "NSE:NIFTY BANK":       "NSE_INDEX|Nifty Bank",
    "NSE:NIFTY MID SELECT": "NSE_INDEX|NIFTY MID SELECT",
    "BSE:SENSEX":           "BSE_INDEX|SENSEX",
}

# Cache: exchange → {trading_symbol: instrument_key}
_INSTRUMENTS_CACHE: dict[str, dict[str, str]] = {}

def _load_instruments(exchange: str) -> dict[str, str]:
    """Download Upstox instruments file and return trading_symbol → instrument_key for EQ type."""
    global _INSTRUMENTS_CACHE
    if exchange in _INSTRUMENTS_CACHE:
        return _INSTRUMENTS_CACHE[exchange]
    try:
        import gzip, json, httpx as _httpx
        url  = f"https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz"
        resp = _httpx.get(url, timeout=30, follow_redirects=True)
        data = json.loads(gzip.decompress(resp.content))
        mapping = {
            item["trading_symbol"]: item["instrument_key"]
            for item in data
            if item.get("instrument_type") == "EQ"
        }
        _INSTRUMENTS_CACHE[exchange] = mapping
        return mapping
    except Exception:
        return {}

def _upstox_historical_key(symbol: str) -> str:
    """Return the correct Upstox instrument key for historical-candle API calls."""
    if symbol in _INDEX_UPSTOX_KEYS:
        return _INDEX_UPSTOX_KEYS[symbol]
    if ":" not in symbol:
        return symbol
    exch, ticker = symbol.split(":", 1)
    mapping = _load_instruments(exch)
    if ticker in mapping:
        return mapping[ticker]
    # Fallback: use WebSocket-style key (may not work for historical API)
    from brokers.upstox import _to_upstox_key
    return _to_upstox_key(symbol)

# (upstox_interval, resample_tf_or_None)
# For TFs without native Upstox support, fetch finer interval and resample.
_UPSTOX_INTERVAL: dict[str, tuple[str, str | None]] = {
    "1min":  ("1minute",  None),
    "3min":  ("1minute",  "3min"),
    "5min":  ("1minute",  "5min"),
    "15min": ("1minute",  "15min"),
    "30min": ("30minute", None),
    "1h":    ("30minute", "1h"),
    "4h":    ("30minute", "4h"),
    "1d":    ("day",      None),
    "1w":    ("week",     None),
    "1M":    ("month",    None),
}

# Kite MCP interval strings; None = unsupported (skip Kite fallback)
_KITE_INTERVAL: dict[str, str | None] = {
    "1min":  "minute",
    "3min":  "3minute",
    "5min":  "5minute",
    "15min": "15minute",
    "30min": "30minute",
    "1h":    "60minute",
    "4h":    "60minute",   # aggregate 60min → 4h via resample_ohlcv
    "1d":    "day",
    "1w":    "week",
    "1M":    None,
}


def resample_ohlcv(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Resample 1-min OHLCV dataframe to the requested timeframe."""
    freq = RESAMPLE_FREQ.get(tf)
    if freq is None or df.empty:
        return df

    symbol = df["symbol"].iloc[0] if "symbol" in df.columns else None
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts")

    agg = df.resample(freq, label="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["open"])

    agg = agg.reset_index()
    if symbol is not None:
        agg["symbol"] = symbol
    return agg


class MarketData:
    async def ohlcv(
        self,
        symbol: str,
        tf: str,
        from_dt: datetime,
        to_dt: datetime,
        adjusted: bool = True,
    ) -> pd.DataFrame:
        if tf not in RESAMPLE_FREQ:
            raise ValueError(f"Unknown timeframe {tf!r}. Use: {list(RESAMPLE_FREQ)}")

        # Always fetch from 1min table (covers all aggregated timeframes)
        base_table = "ohlcv_1min"

        # Try QuestDB hot layer first
        df = await asyncio.get_running_loop().run_in_executor(
            None, self._query_questdb, base_table, symbol, from_dt, to_dt
        )
        if not df.empty:
            return resample_ohlcv(df, tf)

        # Transparent fallback to DuckDB + Parquet (always 1min base)
        df = self._query_parquet(symbol, "1min", from_dt, to_dt)
        if not df.empty:
            return resample_ohlcv(df, tf)

        # Last resort: Kite MCP (covers indices + symbols not in QuestDB/Parquet)
        try:
            df = await asyncio.get_running_loop().run_in_executor(
                None, self._query_kitemcp, symbol, tf, from_dt, to_dt
            )
            if not df.empty:
                return df
        except Exception:
            pass

        return pd.DataFrame()

    def _query_questdb(
        self, table: str, symbol: str, from_dt: datetime, to_dt: datetime
    ) -> pd.DataFrame:
        # QuestDB doesn't accept ::timestamptz casts that psycopg2 adds for
        # tz-aware datetimes. Strip tzinfo — QuestDB stores all timestamps as UTC.
        from_naive = from_dt.replace(tzinfo=None) if from_dt.tzinfo else from_dt
        to_naive   = to_dt.replace(tzinfo=None)   if to_dt.tzinfo   else to_dt
        conn = get_questdb_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM {table} WHERE symbol=%s AND ts BETWEEN %s AND %s ORDER BY ts",
                    (symbol, from_naive, to_naive),
                )
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
            return pd.DataFrame(rows, columns=cols)
        finally:
            conn.close()

    def _query_parquet(
        self, symbol: str, tf: str, from_dt: datetime, to_dt: datetime
    ) -> pd.DataFrame:
        storage = get_storage()
        years = range(from_dt.year, to_dt.year + 1)
        frames = []
        for y in years:
            pattern = f"timeframe={tf}/year={y}/**/*.parquet"
            df = storage.read_parquet(pattern, hive_partitioning=True)
            if not df.empty:
                frames.append(df)
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        df["ts"] = pd.to_datetime(df["ts"]).dt.tz_localize(None)
        from_naive = from_dt.replace(tzinfo=None)
        to_naive = to_dt.replace(tzinfo=None)
        mask = (df["symbol"] == symbol) & (df["ts"] >= from_naive) & (df["ts"] <= to_naive)
        return df[mask].copy()

    def _query_kitemcp(
        self, symbol: str, tf: str, from_dt: datetime, to_dt: datetime
    ) -> pd.DataFrame:
        """Fetch OHLCV from Kite MCP. Used as fallback for indices and symbols not in QuestDB."""
        import json
        from pathlib import Path
        import httpx

        kite_interval = _KITE_INTERVAL.get(tf)
        if kite_interval is None:
            return pd.DataFrame()

        # Prefer Redis session (set by /auth/kite/init), fall back to file
        session_id = ""
        try:
            import redis as _redis_lib
            from core.config import settings as _settings
            _r = _redis_lib.from_url(_settings.REDIS_URL, decode_responses=True)
            session_id = _r.get("kite:session_id") or ""
        except Exception:
            pass
        if not session_id:
            session_file = Path(__file__).parent.parent / "scripts" / ".kitemcp_session"
            if session_file.exists():
                session_id = session_file.read_text().strip()
        if not session_id:
            return pd.DataFrame()

        from workers.activities.fetch_kitemcp_1min import _kite_limiter

        def _call(tool_name: str, args: dict):
            _kite_limiter.acquire()
            resp = httpx.post(
                "https://mcp.kite.trade/mcp",
                json={"jsonrpc": "2.0", "method": "tools/call",
                      "params": {"name": tool_name, "arguments": args}, "id": 1},
                headers={"Content-Type": "application/json",
                         "Accept": "application/json",
                         "mcp-session-id": session_id},
                timeout=30,
            )
            resp.raise_for_status()
            text = resp.json().get("result", {}).get("content", [{}])[0].get("text", "{}")
            return json.loads(text)

        # Resolve symbol → instrument_token via search_instruments
        if ":" in symbol:
            exchange, name = symbol.split(":", 1)
        else:
            exchange, name = "NSE", symbol

        raw = _call("search_instruments", {"query": name, "exchange": exchange})
        inst_list = raw if isinstance(raw, list) else (
            raw.get("instruments") or raw.get("data") or []
        )

        token: int | None = None
        for inst in inst_list:
            if not isinstance(inst, dict):
                continue
            ts = (inst.get("tradingsymbol") or "").strip().upper()
            if ts == name.strip().upper():
                token = inst.get("instrument_token")
                break

        if token is None:
            return pd.DataFrame()

        from_str = from_dt.strftime("%Y-%m-%d %H:%M:%S")
        to_str   = to_dt.strftime("%Y-%m-%d %H:%M:%S")
        candles  = _call("get_historical_data", {
            "instrument_token": token,
            "interval": kite_interval,
            "from_date": from_str,
            "to_date": to_str,
        })

        if not isinstance(candles, list) or not candles:
            return pd.DataFrame()

        rows = []
        for c in candles:
            if isinstance(c, list) and len(c) >= 6:
                rows.append({"ts": c[0], "open": float(c[1]), "high": float(c[2]),
                             "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])})
            elif isinstance(c, dict):
                rows.append({
                    "ts":     c.get("date") or c.get("timestamp") or c.get("ts"),
                    "open":   float(c.get("open",  0)),
                    "high":   float(c.get("high",  0)),
                    "low":    float(c.get("low",   0)),
                    "close":  float(c.get("close", 0)),
                    "volume": float(c.get("volume", 0)),
                })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["symbol"] = symbol
        df["ts"] = pd.to_datetime(df["ts"])
        df = df.dropna(subset=["open", "high", "low", "close"])

        # 4h: Kite returns 60min data, resample to 4h
        if tf == "4h":
            return resample_ohlcv(df, "4h")

        return df

    def _query_upstox(
        self, symbol: str, tf: str, from_dt: datetime, to_dt: datetime
    ) -> pd.DataFrame:
        """Fetch OHLCV from Upstox REST API using the stored OAuth token."""
        import httpx
        import redis as redis_lib
        from datetime import timedelta

        interval_info = _UPSTOX_INTERVAL.get(tf)
        if not interval_info:
            return pd.DataFrame()
        upstox_interval, resample_to = interval_info

        try:
            redis_url = settings.redis_url
        except Exception:
            redis_url = "redis://localhost:6379"
        rdb = redis_lib.from_url(redis_url, decode_responses=True)
        token = rdb.get("upstox:token")
        rdb.close()
        if not token:
            return pd.DataFrame()

        from urllib.parse import quote
        instrument_key = _upstox_historical_key(symbol)
        encoded_key = quote(instrument_key, safe="")   # encode | as %7C
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        def _fetch_historical(from_d: str, to_d: str) -> list:
            url = f"{_UPSTOX_BASE}/historical-candle/{encoded_key}/{upstox_interval}/{to_d}/{from_d}"
            resp = httpx.get(url, headers=headers, timeout=20)
            if resp.status_code == 200:
                return resp.json().get("data", {}).get("candles", [])
            return []

        def _fetch_intraday() -> list:
            url = f"{_UPSTOX_BASE}/historical-candle/intraday/{encoded_key}/{upstox_interval}"
            resp = httpx.get(url, headers=headers, timeout=20)
            if resp.status_code == 200:
                return resp.json().get("data", {}).get("candles", [])
            return []

        today = datetime.now().date()
        from_d = from_dt.strftime("%Y-%m-%d")
        # Historical endpoint only covers up to yesterday
        hist_to = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        candles: list = []

        if from_dt.date() <= today - timedelta(days=1):
            candles = _fetch_historical(from_d, hist_to)

        # Append today's intraday candles if requested range includes today
        if to_dt.date() >= today:
            candles = _fetch_intraday() + candles

        if not candles:
            return pd.DataFrame()

        rows = []
        for c in candles:
            # Upstox format: [ts, open, high, low, close, volume, oi]
            if isinstance(c, list) and len(c) >= 6:
                rows.append({
                    "ts": c[0], "open": float(c[1]), "high": float(c[2]),
                    "low": float(c[3]), "close": float(c[4]), "volume": float(c[5]),
                })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["symbol"] = symbol
        df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None)
        df = df.sort_values("ts").reset_index(drop=True)
        df = df.dropna(subset=["open", "high", "low", "close"])

        if resample_to:
            return resample_ohlcv(df, resample_to)
        return df

    async def live_ohlcv(
        self,
        symbol: str,
        tf: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> pd.DataFrame:
        """Fetch OHLCV for live charts. Upstox first, then Kite MCP. No QuestDB."""
        if tf not in RESAMPLE_FREQ:
            raise ValueError(f"Unknown timeframe {tf!r}")

        loop = asyncio.get_running_loop()

        # Primary: Upstox (same OAuth as WS feed, consistent data)
        try:
            df = await loop.run_in_executor(None, self._query_upstox, symbol, tf, from_dt, to_dt)
            if not df.empty:
                return df
        except Exception:
            pass

        # Fallback: Kite MCP
        try:
            df = await loop.run_in_executor(None, self._query_kitemcp, symbol, tf, from_dt, to_dt)
            if not df.empty:
                return df
        except Exception:
            pass

        return pd.DataFrame()

    async def market_events(
        self,
        event_type: str,
        date_: date,
        symbol: str | None = None,
        collection_label: str | None = None,
    ) -> pd.DataFrame:
        from sqlalchemy import text
        from core.db import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            where = "event_type = :event_type AND date = :date"
            params: dict = {"event_type": event_type, "date": date_}
            if symbol is not None:
                where += " AND symbol = :symbol"
                params["symbol"] = symbol
            if collection_label is not None:
                where += " AND collection_label = :collection_label"
                params["collection_label"] = collection_label
            result = await session.execute(
                text(f"SELECT * FROM market_events WHERE {where} ORDER BY rank"),
                params,
            )
            rows = result.fetchall()
            return pd.DataFrame(rows, columns=result.keys())

    async def universe(self, filters: dict | None = None) -> list[str]:
        from sqlalchemy import text
        from core.db import AsyncSessionLocal

        where_clauses = []
        params: dict = {}

        if filters:
            allowed = {"exchange", "sector", "industry"}
            for i, (key, value) in enumerate(filters.items()):
                if key not in allowed:
                    continue  # silently skip unknown filter keys
                param_name = f"f{i}"
                where_clauses.append(f"{key} = :{param_name}")
                params[param_name] = value

        query = "SELECT symbol FROM stocks"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        query += " ORDER BY symbol"

        async with AsyncSessionLocal() as session:
            result = await session.execute(text(query), params)
            symbols = [r[0] for r in result.fetchall()]
        return symbols


class Indicators:
    @staticmethod
    def rsi(data: pd.DataFrame, period: int = 14) -> pd.Series:
        return ta.rsi(data["close"], length=period)

    @staticmethod
    def macd(data: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        return ta.macd(data["close"], fast=fast, slow=slow, signal=signal)

    @staticmethod
    def ema(data: pd.DataFrame, period: int) -> pd.Series:
        return ta.ema(data["close"], length=period)

    @staticmethod
    def vwap(data: pd.DataFrame) -> pd.Series:
        df = data.set_index(pd.to_datetime(data["ts"])) if "ts" in data.columns else data
        return ta.vwap(df["high"], df["low"], df["close"], df["volume"])

    @staticmethod
    def bollinger_bands(data: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.DataFrame:
        return ta.bbands(data["close"], length=period, std=std)

    @staticmethod
    def atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
        return ta.atr(data["high"], data["low"], data["close"], length=period)

    @staticmethod
    def obv(data: pd.DataFrame) -> pd.Series:
        return ta.obv(data["close"], data["volume"])


class Patterns:
    @staticmethod
    def detect(data: pd.DataFrame, patterns: list[str]) -> list[dict]:
        from technical.patterns.detector import detect_patterns
        return detect_patterns(data, patterns)

    @staticmethod
    def support_resistance(data: pd.DataFrame) -> list[dict]:
        from technical.patterns.levels import find_support_resistance
        return find_support_resistance(data)

    @staticmethod
    def trend(data: pd.DataFrame, window: int = 20):
        from technical.trend import analyze_trend
        return analyze_trend(data, window=window)

    @staticmethod
    def detect_candlestick(data: pd.DataFrame, pattern: str) -> dict | None:
        """Detect a candlestick pattern. Returns {"confidence": float, "direction": str} or None."""
        from technical.patterns.candlestick import detect_candlestick
        return detect_candlestick(data, pattern)


def get_indicator_by_name(name: str):
    """Return indicator function by name. Passthrough to technical.indicators.registry."""
    from technical.indicators.registry import get_indicator
    return get_indicator(name)
