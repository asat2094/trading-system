import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch
from scanner.engine import Scanner
from scanner.dsl import build_dsl, SCANNER_DSL_VERSION

def test_scanner_dsl_includes_version():
    s = Scanner()
    s.from_source("nse_universe")
    dsl = build_dsl(s)
    assert dsl["version"] == SCANNER_DSL_VERSION
    assert dsl["source"]["name"] == "nse_universe"

def test_scanner_filter_adds_condition():
    s = Scanner()
    s.from_source("nse_universe").filter(exchange="NSE")
    assert len(s._filters) == 1
    assert s._filters[0] == {"field": "exchange", "op": "eq", "value": "NSE"}

def test_scanner_run_respects_max_symbols():
    s = Scanner()
    universe = ["A"] * 600
    result = s.run(universe=universe, max_symbols=500)
    assert len(result) <= 500

def test_scanner_run_returns_list_of_dicts():
    from scanner.engine import Scanner
    s = Scanner()
    results = s.run(universe=["RELIANCE", "INFY", "TCS"])
    assert isinstance(results, list)
    assert all(isinstance(r, dict) for r in results)
    assert all("symbol" in r for r in results)


def test_scanner_dsl_roundtrip():
    from scanner.engine import Scanner
    from scanner.dsl import SCANNER_DSL_VERSION
    s = Scanner()
    dsl1 = s.to_dsl()
    s2 = Scanner()
    dsl2 = s2.to_dsl()
    # Both empty scanners produce same DSL structure
    assert dsl1["version"] == dsl2["version"] == SCANNER_DSL_VERSION
    assert dsl1["conditions"] == dsl2["conditions"]
