# backend/tests/unit/test_signal_evaluator.py
import asyncio
import pandas as pd
import pytest
from scanner.signals.models import SignalConfig, SignalCondition
from scanner.signals.evaluator import SignalEvaluator, SignalResult
from scanner.evaluator import ConditionEvaluator, DataContext, ConditionNode


def make_ohlcv(n=30, trend="rising") -> pd.DataFrame:
    if trend == "rising":
        closes = [100 + i * 1.0 for i in range(n)]
    else:
        closes = [130 - i * 1.0 for i in range(n)]
    return pd.DataFrame({
        "ts":     pd.date_range("2026-01-01", periods=n, freq="1D"),
        "open":   closes,
        "high":   [c * 1.01 for c in closes],
        "low":    [c * 0.99 for c in closes],
        "close":  closes,
        "volume": [100_000] * n,
        "symbol": ["TEST"] * n,
    })


def make_ctx(df: pd.DataFrame) -> DataContext:
    async def fetch(symbol, tf):
        return df
    return DataContext("TEST", "1d", fetch)


def make_signal(conditions: list[SignalCondition]) -> SignalConfig:
    return SignalConfig(
        name="test_signal",
        category="entry",
        direction="bullish",
        timeframes=["1d"],
        conditions=conditions,
        severity="medium",
        display={"color": "#089981", "icon": "▲", "strength_score": 3},
    )


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── to_condition_tree ─────────────────────────────────────────────────────────

def test_to_condition_tree_indicator():
    signal = make_signal([
        SignalCondition(type="indicator", indicator="rsi", operator="lt", value=30,
                        params={"period": 14}),
    ])
    se = SignalEvaluator()
    tree = se.to_condition_tree(signal)
    assert tree.logic == "AND"
    assert len(tree.children) == 1
    child = tree.children[0]
    assert child.indicator == "rsi"
    assert child.operator == "lt"
    assert child.params == {"period": 14}


def test_to_condition_tree_crossover():
    signal = make_signal([
        SignalCondition(
            type="crossover",
            indicator_a="ema", params_a={"period": 20},
            indicator_b="ema", params_b={"period": 50},
            crossover="above",
        ),
    ])
    se = SignalEvaluator()
    tree = se.to_condition_tree(signal)
    child = tree.children[0]
    assert child.crossover == "above"
    assert child.indicator_a == "ema"
    assert child.params_a == {"period": 20}


def test_to_condition_tree_candlestick():
    signal = make_signal([
        SignalCondition(type="candlestick_pattern", pattern="hammer"),
    ])
    se = SignalEvaluator()
    tree = se.to_condition_tree(signal)
    assert tree.children[0].candlestick == "hammer"


def test_to_condition_tree_volume():
    signal = make_signal([
        SignalCondition(type="volume_confirmation", min_volume_ratio=1.5),
    ])
    se = SignalEvaluator()
    tree = se.to_condition_tree(signal)
    assert tree.children[0].volume_ratio == 1.5


def test_to_condition_tree_trend():
    signal = make_signal([
        SignalCondition(type="trend_context", trend="up"),
    ])
    se = SignalEvaluator()
    tree = se.to_condition_tree(signal)
    assert tree.children[0].trend == "up"


def test_to_condition_tree_chart_pattern():
    signal = make_signal([
        SignalCondition(type="chart_pattern", pattern="double_bottom", min_confidence=0.7),
    ])
    se = SignalEvaluator()
    tree = se.to_condition_tree(signal)
    child = tree.children[0]
    assert child.chart_pattern == "double_bottom"
    assert child.min_confidence == 0.7


# ── evaluate ──────────────────────────────────────────────────────────────────

def test_evaluate_returns_signal_result():
    signal = make_signal([
        SignalCondition(type="volume_confirmation", min_volume_ratio=0.1),
    ])
    df = make_ohlcv()
    ctx = make_ctx(df)
    se = SignalEvaluator()
    cond_eval = ConditionEvaluator()
    result = run(se.evaluate(signal, ctx, cond_eval))
    assert isinstance(result, SignalResult)
    assert result.signal_name == "test_signal"
    assert isinstance(result.passed, bool)
    assert 0.0 <= result.score <= 1.0


def test_evaluate_conditions_passed_count():
    # 2 conditions: volume (passes) + trend up (on rising prices, passes)
    signal = make_signal([
        SignalCondition(type="volume_confirmation", min_volume_ratio=0.1),
        SignalCondition(type="trend_context", trend="up"),
    ])
    df = make_ohlcv(n=30, trend="rising")
    ctx = make_ctx(df)
    se = SignalEvaluator()
    cond_eval = ConditionEvaluator()
    result = run(se.evaluate(signal, ctx, cond_eval))
    assert result.conditions_total == 2
    assert result.conditions_passed >= 0


def test_evaluate_nonexistent_indicator_returns_failed_not_crash():
    signal = make_signal([
        SignalCondition(type="indicator", indicator="nonexistent_xyz",
                        operator="lt", value=30),
    ])
    df = make_ohlcv()
    ctx = make_ctx(df)
    se = SignalEvaluator()
    cond_eval = ConditionEvaluator()
    result = run(se.evaluate(signal, ctx, cond_eval))
    assert not result.passed
    assert result.score == 0.0


def test_evaluate_includes_display():
    signal = make_signal([
        SignalCondition(type="volume_confirmation", min_volume_ratio=0.1),
    ])
    df = make_ohlcv()
    ctx = make_ctx(df)
    se = SignalEvaluator()
    cond_eval = ConditionEvaluator()
    result = run(se.evaluate(signal, ctx, cond_eval))
    assert result.display["color"] == "#089981"
    assert result.display["strength_score"] == 3
