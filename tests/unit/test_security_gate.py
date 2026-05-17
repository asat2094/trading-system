import pytest
from workers.security import validate_activity_code, SecurityViolation

SAFE_CODE = """
from temporalio import activity
from core.sdk import MarketData, Indicators

@activity.defn(name="safe_activity")
async def activity_fn():
    md = MarketData()
    df = await md.ohlcv("RELIANCE", "1d", None, None)
    rsi = Indicators.rsi(df)
    return float(rsi.iloc[-1])
"""

UNSAFE_IMPORT = """
from temporalio import activity
import os

@activity.defn(name="unsafe_activity")
async def activity_fn():
    return os.getcwd()
"""

UNSAFE_EXEC = """
from temporalio import activity

@activity.defn(name="exec_activity")
async def activity_fn():
    exec("import os; os.system('evil')")
"""

UNSAFE_GETATTR = """
from temporalio import activity

@activity.defn(name="getattr_activity")
async def activity_fn():
    getattr(__builtins__, "eval")("evil")
"""


def test_safe_code_passes():
    validate_activity_code(SAFE_CODE)


def test_unsafe_import_rejected():
    with pytest.raises(SecurityViolation, match="os"):
        validate_activity_code(UNSAFE_IMPORT)


def test_exec_rejected():
    with pytest.raises(SecurityViolation, match="exec"):
        validate_activity_code(UNSAFE_EXEC)


def test_getattr_rejected():
    with pytest.raises(SecurityViolation, match="getattr"):
        validate_activity_code(UNSAFE_GETATTR)
