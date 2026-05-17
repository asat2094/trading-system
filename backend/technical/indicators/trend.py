import pandas as pd
import pandas_ta as ta

def ema(data: pd.DataFrame, period: int) -> pd.Series:
    return ta.ema(data["close"], length=period)

def sma(data: pd.DataFrame, period: int) -> pd.Series:
    return ta.sma(data["close"], length=period)

def wma(data: pd.DataFrame, period: int) -> pd.Series:
    return ta.wma(data["close"], length=period)

def supertrend(data: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    return ta.supertrend(data["high"], data["low"], data["close"], length=period, multiplier=multiplier)

def ichimoku(data: pd.DataFrame) -> pd.DataFrame:
    ich, span = ta.ichimoku(data["high"], data["low"], data["close"])
    return ich
