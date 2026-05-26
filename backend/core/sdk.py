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
    "1d":    "1D",
    "1w":    "1W",
    "1M":    "1ME",
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
        return resample_ohlcv(df, tf)

    def _query_questdb(
        self, table: str, symbol: str, from_dt: datetime, to_dt: datetime
    ) -> pd.DataFrame:
        conn = get_questdb_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM {table} WHERE symbol=%s AND ts BETWEEN %s AND %s ORDER BY ts",
                    (symbol, from_dt, to_dt),
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
