"""Transparent SCORE_PROFILE_V1 feature and ranking implementation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Mapping

from .grammar import GrammarProfileKey
from .identities import as_decimal
from .pivot import PivotConfirmation
from .swings import ConfirmedSwing


class FeatureStatus(str, Enum):
    EVALUATED = "EVALUATED"
    NOT_YET_EVALUABLE = "NOT_YET_EVALUABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class RatioBand:
    low: Decimal
    ideal: Decimal
    high: Decimal
    tolerance: Decimal


@dataclass(frozen=True, slots=True)
class FeatureComponent:
    component_key: str
    status: FeatureStatus
    value: Decimal | None
    score: Decimal | None
    reason: str


@dataclass(frozen=True, slots=True)
class FeatureEvaluation:
    feature_key: str
    feature_status: FeatureStatus
    feature_value: Decimal | None
    feature_score: Decimal | None
    feature_coverage: Decimal
    feature_reason: str
    feature_profile_version: str
    components: tuple[FeatureComponent, ...] = ()


@dataclass(frozen=True, slots=True)
class ScenarioScore:
    score_profile_version: str
    heuristic_score: Decimal | None
    score_coverage: Decimal
    ranking_score: Decimal | None
    features: tuple[FeatureEvaluation, ...]


IMPULSE_WEIGHTS_V1 = (
    ("FIBONACCI_RATIO_FIT", Decimal(7) / Decimal(17)),
    ("TIME_RATIO_FIT", Decimal(4) / Decimal(17)),
    ("WAVE2_WAVE4_ALTERNATION", Decimal(3) / Decimal(17)),
    ("CHANNEL_FIT", Decimal(0)),
    ("STRUCTURE_COMPLETENESS", Decimal(3) / Decimal(17)),
)
ZIGZAG_WEIGHTS_V1 = (
    ("FIBONACCI_RATIO_FIT", Decimal(2) / Decimal(3)),
    ("TIME_RATIO_FIT", Decimal(0)),
    ("WAVE2_WAVE4_ALTERNATION", Decimal(0)),
    ("CHANNEL_FIT", Decimal(0)),
    ("STRUCTURE_COMPLETENESS", Decimal(1) / Decimal(3)),
)
RATIO_BANDS_V1 = (
    (
        "W2_W1",
        RatioBand(
            Decimal("0.382"), Decimal("0.618"), Decimal("0.786"), Decimal("0.05")
        ),
    ),
    (
        "W3_W1",
        RatioBand(
            Decimal("1.000"), Decimal("1.618"), Decimal("2.618"), Decimal("0.05")
        ),
    ),
    (
        "W4_W3",
        RatioBand(
            Decimal("0.236"), Decimal("0.382"), Decimal("0.786"), Decimal("0.05")
        ),
    ),
    (
        "W5_W1",
        RatioBand(
            Decimal("0.618"), Decimal("1.000"), Decimal("1.618"), Decimal("0.05")
        ),
    ),
    (
        "B_A",
        RatioBand(
            Decimal("0.382"), Decimal("0.618"), Decimal("0.886"), Decimal("0.05")
        ),
    ),
    (
        "C_A",
        RatioBand(
            Decimal("1.000"), Decimal("1.000"), Decimal("1.618"), Decimal("0.05")
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class ScoreProfile:
    score_profile_version: str = "SCORE_PROFILE_V1"
    source_baseline: str = "TA4J_0_23_0"
    empirical_status: str = "NOT_FITTED"
    aggregation_formula: str = "EVIDENCE_WEIGHTED_V1"
    impulse_weights: tuple[tuple[str, Decimal], ...] = IMPULSE_WEIGHTS_V1
    zigzag_weights: tuple[tuple[str, Decimal], ...] = ZIGZAG_WEIGHTS_V1
    ratio_bands: tuple[tuple[str, RatioBand], ...] = RATIO_BANDS_V1

    def __post_init__(self) -> None:
        expected_features = {
            "FIBONACCI_RATIO_FIT",
            "TIME_RATIO_FIT",
            "WAVE2_WAVE4_ALTERNATION",
            "CHANNEL_FIT",
            "STRUCTURE_COMPLETENESS",
        }
        for grammar_name, weights in (
            ("impulse", self.impulse_weights),
            ("zigzag", self.zigzag_weights),
        ):
            weight_map = dict(weights)
            if set(weight_map) != expected_features or len(weight_map) != len(weights):
                raise ValueError(
                    f"{grammar_name} weights must define each V1 feature once"
                )
            if any(not value.is_finite() or value < 0 for value in weight_map.values()):
                raise ValueError(
                    f"{grammar_name} weights must be finite and non-negative"
                )
            if abs(sum(weight_map.values(), Decimal(0)) - Decimal(1)) > Decimal(
                "1e-24"
            ):
                raise ValueError(f"{grammar_name} positive weights must sum to one")
        if len(dict(self.ratio_bands)) != len(self.ratio_bands):
            raise ValueError("ratio component keys must be unique")
        for _, band in self.ratio_bands:
            if not (
                Decimal(0) <= band.low <= band.ideal <= band.high
                and band.tolerance >= 0
            ):
                raise ValueError("ratio band bounds are invalid")
        if self.score_profile_version == "SCORE_PROFILE_V1" and (
            self.source_baseline != "TA4J_0_23_0"
            or self.empirical_status != "NOT_FITTED"
            or self.aggregation_formula != "EVIDENCE_WEIGHTED_V1"
            or self.impulse_weights != IMPULSE_WEIGHTS_V1
            or self.zigzag_weights != ZIGZAG_WEIGHTS_V1
            or self.ratio_bands != RATIO_BANDS_V1
        ):
            raise ValueError("SCORE_PROFILE_V1 semantics changed without a new version")


SCORE_PROFILE_V1 = ScoreProfile()


def proximity(
    ratio: Decimal | int | float | str,
    low: Decimal | int | float | str,
    ideal: Decimal | int | float | str,
    high: Decimal | int | float | str,
    tolerance: Decimal | int | float | str,
) -> Decimal:
    r, left, target, right, margin = map(
        as_decimal, (ratio, low, ideal, high, tolerance)
    )
    if r < 0 or not (left <= target <= right) or margin < 0:
        raise ValueError("proximity inputs violate ratio band contract")
    if r < left - margin or r > right + margin:
        return Decimal(0)
    left_edge_score = Decimal(1) if target == left else Decimal("0.5")
    right_edge_score = Decimal(1) if target == right else Decimal("0.5")
    if margin > 0 and left - margin <= r < left:
        value = left_edge_score * (r - (left - margin)) / margin
    elif r == target:
        value = Decimal(1)
    elif left <= r < target:
        value = left_edge_score + (Decimal(1) - left_edge_score) * (r - left) / (
            target - left
        )
    elif target < r <= right:
        value = Decimal(1) - (Decimal(1) - right_edge_score) * (r - target) / (
            right - target
        )
    elif margin > 0 and right < r <= right + margin:
        value = right_edge_score * ((right + margin) - r) / margin
    elif r == left:
        value = left_edge_score
    elif r == right:
        value = right_edge_score
    else:
        value = Decimal(0)
    return min(Decimal(1), max(Decimal(0), value))


def ratio_component(
    component_key: str,
    numerator: Decimal | int | float | str,
    denominator: Decimal | int | float | str,
    band: RatioBand,
) -> FeatureComponent:
    try:
        top = as_decimal(numerator)
        bottom = as_decimal(denominator)
    except (ValueError, InvalidOperation):
        return FeatureComponent(
            component_key,
            FeatureStatus.NOT_YET_EVALUABLE,
            None,
            None,
            "RATIO_NON_FINITE",
        )
    if top < 0 or bottom <= 0:
        return FeatureComponent(
            component_key,
            FeatureStatus.NOT_YET_EVALUABLE,
            None,
            None,
            "RATIO_DENOMINATOR_OR_NUMERATOR_INVALID",
        )
    value = top / bottom
    return FeatureComponent(
        component_key,
        FeatureStatus.EVALUATED,
        value,
        proximity(value, band.low, band.ideal, band.high, band.tolerance),
        "RATIO_EVALUATED",
    )


def _feature_from_components(
    feature_key: str,
    components: tuple[FeatureComponent, ...],
    total_components: int,
    profile: ScoreProfile,
) -> FeatureEvaluation:
    evaluated = tuple(
        component
        for component in components
        if component.status is FeatureStatus.EVALUATED and component.score is not None
    )
    coverage = Decimal(len(evaluated)) / Decimal(total_components)
    if not evaluated:
        return FeatureEvaluation(
            feature_key,
            FeatureStatus.NOT_YET_EVALUABLE,
            None,
            None,
            coverage,
            "NO_EVALUABLE_COMPONENT",
            profile.score_profile_version,
            components,
        )
    score = sum((component.score for component in evaluated), Decimal(0)) / Decimal(
        len(evaluated)
    )
    values = [component.value for component in evaluated if component.value is not None]
    value = sum(values, Decimal(0)) / Decimal(len(values)) if values else None
    return FeatureEvaluation(
        feature_key,
        FeatureStatus.EVALUATED,
        value,
        score,
        coverage,
        "EVALUATED_COMPONENT_MEAN",
        profile.score_profile_version,
        components,
    )


def _not_applicable(
    feature_key: str, reason: str, profile: ScoreProfile
) -> FeatureEvaluation:
    return FeatureEvaluation(
        feature_key,
        FeatureStatus.NOT_APPLICABLE,
        None,
        None,
        Decimal(0),
        reason,
        profile.score_profile_version,
    )


def _fib_feature(
    grammar: GrammarProfileKey,
    pivots: tuple[PivotConfirmation, ...],
    profile: ScoreProfile,
) -> FeatureEvaluation:
    amplitudes = tuple(
        abs(current.extreme_price - previous.extreme_price)
        for previous, current in zip(pivots, pivots[1:])
    )
    bands = dict(profile.ratio_bands)
    components: list[FeatureComponent] = []
    if grammar is GrammarProfileKey.IMPULSE_STANDARD_V1:
        definitions = (
            ("W2_W1", 1, 0),
            ("W3_W1", 2, 0),
            ("W4_W3", 3, 2),
            ("W5_W1", 4, 0),
        )
        total = 4
    else:
        definitions = (("B_A", 1, 0), ("C_A", 2, 0))
        total = 2
    for key, numerator_index, denominator_index in definitions:
        if len(amplitudes) > numerator_index:
            components.append(
                ratio_component(
                    key,
                    amplitudes[numerator_index],
                    amplitudes[denominator_index],
                    bands[key],
                )
            )
    return _feature_from_components(
        "FIBONACCI_RATIO_FIT", tuple(components), total, profile
    )


def _time_feature(
    grammar: GrammarProfileKey,
    swings: tuple[ConfirmedSwing, ...] | None,
    profile: ScoreProfile,
) -> FeatureEvaluation:
    if grammar is GrammarProfileKey.CORRECTIVE_ZIGZAG_V1:
        return _not_applicable(
            "TIME_RATIO_FIT", "ZIGZAG_TIME_PROFILE_NOT_FROZEN", profile
        )
    if swings is None or len(swings) < 3:
        return _feature_from_components("TIME_RATIO_FIT", (), 2, profile)
    components: list[FeatureComponent] = []
    duration1 = swings[0].duration_bars
    duration3 = swings[2].duration_bars
    if duration1 <= 0 or duration3 <= 0:
        components.append(
            FeatureComponent(
                "T3", FeatureStatus.NOT_YET_EVALUABLE, None, None, "DURATION_INVALID"
            )
        )
    else:
        ratio = Decimal(duration3) / Decimal(duration1)
        components.append(
            FeatureComponent(
                "T3",
                FeatureStatus.EVALUATED,
                ratio,
                min(Decimal(1), ratio),
                "DURATION_EVALUATED",
            )
        )
    if len(swings) >= 5:
        components.append(
            ratio_component(
                "T5",
                swings[4].duration_bars,
                duration1,
                RatioBand(
                    Decimal("0.5"), Decimal("1.0"), Decimal("1.5"), Decimal("0.5")
                ),
            )
        )
    return _feature_from_components("TIME_RATIO_FIT", tuple(components), 2, profile)


def _alternation_feature(
    grammar: GrammarProfileKey,
    pivots: tuple[PivotConfirmation, ...],
    swings: tuple[ConfirmedSwing, ...] | None,
    profile: ScoreProfile,
) -> FeatureEvaluation:
    if grammar is GrammarProfileKey.CORRECTIVE_ZIGZAG_V1:
        return _not_applicable(
            "WAVE2_WAVE4_ALTERNATION", "NOT_DEFINED_FOR_ZIGZAG_V1", profile
        )
    if swings is None or len(swings) < 4 or len(pivots) < 5:
        return FeatureEvaluation(
            "WAVE2_WAVE4_ALTERNATION",
            FeatureStatus.NOT_YET_EVALUABLE,
            None,
            None,
            Decimal(0),
            "WAVE4_NOT_CONFIRMED_OR_DURATION_MISSING",
            profile.score_profile_version,
        )
    amp1 = abs(pivots[1].extreme_price - pivots[0].extreme_price)
    amp2 = abs(pivots[2].extreme_price - pivots[1].extreme_price)
    amp3 = abs(pivots[3].extreme_price - pivots[2].extreme_price)
    amp4 = abs(pivots[4].extreme_price - pivots[3].extreme_price)
    duration2 = swings[1].duration_bars
    duration4 = swings[3].duration_bars
    if amp1 <= 0 or amp3 <= 0 or duration2 <= 0 or duration4 <= 0:
        return FeatureEvaluation(
            "WAVE2_WAVE4_ALTERNATION",
            FeatureStatus.NOT_YET_EVALUABLE,
            None,
            None,
            Decimal(0),
            "ALTERNATION_DENOMINATOR_INVALID",
            profile.score_profile_version,
        )
    depth2 = amp2 / amp1
    depth4 = amp4 / amp3
    depth_score = min(Decimal(1), Decimal(2) * abs(depth2 - depth4))
    time_score = min(
        Decimal(1),
        Decimal(abs(duration2 - duration4)) / Decimal(max(duration2, duration4)),
    )
    score = (depth_score + time_score) / Decimal(2)
    return FeatureEvaluation(
        "WAVE2_WAVE4_ALTERNATION",
        FeatureStatus.EVALUATED,
        abs(depth2 - depth4),
        score,
        Decimal(1),
        f"DEPTH_SCORE={depth_score};TIME_SCORE={time_score}",
        profile.score_profile_version,
        (
            FeatureComponent(
                "DEPTH_DIFFERENCE",
                FeatureStatus.EVALUATED,
                abs(depth2 - depth4),
                depth_score,
                "DEPTH_DIFFERENCE_EVALUATED",
            ),
            FeatureComponent(
                "TIME_DIFFERENCE",
                FeatureStatus.EVALUATED,
                Decimal(abs(duration2 - duration4))
                / Decimal(max(duration2, duration4)),
                time_score,
                "TIME_DIFFERENCE_EVALUATED",
            ),
        ),
    )


def _completeness_feature(
    grammar: GrammarProfileKey,
    confirmed_wave_count: int,
    profile: ScoreProfile,
) -> FeatureEvaluation:
    expected = 5 if grammar is GrammarProfileKey.IMPULSE_STANDARD_V1 else 3
    score = min(Decimal(1), Decimal(confirmed_wave_count) / Decimal(expected))
    return FeatureEvaluation(
        "STRUCTURE_COMPLETENESS",
        FeatureStatus.EVALUATED,
        score,
        score,
        Decimal(1),
        "CONFIRMED_WAVE_FRACTION",
        profile.score_profile_version,
    )


def score_scenario(
    grammar: GrammarProfileKey,
    pivots: tuple[PivotConfirmation, ...],
    *,
    swings: tuple[ConfirmedSwing, ...] | None = None,
    profile: ScoreProfile = SCORE_PROFILE_V1,
) -> ScenarioScore:
    features = (
        _fib_feature(grammar, pivots, profile),
        _time_feature(grammar, swings, profile),
        _alternation_feature(grammar, pivots, swings, profile),
        _not_applicable(
            "CHANNEL_FIT", "CHANNEL_ALGORITHM_NOT_FROZEN_IN_SCORE_V1", profile
        ),
        _completeness_feature(grammar, len(pivots) - 1, profile),
    )
    weights: Mapping[str, Decimal] = dict(
        profile.impulse_weights
        if grammar is GrammarProfileKey.IMPULSE_STANDARD_V1
        else profile.zigzag_weights
    )
    evaluated_weight = Decimal(0)
    weighted_sum = Decimal(0)
    for feature in features:
        weight = weights[feature.feature_key]
        effective_weight = weight * feature.feature_coverage
        if feature.feature_score is not None and effective_weight > 0:
            evaluated_weight += effective_weight
            weighted_sum += effective_weight * feature.feature_score
    if evaluated_weight == 0:
        heuristic_score = None
        ranking_score = None
    else:
        heuristic_score = weighted_sum / evaluated_weight
        ranking_score = weighted_sum
    return ScenarioScore(
        score_profile_version=profile.score_profile_version,
        heuristic_score=heuristic_score,
        score_coverage=evaluated_weight,
        ranking_score=ranking_score,
        features=features,
    )
