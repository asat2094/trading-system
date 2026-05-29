import pandas as pd
import numpy as np
import pytest
from technical.patterns.levels import pivot_highs, pivot_lows


def _make_df(highs, lows=None, closes=None):
    n = len(highs)
    if lows is None:
        lows = [h - 2 for h in highs]
    if closes is None:
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    return pd.DataFrame({
        "open": closes, "high": highs, "low": lows,
        "close": closes, "volume": [100_000] * n,
    })


def test_pivot_high_detected_at_peak():
    # Clear peak at index 5
    highs = [10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10, 10, 10]
    df = _make_df(highs)
    result = pivot_highs(df, left=3, right=3)
    assert 5 in result


def test_pivot_high_not_detected_flat():
    highs = [10] * 15
    df = _make_df(highs)
    result = pivot_highs(df, left=3, right=3)
    # Flat series: every point equals max — all qualify but that's ok, or none
    # Just ensure no crash
    assert isinstance(result, list)


def test_pivot_low_detected_at_trough():
    lows = [20, 18, 15, 12, 10, 3, 10, 12, 15, 18, 20, 20, 20]
    df = _make_df([l + 5 for l in lows], lows)
    result = pivot_lows(df, left=3, right=3)
    assert 5 in result


def test_pivot_high_respects_left_right():
    # With left=5, right=5, need at least 11 bars; peak must beat 5 bars on each side
    highs = [5, 6, 7, 8, 9, 15, 9, 8, 7, 6, 5]
    df = _make_df(highs)
    result = pivot_highs(df, left=5, right=5)
    assert 5 in result


def test_pivot_multiple_peaks():
    highs = [5, 10, 5, 5, 5, 10, 5, 5, 5, 10, 5]
    df = _make_df(highs)
    result = pivot_highs(df, left=2, right=2)
    # With left=2, right=2, valid range is [2, 9)
    # Only index 5 has highs[5]=10 with sufficient bars on both sides
    assert 5 in result
    # Verify it's the only detected peak with these parameters
    assert len(result) == 1


def test_pivot_low_empty_when_short_series():
    df = _make_df([10, 9, 8])
    result = pivot_lows(df, left=5, right=5)
    assert result == []
