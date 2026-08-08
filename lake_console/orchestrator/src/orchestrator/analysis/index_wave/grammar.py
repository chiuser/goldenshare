"""Frozen V1 impulse and zigzag hard-rule evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .pivot import PivotConfirmation, PivotType
from .swings import Direction


class GrammarProfileKey(str, Enum):
    IMPULSE_STANDARD_V1 = "IMPULSE_STANDARD_V1"
    CORRECTIVE_ZIGZAG_V1 = "CORRECTIVE_ZIGZAG_V1"


class RuleStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_YET_EVALUABLE = "NOT_YET_EVALUABLE"


class ScenarioStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"


class GenerationStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    rule_key: str
    status: RuleStatus
    reason: str


@dataclass(frozen=True, slots=True)
class GrammarEvaluation:
    grammar_profile_key: GrammarProfileKey
    scenario_type: str
    direction: Direction
    current_phase: str
    confirmed_wave_count: int
    expected_wave_count: int
    status: ScenarioStatus
    hard_evaluations: tuple[RuleEvaluation, ...]
    invalidation_rule_key: str | None
    context_status: str


def _rule(rule_key: str, ready: bool, passes: bool, reason: str) -> RuleEvaluation:
    if not ready:
        return RuleEvaluation(
            rule_key, RuleStatus.NOT_YET_EVALUABLE, "INSUFFICIENT_CONFIRMED_PIVOTS"
        )
    return RuleEvaluation(
        rule_key, RuleStatus.PASS if passes else RuleStatus.FAIL, reason
    )


def _expected_types(direction: Direction, pivot_count: int) -> tuple[PivotType, ...]:
    first = PivotType.LOW if direction is Direction.UP else PivotType.HIGH
    second = PivotType.HIGH if first is PivotType.LOW else PivotType.LOW
    return tuple(first if index % 2 == 0 else second for index in range(pivot_count))


def _direction(pivots: tuple[PivotConfirmation, ...]) -> Direction:
    return Direction.UP if pivots[0].pivot_type is PivotType.LOW else Direction.DOWN


def evaluate_grammar(
    pivots: tuple[PivotConfirmation, ...],
    grammar_profile_key: GrammarProfileKey,
) -> GrammarEvaluation:
    if len(pivots) < 2:
        raise ValueError("a scenario requires at least two confirmed pivots")
    direction = _direction(pivots)
    if grammar_profile_key is GrammarProfileKey.IMPULSE_STANDARD_V1:
        return _evaluate_impulse(pivots, direction)
    if grammar_profile_key is GrammarProfileKey.CORRECTIVE_ZIGZAG_V1:
        return _evaluate_zigzag(pivots, direction)
    raise ValueError(f"unsupported grammar: {grammar_profile_key}")


def _evaluate_impulse(
    pivots: tuple[PivotConfirmation, ...], direction: Direction
) -> GrammarEvaluation:
    if len(pivots) > 6:
        raise ValueError("impulse scenario cannot contain more than W0..W5")
    prices = tuple(pivot.extreme_price for pivot in pivots)
    alternating = tuple(p.pivot_type for p in pivots) == _expected_types(
        direction, len(pivots)
    )
    up = direction is Direction.UP
    rules = [
        _rule(
            "IMPULSE_ALTERNATING_DIRECTION",
            True,
            alternating,
            "PIVOT_TYPES_MATCH" if alternating else "PIVOT_TYPES_DO_NOT_ALTERNATE",
        ),
        _rule(
            "WAVE2_NOT_BEYOND_ORIGIN",
            len(prices) >= 3,
            len(prices) < 3 or (prices[2] > prices[0] if up else prices[2] < prices[0]),
            "WAVE2_WITHIN_ORIGIN"
            if len(prices) < 3
            or (prices[2] > prices[0] if up else prices[2] < prices[0])
            else "WAVE2_BEYOND_ORIGIN",
        ),
        _rule(
            "WAVE3_EXCEEDS_WAVE1",
            len(prices) >= 4,
            len(prices) < 4 or (prices[3] > prices[1] if up else prices[3] < prices[1]),
            "WAVE3_EXCEEDS_WAVE1"
            if len(prices) < 4
            or (prices[3] > prices[1] if up else prices[3] < prices[1])
            else "WAVE3_DOES_NOT_EXCEED_WAVE1",
        ),
        _rule(
            "WAVE4_NO_WAVE1_OVERLAP",
            len(prices) >= 5,
            len(prices) < 5 or (prices[4] > prices[1] if up else prices[4] < prices[1]),
            "WAVE4_CLEAR_OF_WAVE1"
            if len(prices) < 5
            or (prices[4] > prices[1] if up else prices[4] < prices[1])
            else "WAVE4_OVERLAPS_WAVE1",
        ),
        _rule(
            "WAVE5_EXCEEDS_WAVE3",
            len(prices) >= 6,
            len(prices) < 6 or (prices[5] > prices[3] if up else prices[5] < prices[3]),
            "WAVE5_EXCEEDS_WAVE3"
            if len(prices) < 6
            or (prices[5] > prices[3] if up else prices[5] < prices[3])
            else "WAVE5_TRUNCATED",
        ),
    ]
    if len(prices) >= 6:
        wave1 = abs(prices[1] - prices[0])
        wave3 = abs(prices[3] - prices[2])
        wave5 = abs(prices[5] - prices[4])
        wave3_ok = wave3 >= min(wave1, wave5)
    else:
        wave3_ok = True
    rules.append(
        _rule(
            "WAVE3_NOT_SHORTEST",
            len(prices) >= 6,
            wave3_ok,
            "WAVE3_NOT_SHORTEST" if wave3_ok else "WAVE3_IS_SHORTEST",
        )
    )
    return _finish_evaluation(
        grammar_profile_key=GrammarProfileKey.IMPULSE_STANDARD_V1,
        scenario_type="IMPULSE_STANDARD",
        direction=direction,
        current_phase=f"W{len(pivots) - 1}",
        expected_wave_count=5,
        rules=tuple(rules),
        context_status="LOCAL_STRUCTURE_ONLY",
    )


def _evaluate_zigzag(
    pivots: tuple[PivotConfirmation, ...], direction: Direction
) -> GrammarEvaluation:
    if len(pivots) > 4:
        raise ValueError("zigzag scenario cannot contain more than C0,A,B,C")
    prices = tuple(pivot.extreme_price for pivot in pivots)
    alternating = tuple(p.pivot_type for p in pivots) == _expected_types(
        direction, len(pivots)
    )
    up = direction is Direction.UP
    rules = (
        _rule(
            "ZIGZAG_ALTERNATING_DIRECTION",
            True,
            alternating,
            "PIVOT_TYPES_MATCH" if alternating else "PIVOT_TYPES_DO_NOT_ALTERNATE",
        ),
        _rule(
            "B_NOT_BEYOND_ORIGIN",
            len(prices) >= 3,
            len(prices) < 3 or (prices[2] > prices[0] if up else prices[2] < prices[0]),
            "B_WITHIN_ORIGIN"
            if len(prices) < 3
            or (prices[2] > prices[0] if up else prices[2] < prices[0])
            else "B_BEYOND_ORIGIN",
        ),
        _rule(
            "C_EXCEEDS_A",
            len(prices) >= 4,
            len(prices) < 4 or (prices[3] > prices[1] if up else prices[3] < prices[1]),
            "C_EXCEEDS_A"
            if len(prices) < 4
            or (prices[3] > prices[1] if up else prices[3] < prices[1])
            else "C_TRUNCATED",
        ),
    )
    phase_names = ("C0", "A", "B", "C")
    return _finish_evaluation(
        grammar_profile_key=GrammarProfileKey.CORRECTIVE_ZIGZAG_V1,
        scenario_type="CORRECTIVE_ZIGZAG",
        direction=direction,
        current_phase=phase_names[len(pivots) - 1],
        expected_wave_count=3,
        rules=rules,
        context_status="LOCAL_STRUCTURE_ONLY",
    )


def _finish_evaluation(
    *,
    grammar_profile_key: GrammarProfileKey,
    scenario_type: str,
    direction: Direction,
    current_phase: str,
    expected_wave_count: int,
    rules: tuple[RuleEvaluation, ...],
    context_status: str,
) -> GrammarEvaluation:
    confirmed_wave_count = (
        int(current_phase[1:])
        if current_phase.startswith("W")
        else {
            "C0": 0,
            "A": 1,
            "B": 2,
            "C": 3,
        }[current_phase]
    )
    failure = next((rule for rule in rules if rule.status is RuleStatus.FAIL), None)
    if failure is not None:
        status = ScenarioStatus.INVALIDATED
    elif confirmed_wave_count == expected_wave_count:
        status = ScenarioStatus.COMPLETED
    elif confirmed_wave_count >= 2:
        status = ScenarioStatus.ACTIVE
    else:
        status = ScenarioStatus.CANDIDATE
    return GrammarEvaluation(
        grammar_profile_key=grammar_profile_key,
        scenario_type=scenario_type,
        direction=direction,
        current_phase=current_phase,
        confirmed_wave_count=confirmed_wave_count,
        expected_wave_count=expected_wave_count,
        status=status,
        hard_evaluations=rules,
        invalidation_rule_key=failure.rule_key if failure else None,
        context_status=context_status,
    )


def resolve_grammar_profile(value: str | GrammarProfileKey) -> GrammarProfileKey | None:
    try:
        return (
            value if isinstance(value, GrammarProfileKey) else GrammarProfileKey(value)
        )
    except ValueError:
        return None
