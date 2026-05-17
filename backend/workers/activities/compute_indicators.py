"""Compute technical indicators for all symbols and cache results in Redis."""
import asyncio
import json
from datetime import datetime, timedelta
from temporalio import activity
from core.logging import get_logger
from core.sdk import MarketData, Indicators
from core.cache import get_redis, cache_key

log = get_logger(__name__)

_DEFAULT_INDICATORS = ["rsi", "macd", "ema", "vwap", "atr"]
_DEFAULT_TIMEFRAMES = ["1d"]
_CACHE_TTL = 3600  # 1 hour


@activity.defn(name="compute_indicators")
async def activity_fn(
    indicators: list[str] | None = None,
    timeframes: list[str] | None = None,
) -> dict:
    if indicators is None:
        indicators = _DEFAULT_INDICATORS
    if timeframes is None:
        timeframes = _DEFAULT_TIMEFRAMES

    md = MarketData()
    symbols = await md.universe()
    if not symbols:
        log.warning("compute_indicators_no_symbols")
        return {"computed": 0}

    redis = get_redis()
    computed = 0
    failed = 0
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=200)

    for sym in symbols:
        for tf in timeframes:
            try:
                df = await md.ohlcv(sym, tf, from_dt.isoformat(), to_dt.isoformat())
            except Exception as exc:
                log.warning("indicator_ohlcv_failed", symbol=sym, tf=tf, error=str(exc))
                failed += 1
                continue

            if df is None or df.empty:
                continue

            result: dict = {}
            for ind_name in indicators:
                try:
                    # Map indicator names to SDK methods
                    ind_map = {
                        "rsi": lambda d: Indicators.rsi(d),
                        "macd": lambda d: Indicators.macd(d),
                        "ema": lambda d: Indicators.ema(d),
                        "vwap": lambda d: Indicators.vwap(d),
                        "atr": lambda d: Indicators.atr(d),
                        "obv": lambda d: Indicators.obv(d),
                        "bollinger_bands": lambda d: Indicators.bollinger_bands(d),
                    }
                    fn = ind_map.get(ind_name)
                    if fn is None:
                        continue
                    val = fn(df)
                    if val is not None and len(val) > 0:
                        last = val.dropna()
                        result[ind_name] = float(last.iloc[-1]) if not last.empty else None
                except Exception as exc:
                    log.warning("indicator_compute_failed",
                                symbol=sym, indicator=ind_name, error=str(exc))

            key = cache_key("indicators", sym, tf)
            await redis.setex(key, _CACHE_TTL, json.dumps(result))
            computed += 1

    log.info("compute_indicators_complete",
             symbols=len(symbols), computed=computed, failed=failed)
    return {"computed": computed, "failed": failed}
