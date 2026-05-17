from typing import Any, Literal
from pydantic import BaseModel, field_validator


class SignalCondition(BaseModel):
    type: Literal[
        "candlestick_pattern", "volume_confirmation",
        "trend_context", "indicator", "custom_activity",
    ]
    pattern: str | None = None
    indicator: str | None = None
    operator: str | None = None
    value: float | str | None = None
    min_volume_ratio: float | None = None
    trend: str | None = None


class SignalDisplay(BaseModel):
    color: str
    icon: str = "●"
    strength_score: int

    @field_validator("strength_score")
    @classmethod
    def score_in_range(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError(f"strength_score must be 1–5, got {v}")
        return v


class SignalConfig(BaseModel):
    name: str
    category: Literal["entry", "exit", "alert", "custom"]
    direction: Literal["bullish", "bearish", "any"]
    timeframes: list[str]
    conditions: list[SignalCondition]
    severity: Literal["low", "medium", "high"]
    display: dict[str, Any]
