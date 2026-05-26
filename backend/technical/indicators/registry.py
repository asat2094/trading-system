# backend/technical/indicators/registry.py
from typing import Callable
from core.sdk import Indicators
from technical.indicators.momentum import stochastic, cci, williams_r
from technical.indicators.trend import sma, wma, supertrend
from technical.indicators.volume import obv
from technical.indicators.price import price_vs_resistance

_REGISTRY: dict[str, Callable] = {
    "rsi":                  Indicators.rsi,
    "macd":                 Indicators.macd,
    "ema":                  Indicators.ema,
    "vwap":                 Indicators.vwap,
    "bollinger_bands":      Indicators.bollinger_bands,
    "atr":                  Indicators.atr,
    # previously missing
    "sma":                  sma,
    "wma":                  wma,
    "stochastic":           stochastic,
    "cci":                  cci,
    "williams_r":           williams_r,
    "obv":                  obv,
    "supertrend":           supertrend,
    "price_vs_resistance":  price_vs_resistance,
}


def get_indicator(name: str) -> Callable:
    if name not in _REGISTRY:
        raise KeyError(f"{name!r}: not in indicator registry. Available: {list(_REGISTRY)}")
    return _REGISTRY[name]


def list_indicators() -> list[str]:
    return list(_REGISTRY.keys())


def register_indicator(name: str, fn: Callable, overwrite: bool = False) -> None:
    if name in _REGISTRY and not overwrite:
        raise ValueError(f"Indicator {name!r} already registered. Pass overwrite=True to replace.")
    _REGISTRY[name] = fn
