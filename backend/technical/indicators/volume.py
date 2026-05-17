import pandas as pd
import pandas_ta as ta

def obv(data: pd.DataFrame) -> pd.Series:
    return ta.obv(data["close"], data["volume"])

def vwap(data: pd.DataFrame) -> pd.Series:
    df = data.set_index(pd.to_datetime(data["ts"])) if "ts" in data.columns else data
    return ta.vwap(df["high"], df["low"], df["close"], df["volume"])

def chaikin(data: pd.DataFrame, fast: int = 3, slow: int = 10) -> pd.Series:
    return ta.adosc(data["high"], data["low"], data["close"], data["volume"], fast=fast, slow=slow)
