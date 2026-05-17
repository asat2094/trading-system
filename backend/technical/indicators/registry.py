from typing import Callable
from core.sdk import Indicators

_REGISTRY: dict[str, Callable] = {
    "rsi":             Indicators.rsi,
    "macd":            Indicators.macd,
    "ema":             Indicators.ema,
    "vwap":            Indicators.vwap,
    "bollinger_bands": Indicators.bollinger_bands,
    "atr":             Indicators.atr,
}

def get_indicator(name: str) -> Callable:
    if name not in _REGISTRY:
        raise KeyError(f"{name!r}: not in indicator registry. Available: {list(_REGISTRY)}")
    return _REGISTRY[name]

def list_indicators() -> list[str]:
    return list(_REGISTRY.keys())

def register_indicator(name: str, fn: Callable) -> None:
    _REGISTRY[name] = fn
