# backend/tests/unit/test_condition_evaluator.py
"""Unit tests for ConditionEvaluator. All use synthetic DataFrames — no DB calls."""
import asyncio
import pandas as pd
import pytest
from scanner.evaluator import ConditionNode, ConditionEvaluator, DataContext, ConditionResult


def make_ohlcv(closes: list, volumes: list = None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "ts":     pd.date_range("2026-01-01", periods=n, freq="1D"),
        "open":   closes,
        "high":   [c * 1.01 for c in closes],
        "low":    [c * 0.99 for c in closes],
        "close":  closes,
        "volume": volumes or [100_000] * n,
        "symbol": ["TEST"] * n,
    })


def make_ctx(df: pd.DataFrame, default_tf: str = "1d") -> DataContext:
    async def fetch(symbol: str, tf: str) -> pd.DataFrame:
        return df
    return DataContext(symbol="TEST", default_tf=default_tf, fetch_fn=fetch)


def run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def eval_node(node: ConditionNode, df: pd.DataFrame) -> ConditionResult:
    ctx = make_ctx(df)
    evaluator = ConditionEvaluator()
    return run(evaluator.evaluate(node, ctx))


# ── indicator: rsi lt ─────────────────────────────────────────────────────────

def test_rsi_lt_passes_when_low():
    # Falling prices → low RSI
    closes = [100 - i * 2 for i in range(30)]
    df = make_ohlcv(closes)
    node = ConditionNode(indicator="rsi", operator="lt", value=50.0, params={"period": 14})
    result = eval_node(node, df)
    assert result.passed
    assert result.score > 0.0
    assert "rsi_value" in result.details
    assert result.node_type == "indicator"


def test_rsi_lt_fails_when_high():
    # Rising prices → high RSI
    closes = [100 + i * 2 for i in range(30)]
    df = make_ohlcv(closes)
    node = ConditionNode(indicator="rsi", operator="lt", value=30.0, params={"period": 14})
    result = eval_node(node, df)
    assert not result.passed
    assert result.score == 0.0


def test_rsi_lt_score_stronger_when_further_below():
    closes_low = [100 - i * 3 for i in range(30)]   # lower RSI
    closes_mid = [100 - i * 1 for i in range(30)]   # higher RSI
    df_low = make_ohlcv(closes_low)
    df_mid = make_ohlcv(closes_mid)
    node = ConditionNode(indicator="rsi", operator="lt", value=50.0, params={"period": 14})
    r_low = eval_node(node, df_low)
    r_mid = eval_node(node, df_mid)
    if r_low.passed and r_mid.passed:
        assert r_low.score >= r_mid.score


# ── indicator: bad params ─────────────────────────────────────────────────────

def test_indicator_bad_params_returns_error_not_crash():
    closes = [100 + i for i in range(30)]
    df = make_ohlcv(closes)
    node = ConditionNode(indicator="rsi", operator="lt", value=30.0,
                         params={"nonexistent_kwarg": 99})
    result = eval_node(node, df)
    assert not result.passed
    assert "error" in result.details


# ── crossover ─────────────────────────────────────────────────────────────────

def test_ema_crossover_returns_condition_result():
    closes = [100 + i * 0.5 for i in range(60)]
    df = make_ohlcv(closes)
    node = ConditionNode(
        crossover="above",
        indicator_a="ema", params_a={"period": 10},
        indicator_b="ema", params_b={"period": 20},
    )
    result = eval_node(node, df)
    assert isinstance(result, ConditionResult)
    assert result.node_type == "crossover"
    assert 0.0 <= result.score <= 1.0


def test_crossover_with_unknown_indicator_returns_error():
    closes = [100.0] * 30
    df = make_ohlcv(closes)
    node = ConditionNode(
        crossover="above",
        indicator_a="nonexistent_xyz", params_a={},
        indicator_b="ema", params_b={"period": 20},
    )
    result = eval_node(node, df)
    assert not result.passed
    assert "error" in result.details


# ── volume ────────────────────────────────────────────────────────────────────

def test_volume_passes_on_spike():
    volumes = [100_000] * 20 + [300_000]
    closes = [100.0] * 21
    df = make_ohlcv(closes, volumes)
    node = ConditionNode(volume_ratio=1.5, volume_period=20)
    result = eval_node(node, df)
    assert result.passed
    assert result.score > 0.0
    assert result.details["volume_ratio"] == pytest.approx(3.0, rel=0.1)


def test_volume_score_near_zero_at_exact_threshold():
    volumes = [100_000] * 20 + [150_000]
    closes = [100.0] * 21
    df = make_ohlcv(closes, volumes)
    node = ConditionNode(volume_ratio=1.5, volume_period=20)
    result = eval_node(node, df)
    assert result.passed
    assert result.score == pytest.approx(0.0, abs=0.05)


def test_volume_fails_below_threshold():
    volumes = [100_000] * 21
    closes = [100.0] * 21
    df = make_ohlcv(closes, volumes)
    node = ConditionNode(volume_ratio=2.0, volume_period=20)
    result = eval_node(node, df)
    assert not result.passed
    assert result.score == 0.0


# ── AND composite ─────────────────────────────────────────────────────────────

def test_and_passes_when_all_children_pass():
    closes = [100.0] * 30
    df = make_ohlcv(closes)
    node = ConditionNode(logic="AND", children=[
        ConditionNode(volume_ratio=0.1, volume_period=20),
        ConditionNode(volume_ratio=0.05, volume_period=20),
    ])
    result = eval_node(node, df)
    assert result.passed
    assert result.node_type == "AND"


def test_and_fails_when_any_child_fails():
    closes = [100 + i * 2 for i in range(30)]
    df = make_ohlcv(closes)
    node = ConditionNode(logic="AND", children=[
        ConditionNode(indicator="rsi", operator="lt", value=5.0, params={"period": 14}),  # fails
        ConditionNode(volume_ratio=0.1, volume_period=20),  # passes
    ])
    result = eval_node(node, df)
    assert not result.passed
    assert result.score == 0.0


def test_and_details_include_children_with_passed_field():
    closes = [100.0] * 30
    df = make_ohlcv(closes)
    node = ConditionNode(logic="AND", children=[
        ConditionNode(volume_ratio=0.1, volume_period=20),
    ])
    result = eval_node(node, df)
    children = result.details.get("children", [])
    assert len(children) == 1
    assert "passed" in children[0]
    assert "score" in children[0]
    assert "node_type" in children[0]


# ── OR composite ──────────────────────────────────────────────────────────────

def test_or_passes_when_any_child_passes():
    closes = [100 + i * 2 for i in range(30)]
    df = make_ohlcv(closes)
    node = ConditionNode(logic="OR", children=[
        ConditionNode(indicator="rsi", operator="lt", value=5.0, params={"period": 14}),  # fails
        ConditionNode(volume_ratio=0.1, volume_period=20),   # passes
    ])
    result = eval_node(node, df)
    assert result.passed
    assert result.node_type == "OR"


def test_or_score_is_max_of_passing_children():
    closes = [100.0] * 30
    df = make_ohlcv(closes)
    node = ConditionNode(logic="OR", children=[
        ConditionNode(volume_ratio=0.1, volume_period=20),
        ConditionNode(volume_ratio=0.05, volume_period=20),
    ])
    result = eval_node(node, df)
    assert result.passed
    assert result.score > 0.0


# ── trend ─────────────────────────────────────────────────────────────────────

def test_trend_up_passes_on_rising_prices():
    closes = [100 + i * 1.0 for i in range(30)]
    df = make_ohlcv(closes)
    node = ConditionNode(trend="up", trend_window=20)
    result = eval_node(node, df)
    assert result.passed
    assert "direction" in result.details


def test_trend_down_fails_on_rising_prices():
    closes = [100 + i * 1.0 for i in range(30)]
    df = make_ohlcv(closes)
    node = ConditionNode(trend="down", trend_window=20)
    result = eval_node(node, df)
    assert not result.passed


# ── DataContext cache ─────────────────────────────────────────────────────────

def test_datacontext_fetch_called_once_per_tf():
    call_count = {}
    closes = [100.0] * 30

    async def fetch(symbol: str, tf: str):
        call_count[tf] = call_count.get(tf, 0) + 1
        return make_ohlcv(closes)

    async def run_test():
        ctx = DataContext("TEST", "1d", fetch)
        await ctx.get("1d")
        await ctx.get("1d")
        await ctx.get("1h")
        await ctx.get("1h")

    asyncio.get_event_loop().run_until_complete(run_test())
    assert call_count.get("1d") == 1
    assert call_count.get("1h") == 1


# ── multi-TF ──────────────────────────────────────────────────────────────────

def test_multi_tf_node_fetches_correct_tf():
    fetched_tfs = []
    closes = [100.0] * 30

    async def fetch(symbol: str, tf: str):
        fetched_tfs.append(tf)
        return make_ohlcv(closes)

    async def run_test():
        ctx = DataContext("TEST", "1d", fetch)
        evaluator = ConditionEvaluator()
        node = ConditionNode(
            logic="AND",
            children=[
                ConditionNode(indicator="rsi", operator="lt", value=70.0,
                              params={"period": 14}, timeframe="1h"),
                ConditionNode(volume_ratio=0.1, volume_period=20, timeframe="1d"),
            ]
        )
        await evaluator.evaluate(node, ctx)

    asyncio.get_event_loop().run_until_complete(run_test())
    assert "1h" in fetched_tfs
    assert "1d" in fetched_tfs


# ── ConditionNode.from_dict ───────────────────────────────────────────────────

def test_from_dict_indicator():
    d = {"type": "indicator", "indicator": "rsi", "operator": "lt", "value": 30,
         "params": {"period": 14}}
    node = ConditionNode.from_dict(d)
    assert node.indicator == "rsi"
    assert node.operator == "lt"
    assert node.value == 30
    assert node.params == {"period": 14}


def test_from_dict_crossover():
    d = {"type": "crossover", "crossover": "above",
         "indicator_a": "ema", "params_a": {"period": 20},
         "indicator_b": "ema", "params_b": {"period": 50}}
    node = ConditionNode.from_dict(d)
    assert node.crossover == "above"
    assert node.indicator_a == "ema"
    assert node.params_a == {"period": 20}


def test_from_dict_composite():
    d = {
        "logic": "AND",
        "conditions": [
            {"type": "indicator", "indicator": "rsi", "operator": "lt", "value": 30, "params": {}},
            {"type": "volume", "value": 1.5, "period": 20},
        ]
    }
    node = ConditionNode.from_dict(d)
    assert node.logic == "AND"
    assert len(node.children) == 2
    assert node.children[0].indicator == "rsi"
    assert node.children[1].volume_ratio == 1.5


def test_from_dict_unknown_type_raises():
    with pytest.raises(ValueError, match="Unknown condition type"):
        ConditionNode.from_dict({"type": "mystery"})
