import asyncio
import json
from temporalio import activity
from core.logging import get_logger
from core.sdk import MarketData, Indicators
from core.cache import get_redis, cache_key

log = get_logger(__name__)


@activity.defn(name="compute_indicators")
async def activity_fn(
    indicators: list[str] | None = None,
    timeframes: list[str] | None = None,
) -> dict:
    if indicators is None:
        indicators = ["rsi", "macd", "ema"]
    if timeframes is None:
        timeframes = ["1d"]

    from datetime import datetime, timedelta
    md = MarketData()
    symbols = await md.universe()
    redis = get_redis()
    computed = 0

    for sym in symbols:
        for tf in timeframes:
            to_dt = datetime.now()
            from_dt = to_dt - timedelta(days=200)
            df = await md.ohlcv(sym, tf, from_dt, to_dt)
            if df.empty:
                continue

            result = {}
            for ind_name in indicators:
                try:
                    from technical.indicators.registry import get_indicator
                    fn = get_indicator(ind_name.replace("_14", "").replace("_20", ""))
                    val = fn(df)
                    result[ind_name] = float(val.iloc[-1]) if val is not None and len(val) > 0 else None
                except Exception as exc:
                    log.warning("indicator_compute_failed", symbol=sym, indicator=ind_name, error=str(exc))

            key = cache_key("indicators", sym, tf)
            await redis.setex(key, 3600, json.dumps(result))
            computed += 1

    log.info("compute_indicators_complete", symbols=len(symbols), computed=computed)
    return {"computed": computed}
