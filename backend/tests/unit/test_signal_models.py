# backend/tests/unit/test_signal_models.py
import pytest
from scanner.signals.models import SignalCondition, SignalConfig


def test_signal_condition_accepts_params():
    sc = SignalCondition(type="indicator", indicator="rsi", operator="lt", value=30,
                        params={"period": 14})
    assert sc.params == {"period": 14}


def test_signal_condition_params_defaults_to_empty():
    sc = SignalCondition(type="indicator", indicator="rsi", operator="lt", value=30)
    assert sc.params == {}


def test_signal_condition_accepts_timeframe():
    sc = SignalCondition(type="indicator", indicator="rsi", operator="lt", value=30,
                        timeframe="1h")
    assert sc.timeframe == "1h"


def test_signal_condition_timeframe_defaults_none():
    sc = SignalCondition(type="indicator", indicator="rsi", operator="lt", value=30)
    assert sc.timeframe is None


def test_signal_condition_accepts_crossover_type():
    sc = SignalCondition(
        type="crossover",
        indicator_a="ema", params_a={"period": 20},
        indicator_b="ema", params_b={"period": 50},
        crossover="above",
    )
    assert sc.type == "crossover"
    assert sc.indicator_a == "ema"
    assert sc.params_a == {"period": 20}
    assert sc.crossover == "above"


def test_signal_condition_accepts_chart_pattern_type():
    sc = SignalCondition(type="chart_pattern", pattern="double_bottom", min_confidence=0.7)
    assert sc.min_confidence == 0.7


def test_signal_condition_min_confidence_defaults_none():
    sc = SignalCondition(type="chart_pattern", pattern="double_bottom")
    assert sc.min_confidence is None


def test_load_signals_yaml_parses_crossover():
    """Verify that the updated signals.yaml loads without errors."""
    from scanner.signals.loader import load_signals
    signals = load_signals()
    names = [s.name for s in signals]
    assert "ema_crossover_bullish" in names
    crossover_signal = next(s for s in signals if s.name == "ema_crossover_bullish")
    assert crossover_signal.conditions[0].type == "crossover"
    assert crossover_signal.conditions[0].crossover == "above"


def test_load_signals_yaml_parses_breakout():
    from scanner.signals.loader import load_signals
    signals = load_signals()
    breakout = next((s for s in signals if s.name == "breakout_high_volume"), None)
    assert breakout is not None
    assert breakout.conditions[0].type == "indicator"
    assert breakout.conditions[0].indicator == "price_vs_resistance"
