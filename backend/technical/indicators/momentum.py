import pandas as pd
import pandas_ta as ta

def rsi(data: pd.DataFrame, period: int = 14) -> pd.Series:
    return ta.rsi(data["close"], length=period)

def macd(data: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    return ta.macd(data["close"], fast=fast, slow=slow, signal=signal)

def stochastic(data: pd.DataFrame, k: int = 14, d: int = 3) -> pd.DataFrame:
    return ta.stoch(data["high"], data["low"], data["close"], k=k, d=d)

def cci(data: pd.DataFrame, period: int = 20) -> pd.Series:
    return ta.cci(data["high"], data["low"], data["close"], length=period)

def williams_r(data: pd.DataFrame, period: int = 14) -> pd.Series:
    return ta.willr(data["high"], data["low"], data["close"], length=period)
