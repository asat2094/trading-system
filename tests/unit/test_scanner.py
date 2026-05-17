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
    s.from_source("nse_universe")
    with patch.object(s, "_fetch_symbols", return_value=["A"] * 600):
        with patch.object(s, "_apply_filters", side_effect=lambda syms: syms):
            with patch.object(s, "_compute_results", return_value=pd.DataFrame()) as mock_compute:
                result = s.run(max_symbols=500)
                call_args = mock_compute.call_args
                assert len(call_args[0][0]) <= 500
