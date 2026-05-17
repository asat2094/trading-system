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


class MarketData:
    async def ohlcv(
        self,
        symbol: str,
        tf: str,
        from_dt: datetime,
        to_dt: datetime,
        adjusted: bool = True,
    ) -> pd.DataFrame:
        table = TF_TABLE.get(tf)
        if table is None:
            raise ValueError(f"Unknown timeframe {tf!r}. Use: {list(TF_TABLE)}")

        # Try QuestDB hot layer first
        df = await asyncio.get_running_loop().run_in_executor(
            None, self._query_questdb, table, symbol, from_dt, to_dt
        )
        if not df.empty:
            return df

        # Transparent fallback to DuckDB + Parquet
        return self._query_parquet(symbol, tf, from_dt, to_dt)

    def _query_questdb(
        self, table: str, symbol: str, from_dt: datetime, to_dt: datetime
    ) -> pd.DataFrame:
        conn = get_questdb_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM {table} WHERE symbol=? AND ts BETWEEN ? AND ? ORDER BY ts",
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
        if filters:
            raise NotImplementedError("universe() filters not yet implemented")
        from sqlalchemy import text
        from core.db import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT symbol FROM stocks ORDER BY symbol"))
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
