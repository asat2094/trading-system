"""Unit tests for FnO snapshot logic."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import date


# --- _nearest_monthly_expiry ---

def test_nearest_monthly_expiry_before_expiry():
    """If today is before last Thursday, return current month's last Thursday."""
    from backend.workers.activities.fetch_fno_snapshot import _nearest_monthly_expiry
    # June 30 2026 is Tuesday; last Thursday of June 2026 is June 25
    result = _nearest_monthly_expiry(date(2026, 6, 1))
    assert result == date(2026, 6, 25)


def test_nearest_monthly_expiry_after_expiry():
    """If today is after last Thursday, return next month."""
    from backend.workers.activities.fetch_fno_snapshot import _nearest_monthly_expiry
    # June 25 2026 passed → return last Thursday of July 2026
    result = _nearest_monthly_expiry(date(2026, 6, 26))
    assert result == date(2026, 7, 30)


def test_nearest_monthly_expiry_december_rolls_to_january():
    """December expiry passed → rolls to January next year."""
    from backend.workers.activities.fetch_fno_snapshot import _nearest_monthly_expiry
    # Last Thursday Dec 2026 is Dec 31; after that rolls to Jan 2027
    result = _nearest_monthly_expiry(date(2027, 1, 2))
    assert result.year == 2027
    assert result.month == 1
    assert result.weekday() == 3  # Thursday


# --- _expiry_prefix ---

def test_expiry_prefix():
    from backend.workers.activities.fetch_fno_snapshot import _expiry_prefix
    assert _expiry_prefix(date(2026, 6, 25)) == "NIFTY26JUN"
    assert _expiry_prefix(date(2026, 12, 31)) == "NIFTY26DEC"


# --- Open-High detection ---

def test_is_oh_true_when_high_equals_open():
    from backend.workers.activities.fetch_fno_snapshot import _is_oh
    assert _is_oh(open_=138.0, high=138.0) is True


def test_is_oh_true_within_one_tick():
    from backend.workers.activities.fetch_fno_snapshot import _is_oh
    assert _is_oh(open_=138.0, high=138.05) is True


def test_is_oh_false_when_high_above_open():
    from backend.workers.activities.fetch_fno_snapshot import _is_oh
    assert _is_oh(open_=138.0, high=140.0) is False


def test_is_oh_hit_true_when_price_at_open():
    from backend.workers.activities.fetch_fno_snapshot import _is_oh_hit
    assert _is_oh_hit(open_=138.0, last_price=138.0) is True


def test_is_oh_hit_false_when_price_below_open():
    from backend.workers.activities.fetch_fno_snapshot import _is_oh_hit
    assert _is_oh_hit(open_=138.0, last_price=120.0) is False


# --- PCR / PCDR / PCD computation ---

def test_pcr_computation():
    """PCR = total PE OI / total CE OI."""
    from backend.workers.activities.fetch_fno_snapshot import _compute_ratios
    result = _compute_ratios(
        ce_oi=1_000_000, pe_oi=1_500_000,
        ce_delta=50_000, pe_delta=100_000,
    )
    assert result["pcr"] == pytest.approx(1.5, rel=1e-3)
    assert result["pcdr"] == pytest.approx(2.0, rel=1e-3)
    assert result["pcd"] == 50_000


def test_pcr_zero_ce_oi_does_not_crash():
    from backend.workers.activities.fetch_fno_snapshot import _compute_ratios
    result = _compute_ratios(ce_oi=0, pe_oi=500_000, ce_delta=0, pe_delta=10_000)
    assert result["pcr"] == 0.0
    assert result["pcdr"] == 0.0


# --- run_fno_snapshot integration (mocked KiteMCP + Redis) ---

def _make_quote(ltp, oi, open_, high):
    return {
        "last_price": ltp, "oi": oi,
        "ohlc": {"open": open_, "high": high, "low": ltp * 0.9, "close": ltp},
    }


def test_run_fno_snapshot_returns_expected_keys():
    """run_fno_snapshot returns all required keys when KiteMCP + Redis are mocked."""
    from backend.workers.activities.fetch_fno_snapshot import run_fno_snapshot

    fake_spot = {"NSE:NIFTY 50": {"last_price": 24700.0}}
    # Build fake quotes for 21 strikes × 2 types
    fake_quotes = {}
    for i in range(-10, 11):
        strike = int(24700 + i * 50)
        for t in ("CE", "PE"):
            key = f"NFO:NIFTY26JUN{strike}{t}"
            fake_quotes[key] = _make_quote(100.0, 1_000_000, 100.0, 100.0)

    mock_redis = MagicMock()
    mock_redis.get.return_value = None  # no baseline yet

    call_count = [0]
    def fake_call_tool(self_ignored, name, arguments):
        call_count[0] += 1
        if name == "get_ltp":
            return fake_spot
        if name == "get_quotes":
            return fake_quotes
        return {}

    with (
        patch(
            "backend.workers.activities.fetch_fno_snapshot._FnoMCPClient.call_tool",
            side_effect=fake_call_tool,
        ),
        patch(
            "backend.workers.activities.fetch_fno_snapshot._FnoMCPClient.__init__",
            return_value=None,
        ),
        patch(
            "backend.workers.activities.fetch_fno_snapshot._FnoMCPClient.close",
            return_value=None,
        ),
        patch("backend.workers.activities.fetch_fno_snapshot._redis", return_value=mock_redis),
    ):
        result = run_fno_snapshot("NIFTY", strikes=10)

    assert result["symbol"] == "NIFTY"
    assert result["spot"] == 24700.0
    assert result["atm_strike"] == 24700
    assert "pcr" in result
    assert "pcdr" in result
    assert "pcd" in result
    assert len(result["strikes"]) == 21
    assert result["strikes"][10]["strike"] == 24700  # ATM is middle
    assert call_count[0] == 2  # exactly 2 MCP calls: get_ltp + get_quotes
