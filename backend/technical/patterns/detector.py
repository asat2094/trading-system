import pandas as pd
from technical.patterns.reversal import (
    detect_double_bottom, detect_double_top, detect_head_and_shoulders,
    detect_triple_top, detect_triple_bottom, PatternResult,
)
from technical.patterns.continuation import (
    detect_bull_flag, detect_triangle, detect_pennant, detect_wedge,
)
from technical.patterns.levels import find_support_resistance

_DETECTORS = {
    "double_bottom":      detect_double_bottom,
    "double_top":         detect_double_top,
    "head_and_shoulders": detect_head_and_shoulders,
    "bull_flag":          detect_bull_flag,
    "triangle":           detect_triangle,
    "pennant":            detect_pennant,
    "wedge":              detect_wedge,
    "triple_top":         detect_triple_top,
    "triple_bottom":      detect_triple_bottom,
}

def detect_patterns(data: pd.DataFrame, patterns: list[str]) -> list[dict]:
    unknown = set(patterns) - set(_DETECTORS)
    if unknown:
        raise ValueError(f"{unknown}: not in pattern registry. Available: {list(_DETECTORS)}")

    results = []
    for name in patterns:
        result: PatternResult | None = _DETECTORS[name](data)
        if result is not None:
            results.append(result.to_dict())
    return results
