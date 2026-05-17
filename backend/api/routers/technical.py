from fastapi import APIRouter, Depends, Query
from datetime import datetime
from core.auth.middleware import get_current_user
from core.auth.provider import User
from core.sdk import MarketData

router = APIRouter(prefix="/technical", tags=["technical"])


@router.get("/ohlcv/{symbol}")
async def get_ohlcv(
    symbol: str,
    tf: str = Query("1d", pattern="^(1min|1h|1d)$"),
    from_dt: datetime = Query(...),
    to_dt: datetime = Query(...),
    user: User = Depends(get_current_user),
):
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
