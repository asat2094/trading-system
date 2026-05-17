import pytest
from scanner.signals.loader import load_signals
from scanner.signals.models import SignalConfig

def test_signals_yaml_loads_and_validates():
    signals = load_signals()
    assert len(signals) > 0
    for sig in signals:
        assert isinstance(sig, SignalConfig)
        assert sig.name
        assert sig.category in ("entry", "exit", "alert", "custom")
        assert sig.direction in ("bullish", "bearish", "any")
        assert 1 <= sig.display.get("strength_score", 0) <= 5

def test_invalid_yaml_fails_fast(tmp_path):
    bad_yaml = tmp_path / "signals.yaml"
    bad_yaml.write_text("signals:\n  - name: bad\n    category: INVALID\n")
    with pytest.raises(Exception):
        load_signals(str(bad_yaml))
