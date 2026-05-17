import pandas as pd
import pandas_ta as ta

def bollinger_bands(data: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.DataFrame:
    return ta.bbands(data["close"], length=period, std=std)

def atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    return ta.atr(data["high"], data["low"], data["close"], length=period)

def keltner_channel(data: pd.DataFrame, period: int = 20, scalar: float = 2.0) -> pd.DataFrame:
    return ta.kc(data["high"], data["low"], data["close"], length=period, scalar=scalar)

def donchian(data: pd.DataFrame, lower_length: int = 20, upper_length: int = 20) -> pd.DataFrame:
    return ta.donchian(data["high"], data["low"], lower_length=lower_length, upper_length=upper_length)
