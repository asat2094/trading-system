# backend/scanner/signals/evaluator.py
"""
SignalEvaluator: converts a SignalConfig YAML definition to a ConditionNode tree
and evaluates it using the ConditionEvaluator.
"""
from __future__ import annotations
from dataclasses import dataclass
from scanner.signals.models import SignalConfig
from scanner.evaluator import ConditionNode, ConditionEvaluator, DataContext, ConditionResult


@dataclass
class SignalResult:
    signal_name: str
    passed: bool
    score: float
    conditions_passed: int
    conditions_total: int
    details: dict
    display: dict


class SignalEvaluator:
    """Converts a SignalConfig to a ConditionNode tree and evaluates it."""

    def to_condition_tree(self, signal: SignalConfig) -> ConditionNode:
        """Map YAML condition types to ConditionNode leaf types."""
        children: list[ConditionNode] = []
        for cond in signal.conditions:
            if cond.type == "indicator":
                children.append(ConditionNode(
                    indicator=cond.indicator,
                    operator=cond.operator,
                    value=cond.value,
                    params=cond.params,
                    timeframe=cond.timeframe,
                ))
            elif cond.type == "crossover":
                children.append(ConditionNode(
                    crossover=cond.crossover,
                    indicator_a=cond.indicator_a,
                    indicator_b=cond.indicator_b,
                    params_a=cond.params_a,
                    params_b=cond.params_b,
                    timeframe=cond.timeframe,
                ))
            elif cond.type == "candlestick_pattern":
                children.append(ConditionNode(
                    candlestick=cond.pattern,
                    timeframe=cond.timeframe,
                ))
            elif cond.type == "chart_pattern":
                children.append(ConditionNode(
                    chart_pattern=cond.pattern,
                    min_confidence=cond.min_confidence or 0.5,
                    timeframe=cond.timeframe,
                ))
            elif cond.type == "volume_confirmation":
                children.append(ConditionNode(
                    volume_ratio=cond.min_volume_ratio or 1.5,
                    timeframe=cond.timeframe,
                ))
            elif cond.type == "trend_context":
                children.append(ConditionNode(
                    trend=cond.trend,
                    timeframe=cond.timeframe,
                ))
            elif cond.type == "custom_activity":
                # Reserved for future quant model integration — skip.
                pass
        return ConditionNode(logic="AND", children=children)

    async def evaluate(
        self,
        signal: SignalConfig,
        ctx: DataContext,
        evaluator: ConditionEvaluator,
    ) -> SignalResult:
        tree = self.to_condition_tree(signal)
        result: ConditionResult = await evaluator.evaluate(tree, ctx)
        child_details = result.details.get("children", [])
        conditions_passed = sum(1 for c in child_details if c.get("passed", False))
        return SignalResult(
            signal_name=signal.name,
            passed=result.passed,
            score=result.score,
            conditions_passed=conditions_passed,
            conditions_total=len(signal.conditions),
            details=result.details,
            display=signal.display,
        )
