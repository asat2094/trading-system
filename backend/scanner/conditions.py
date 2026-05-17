# Condition evaluators — implemented in Task 13
import pandas as pd


def rsi_below(threshold: float = 30.0):
    def _check(data: pd.DataFrame) -> bool:
        from technical.indicators.momentum import rsi as compute_rsi
        series = compute_rsi(data)
        return bool(series.dropna().iloc[-1] < threshold) if not series.dropna().empty else False
    return _check


def rsi_above(threshold: float = 70.0):
    def _check(data: pd.DataFrame) -> bool:
        from technical.indicators.momentum import rsi as compute_rsi
        series = compute_rsi(data)
        return bool(series.dropna().iloc[-1] > threshold) if not series.dropna().empty else False
    return _check


def price_above_ema(period: int = 20):
    def _check(data: pd.DataFrame) -> bool:
        from technical.indicators.trend import ema as compute_ema
        ema_series = compute_ema(data, period=period)
        last_close = data["close"].iloc[-1]
        last_ema = ema_series.dropna().iloc[-1] if not ema_series.dropna().empty else last_close
        return bool(last_close > last_ema)
    return _check
