# backend/tests/integration/test_scanner_api.py
"""
Integration tests for scanner API.
Uses an explicit symbol list to bypass universe fetch (no real DB needed for shape tests).
Requires backend to be importable: PYTHONPATH=. pytest
"""
import pandas as pd
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch


def make_ohlcv(n=50, trend="rising") -> pd.DataFrame:
    closes = [100 + i for i in range(n)] if trend == "rising" else [150 - i for i in range(n)]
    return pd.DataFrame({
        "ts":     pd.date_range("2026-01-01", periods=n, freq="1D"),
        "open":   closes,
        "high":   [c * 1.01 for c in closes],
        "low":    [c * 0.99 for c in closes],
        "close":  closes,
        "volume": [100_000] * n,
        "symbol": ["TEST"] * n,
    })


@pytest.fixture
def mock_ohlcv():
    """Patch MarketData.ohlcv to return synthetic data."""
    async def fake_ohlcv(self, symbol, tf, from_dt, to_dt):
        return make_ohlcv()
    with patch("core.sdk.MarketData.ohlcv", fake_ohlcv):
        yield


@pytest.fixture
def mock_auth():
    """Bypass auth — override FastAPI dependency to return a fake user object."""
    from core.auth.provider import User
    from core.auth.middleware import get_current_user
    from api.main import app

    fake_user = User(username="test")

    async def fake_get_current_user():
        return fake_user

    app.dependency_overrides[get_current_user] = fake_get_current_user
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_scanner_run_response_shape(mock_ohlcv, mock_auth):
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/scanner/run", json={
            "universe": ["RELIANCE", "TCS"],
            "signals": ["rsi_oversold_uptrend"],
            "default_timeframe": "1d",
            "match_mode": "any_signal",
            "max_symbols": 10,
        })
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "symbols" in body
    assert "results" in body
    assert "total_scanned" in body
    assert "matched" in body
    assert "duration_ms" in body
    assert isinstance(body["results"], list)


@pytest.mark.asyncio
async def test_scanner_run_result_item_shape(mock_ohlcv, mock_auth):
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/scanner/run", json={
            "universe": ["RELIANCE"],
            "signals": ["rsi_oversold_uptrend"],
            "default_timeframe": "1d",
            "match_mode": "any_signal",
            "max_symbols": 10,
        })
    body = resp.json()
    for item in body["results"]:
        assert "symbol" in item
        assert "overall_score" in item
        assert "matched_signals" in item
        assert "signal_details" in item
        assert "custom_passed" in item


@pytest.mark.asyncio
async def test_scanner_evaluate_endpoint(mock_ohlcv, mock_auth):
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/scanner/evaluate", json={
            "symbol": "RELIANCE",
            "default_timeframe": "1d",
            "conditions": {
                "logic": "AND",
                "conditions": [
                    {"type": "indicator", "indicator": "rsi", "operator": "lt",
                     "value": 30, "params": {"period": 14}}
                ]
            }
        })
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "symbol" in body
    assert "passed" in body
    assert "score" in body
    assert "details" in body


@pytest.mark.asyncio
async def test_scanner_evaluate_details_include_per_condition(mock_ohlcv, mock_auth):
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/scanner/evaluate", json={
            "symbol": "RELIANCE",
            "default_timeframe": "1d",
            "conditions": {
                "logic": "AND",
                "conditions": [
                    {"type": "volume", "value": 0.1, "period": 20}
                ]
            }
        })
    body = resp.json()
    children = body["details"].get("children", [])
    assert len(children) == 1
    assert "passed" in children[0]
    assert "score" in children[0]
    assert "node_type" in children[0]


@pytest.mark.asyncio
async def test_scanner_run_unknown_signal_doesnt_crash(mock_ohlcv, mock_auth):
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/scanner/run", json={
            "universe": ["RELIANCE"],
            "signals": ["nonexistent_signal_xyz"],
            "default_timeframe": "1d",
            "match_mode": "any_signal",
            "max_symbols": 10,
        })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_scanner_signals_list(mock_auth):
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/scanner/signals")
    assert resp.status_code == 200
    signals = resp.json()
    assert isinstance(signals, list)
    names = [s["name"] for s in signals]
    assert "rsi_oversold_uptrend" in names
    assert "ema_crossover_bullish" in names
