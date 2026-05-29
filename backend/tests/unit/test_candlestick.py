# backend/tests/unit/test_candlestick.py
import pandas as pd
import pytest
from technical.patterns.candlestick import detect_candlestick


def make_bar(o, h, l, c, v=100_000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def df_from_bars(*bars):
    rows = list(bars)
    df = pd.DataFrame(rows)
    df["ts"] = pd.date_range("2026-01-01", periods=len(rows), freq="1D")
    df["symbol"] = "TEST"
    return df


# ── bearish_engulfing ─────────────────────────────────────────────────────────

def test_bearish_engulfing_detected():
    # bar1: green (100→105), bar2: red (106→99) — engulfs bar1 body
    df = df_from_bars(
        make_bar(100, 106, 99, 105),   # bar1 green: body 100–105
        make_bar(106, 107, 98, 99),    # bar2 red:   body 99–106, engulfs
    )
    result = detect_candlestick(df, "bearish_engulfing")
    assert result is not None
    assert result["confidence"] > 0
    assert result["direction"] == "bearish"


def test_bearish_engulfing_not_detected():
    # bar1 red, bar2 green — wrong direction
    df = df_from_bars(
        make_bar(105, 107, 99, 100),
        make_bar(99, 106, 98, 104),
    )
    result = detect_candlestick(df, "bearish_engulfing")
    assert result is None


# ── bullish_engulfing ─────────────────────────────────────────────────────────

def test_bullish_engulfing_detected():
    # bar1: red (105→100), bar2: green (99→107) — engulfs
    df = df_from_bars(
        make_bar(105, 106, 99, 100),
        make_bar(99, 108, 98, 107),
    )
    result = detect_candlestick(df, "bullish_engulfing")
    assert result is not None
    assert result["direction"] == "bullish"


def test_bullish_engulfing_not_detected():
    # bar1 green, bar2 red — wrong direction
    df = df_from_bars(
        make_bar(100, 106, 99, 105),
        make_bar(106, 107, 98, 100),
    )
    result = detect_candlestick(df, "bullish_engulfing")
    assert result is None


# ── hammer ────────────────────────────────────────────────────────────────────

def test_hammer_detected():
    # open=100, close=98, high=100, low=90 → body=2, lower_shadow=8, upper=0
    df = df_from_bars(make_bar(100, 100, 90, 98))
    result = detect_candlestick(df, "hammer")
    assert result is not None
    assert result["direction"] == "bullish"


def test_hammer_not_detected_small_shadow():
    # body: 98–100, lower shadow: 98–97 (1, not ≥ 2x body)
    df = df_from_bars(make_bar(100, 101, 97, 98))
    result = detect_candlestick(df, "hammer")
    assert result is None


# ── shooting_star ─────────────────────────────────────────────────────────────

def test_shooting_star_detected():
    # open=100, close=102, high=110, low=99
    # upper_shadow = 110-102 = 8, body=2, lower = 100-99=1 <= 0.1*2? No, 1 > 0.2
    # Need: lower <= 0.1*body. body=2, lower must be <= 0.2
    # open=100, close=102, high=110, low=99.8 → lower=100-99.8=0.2 = exactly 0.1*2
    df = df_from_bars(make_bar(100, 110, 99.8, 102))
    result = detect_candlestick(df, "shooting_star")
    assert result is not None
    assert result["direction"] == "bearish"


def test_shooting_star_not_detected():
    df = df_from_bars(make_bar(100, 101, 97, 98))  # large lower shadow, not upper
    result = detect_candlestick(df, "shooting_star")
    assert result is None


# ── doji ──────────────────────────────────────────────────────────────────────

def test_doji_detected():
    # open=100, close=100.1, high=105, low=95 → body=0.1, range=10, body_pct=0.01 < 0.1
    df = df_from_bars(make_bar(100, 105, 95, 100.1))
    result = detect_candlestick(df, "doji")
    assert result is not None


def test_doji_not_detected():
    # Large body relative to range
    df = df_from_bars(make_bar(100, 105, 99, 104))  # body=4, range=6, body_pct=0.67
    result = detect_candlestick(df, "doji")
    assert result is None


# ── morning_star ──────────────────────────────────────────────────────────────

def test_morning_star_detected():
    # bar1: large bearish (110→100), bar2: small body (101→99), bar3: large bullish (100→108)
    df = df_from_bars(
        make_bar(110, 111, 99, 100),   # bar1: large bearish, body=10
        make_bar(101, 102, 98, 99),    # bar2: small body, body=2
        make_bar(100, 109, 99, 108),   # bar3: large bullish, body=8
    )
    result = detect_candlestick(df, "morning_star")
    assert result is not None
    assert result["direction"] == "bullish"


def test_morning_star_not_detected():
    # All green bars
    df = df_from_bars(
        make_bar(100, 105, 99, 104),
        make_bar(104, 108, 103, 107),
        make_bar(107, 112, 106, 111),
    )
    result = detect_candlestick(df, "morning_star")
    assert result is None


# ── evening_star ──────────────────────────────────────────────────────────────

def test_evening_star_detected():
    # bar1: large bullish (100→110), bar2: small body (111→109), bar3: large bearish (108→101)
    df = df_from_bars(
        make_bar(100, 111, 99, 110),   # bar1: large bullish, body=10
        make_bar(111, 113, 108, 109),  # bar2: small body, body=2
        make_bar(108, 109, 100, 101),  # bar3: large bearish, body=7
    )
    result = detect_candlestick(df, "evening_star")
    assert result is not None
    assert result["direction"] == "bearish"


def test_evening_star_not_detected():
    df = df_from_bars(
        make_bar(100, 105, 99, 104),
        make_bar(104, 108, 103, 107),
        make_bar(107, 112, 106, 111),
    )
    result = detect_candlestick(df, "evening_star")
    assert result is None


# ── unknown pattern ───────────────────────────────────────────────────────────

def test_unknown_pattern_raises():
    df = df_from_bars(make_bar(100, 105, 95, 102))
    with pytest.raises(ValueError, match="Unknown candlestick pattern"):
        detect_candlestick(df, "nonexistent_pattern")


# ── gravestone_doji ───────────────────────────────────────────────────────────

def test_gravestone_doji_detected():
    # Long upper wick, tiny body at low, no lower wick
    # open=99, close=100, high=120, low=98 → body=1/22≈0.045, upper=20/22≈0.91, lower=2/22≈0.09
    df = df_from_bars(make_bar(99, 120, 98, 100))
    result = detect_candlestick(df, "gravestone_doji")
    assert result is not None
    assert result["direction"] == "bearish"
    assert result["confidence"] >= 0.6


def test_gravestone_doji_high_confidence():
    # Perfect gravestone: open=close=low, all wick above
    df = df_from_bars(make_bar(100, 130, 100, 100))
    result = detect_candlestick(df, "gravestone_doji")
    assert result is not None
    assert result["confidence"] > 0.9


def test_gravestone_doji_not_detected_large_body():
    # Large body — fails body < 0.1 check
    df = df_from_bars(make_bar(100, 130, 99, 120))
    result = detect_candlestick(df, "gravestone_doji")
    assert result is None


def test_gravestone_doji_not_detected_lower_wick():
    # Has significant lower wick — fails lower < 0.1 check
    df = df_from_bars(make_bar(100, 130, 90, 101))
    result = detect_candlestick(df, "gravestone_doji")
    assert result is None


def test_gravestone_doji_not_detected_small_upper_wick():
    # Small upper wick — fails upper > 0.6 check
    # body=99→100=1, range=103-98=5, upper=103-100=3/5=0.6 (just at boundary)
    df = df_from_bars(make_bar(99, 103, 98, 100))
    result = detect_candlestick(df, "gravestone_doji")
    # upper_wick/range = 3/5 = 0.6, exactly at boundary — borderline, assert is None for strict >0.6
    assert result is None


def test_gravestone_doji_not_detected_flat_candle():
    # Zero range — should not crash, should return None
    df = df_from_bars(make_bar(100, 100, 100, 100))
    result = detect_candlestick(df, "gravestone_doji")
    assert result is None
