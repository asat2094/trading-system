from fastapi import APIRouter, Depends, Query
from datetime import datetime
import asyncio
import time
from core.auth.middleware import get_current_user
from core.auth.provider import User
from core.sdk import MarketData

router = APIRouter(prefix="/technical", tags=["technical"])

# ---------------------------------------------------------------------------
# Symbol cache — built once on startup, refreshed every 5 minutes.
# QuestDB uses LATEST ON (partition index) instead of SELECT DISTINCT —
# that query scans all 280M rows; LATEST ON resolves in O(num_symbols).
# ---------------------------------------------------------------------------
_symbol_cache: list[str] = []
_cache_ts: float = 0.0
_CACHE_TTL = 300  # seconds
_build_lock = asyncio.Lock()


async def _build_symbol_cache() -> list[str]:
    from core.db import AsyncSessionLocal
    from sqlalchemy import text

    # All symbols — stocks + indices — now live in postgres.
    # Index symbols (NSE_/BSE_) were seeded into stocks table once.
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT symbol FROM stocks ORDER BY symbol"))
        return [r[0] for r in result.fetchall()]


async def warm_symbol_cache() -> None:
    """Call once at startup to pre-populate cache before users search."""
    global _symbol_cache, _cache_ts
    async with _build_lock:
        _symbol_cache = await _build_symbol_cache()
        _cache_ts = time.monotonic()


async def _get_symbols() -> list[str]:
    global _symbol_cache, _cache_ts
    if _symbol_cache and (time.monotonic() - _cache_ts) < _CACHE_TTL:
        return _symbol_cache
    async with _build_lock:
        # Re-check inside lock — another coroutine may have built it
        if _symbol_cache and (time.monotonic() - _cache_ts) < _CACHE_TTL:
            return _symbol_cache
        _symbol_cache = await _build_symbol_cache()
        _cache_ts = time.monotonic()
    return _symbol_cache


@router.get("/symbols")
async def list_symbols(
    q: str = Query("", description="Search prefix/substring"),
    limit: int = Query(50, le=200),
    user: User = Depends(get_current_user),
):
    """Return symbols matching q (case-insensitive substring). Served from in-memory cache."""
    all_syms = await _get_symbols()
    if q:
        q_up = q.strip().upper()
        matched = [s for s in all_syms if q_up in s.upper()]
    else:
        matched = all_syms
    return {"symbols": matched[:limit]}



@router.get("/candles")
async def get_candles(
    symbol: str = Query(..., description="Full symbol e.g. NSE:NIFTY 50, BSE:SENSEX, NSE:RELIANCE"),
    tf: str = Query("15min", pattern="^(1min|3min|5min|15min|30min|1h|4h|1d|1w|1M)$"),
    from_dt: datetime = Query(...),
    to_dt: datetime = Query(...),
    user: User = Depends(get_current_user),
):
    """Live OHLCV for charts. Upstox → Kite MCP fallback. Does not touch QuestDB."""
    md = MarketData()
    df = await md.live_ohlcv(symbol, tf, from_dt, to_dt)
    return {"symbol": symbol, "tf": tf, "rows": df.to_dict(orient="records")}


@router.get("/ohlcv/{symbol}")
async def get_ohlcv(
    symbol: str,
    tf: str = Query("1d", pattern="^(1min|3min|5min|15min|30min|1h|4h|1d|1w|1M)$"),
    from_dt: datetime = Query(...),
    to_dt: datetime = Query(...),
    user: User = Depends(get_current_user),
):
    """Historical OHLCV from QuestDB/Parquet. For backtesting only."""
    md = MarketData()
    df = await md.ohlcv(symbol, tf, from_dt, to_dt)
    return {"symbol": symbol, "tf": tf, "rows": df.to_dict(orient="records")}


@router.get("/indicators/{symbol}")
async def get_indicators(
    symbol: str,
    tf: str = Query("1d"),
    indicators: list[str] = Query(["rsi", "macd"]),
    user: User = Depends(get_current_user),
):
    from datetime import timedelta
    md = MarketData()
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=200)
    df = await md.ohlcv(symbol, tf, from_dt, to_dt)
    result = {}
    for name in indicators:
        try:
            from technical.indicators.registry import get_indicator
            fn = get_indicator(name)
            val = fn(df)
            result[name] = float(val.iloc[-1]) if val is not None and len(val) > 0 else None
        except Exception:
            result[name] = None
    return {"symbol": symbol, "tf": tf, "indicators": result}


@router.get("/trend/{symbol}")
async def get_trend(
    symbol: str,
    tf: str = Query("1min"),
    window: int = Query(20),
    user: User = Depends(get_current_user),
):
    from datetime import timedelta
    from technical.trend import analyze_trend
    import dataclasses
    md = MarketData()
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(hours=8)
    df = await md.ohlcv(symbol, tf, from_dt, to_dt)
    result = analyze_trend(df, window=window)
    return dataclasses.asdict(result)
