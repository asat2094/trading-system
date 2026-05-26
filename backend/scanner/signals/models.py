# backend/scanner/signals/models.py
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


class SignalCondition(BaseModel):
    type: Literal[
        "candlestick_pattern", "chart_pattern", "volume_confirmation",
        "trend_context", "indicator", "crossover", "custom_activity",
    ]
    pattern: str | None = None
    indicator: str | None = None
    operator: str | None = None
    value: float | str | None = None
    params: dict[str, Any] = Field(default_factory=dict)                # indicator-specific kwargs
    min_volume_ratio: float | None = None
    min_confidence: float | None = None        # for chart_pattern
    trend: str | None = None
    timeframe: str | None = None               # per-condition TF override
    # crossover-specific
    indicator_a: str | None = None
    indicator_b: str | None = None
    params_a: dict[str, Any] = Field(default_factory=dict)
    params_b: dict[str, Any] = Field(default_factory=dict)
    crossover: Literal["above", "below"] | None = None               # "above" | "below"


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
