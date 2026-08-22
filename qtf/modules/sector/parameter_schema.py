from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from qtf.contracts.errors import QtfRequestInvalid
from qtf.contracts.parameters import (
    EffectiveParameterSet,
    ParameterDefinition,
    ParameterKind,
    ParameterSchema,
    ParameterSchemaRegistry,
    ParameterValueSource,
)
from qtf.engine.parameter_resolution import resolve_effective_parameters


SECTOR_L2_PARAMETER_SCHEMA_KEY = "sector_l2_heat_params_v1"
SECTOR_L2_PARAMETER_SCHEMA_VERSION = "1"


class ComparisonScope(StrEnum):
    SIBLINGS = "SIBLINGS"


class RankingRuleKind(StrEnum):
    PERCENTILE_GTE = "PERCENTILE_GTE"


class EventClusterRule(StrEnum):
    RESET_ONLY = "RESET_ONLY"


@dataclass(frozen=True, slots=True)
class RankingRule:
    kind: RankingRuleKind
    threshold: float


@dataclass(frozen=True, slots=True)
class SectorHeatParameters:
    baseline_days: int
    trend_days: int
    amount_lookback_days: int
    ewma_lambda: float
    price_weight: float
    amount_weight: float
    z_clip: float
    signal_threshold: float
    reset_threshold: float
    up_move_share_min: float
    future_horizons: tuple[int, ...]
    comparison_scope: ComparisonScope
    minimum_group_size: int
    ranking_rule: RankingRule
    event_cluster_rule: EventClusterRule

    @property
    def required_source_history_days(self) -> int:
        return self.amount_lookback_days + self.baseline_days + self.trend_days - 1


@dataclass(frozen=True, slots=True)
class ResolvedSectorHeatParameters:
    effective: EffectiveParameterSet
    parameters: SectorHeatParameters


SECTOR_L2_PARAMETER_SCHEMA = ParameterSchema(
    schema_key=SECTOR_L2_PARAMETER_SCHEMA_KEY,
    schema_version=SECTOR_L2_PARAMETER_SCHEMA_VERSION,
    fields=(
        ParameterDefinition("baseline_days", ParameterKind.INTEGER, True, allowed_values=(60, 120)),
        ParameterDefinition("trend_days", ParameterKind.INTEGER, True, allowed_values=(5, 10, 20, 30)),
        ParameterDefinition("amount_lookback_days", ParameterKind.INTEGER, False, allowed_values=(20,)),
        ParameterDefinition(
            "ewma_lambda",
            ParameterKind.NUMBER,
            False,
            minimum=0,
            maximum=1,
            minimum_inclusive=False,
        ),
        ParameterDefinition("price_weight", ParameterKind.NUMBER, False, minimum=0, maximum=1),
        ParameterDefinition("amount_weight", ParameterKind.NUMBER, False, minimum=0, maximum=1),
        ParameterDefinition(
            "z_clip",
            ParameterKind.NUMBER,
            False,
            minimum=0,
            minimum_inclusive=False,
        ),
        ParameterDefinition("signal_threshold", ParameterKind.NUMBER, False, minimum=0, maximum=100),
        ParameterDefinition("reset_threshold", ParameterKind.NUMBER, False, minimum=0, maximum=100),
        ParameterDefinition("up_move_share_min", ParameterKind.NUMBER, False, minimum=0, maximum=1),
        ParameterDefinition("future_horizons", ParameterKind.INTEGER_SEQUENCE, False),
        ParameterDefinition(
            "comparison_scope",
            ParameterKind.STRING,
            False,
            allowed_values=(ComparisonScope.SIBLINGS.value,),
        ),
        ParameterDefinition("minimum_group_size", ParameterKind.INTEGER, False, minimum=2),
        ParameterDefinition("ranking_rule", ParameterKind.MAPPING, False),
        ParameterDefinition(
            "event_cluster_rule",
            ParameterKind.STRING,
            False,
            allowed_values=(EventClusterRule.RESET_ONLY.value,),
        ),
    ),
)

SECTOR_PARAMETER_SCHEMA_REGISTRY = ParameterSchemaRegistry((SECTOR_L2_PARAMETER_SCHEMA,))


def resolve_sector_heat_parameters(
    values: Mapping[str, object],
    sources: Mapping[str, ParameterValueSource | str],
) -> ResolvedSectorHeatParameters:
    normalized_input = dict(values)
    if "ranking_rule" in normalized_input:
        normalized_input["ranking_rule"] = _normalize_ranking_rule(normalized_input["ranking_rule"])
    effective = resolve_effective_parameters(
        SECTOR_L2_PARAMETER_SCHEMA,
        normalized_input,
        sources,
        dependency_validator=_validate_dependencies,
    )
    ranking_mapping = effective.values["ranking_rule"]
    if not isinstance(ranking_mapping, Mapping):
        raise AssertionError("ranking_rule was not normalized as a mapping")
    parameters = SectorHeatParameters(
        baseline_days=int(effective.values["baseline_days"]),
        trend_days=int(effective.values["trend_days"]),
        amount_lookback_days=int(effective.values["amount_lookback_days"]),
        ewma_lambda=float(effective.values["ewma_lambda"]),
        price_weight=float(effective.values["price_weight"]),
        amount_weight=float(effective.values["amount_weight"]),
        z_clip=float(effective.values["z_clip"]),
        signal_threshold=float(effective.values["signal_threshold"]),
        reset_threshold=float(effective.values["reset_threshold"]),
        up_move_share_min=float(effective.values["up_move_share_min"]),
        future_horizons=tuple(int(value) for value in effective.values["future_horizons"]),  # type: ignore[union-attr]
        comparison_scope=ComparisonScope(str(effective.values["comparison_scope"])),
        minimum_group_size=int(effective.values["minimum_group_size"]),
        ranking_rule=RankingRule(
            kind=RankingRuleKind(str(ranking_mapping["kind"])),
            threshold=float(ranking_mapping["threshold"]),
        ),
        event_cluster_rule=EventClusterRule(str(effective.values["event_cluster_rule"])),
    )
    return ResolvedSectorHeatParameters(effective=effective, parameters=parameters)


def _normalize_ranking_rule(value: object) -> object:
    if not isinstance(value, Mapping) or set(value) != {"kind", "threshold"}:
        return value
    threshold = value["threshold"]
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        return value
    return {"kind": value["kind"], "threshold": float(threshold)}


def _validate_dependencies(values: Mapping[str, object]) -> None:
    if not math.isclose(
        float(values["price_weight"]) + float(values["amount_weight"]),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise QtfRequestInvalid("price_weight and amount_weight must sum to 1")
    if float(values["reset_threshold"]) >= float(values["signal_threshold"]):
        raise QtfRequestInvalid("reset_threshold must be lower than signal_threshold")
    if tuple(values["future_horizons"]) != (1, 3, 5):  # type: ignore[arg-type]
        raise QtfRequestInvalid("future_horizons must be exactly [1, 3, 5]")

    ranking_rule = values["ranking_rule"]
    if not isinstance(ranking_rule, Mapping) or set(ranking_rule) != {"kind", "threshold"}:
        raise QtfRequestInvalid("ranking_rule must contain exactly kind and threshold")
    try:
        kind = RankingRuleKind(ranking_rule["kind"])
    except (TypeError, ValueError) as exc:
        raise QtfRequestInvalid("ranking_rule kind is not supported") from exc
    if kind is not RankingRuleKind.PERCENTILE_GTE:
        raise QtfRequestInvalid("ranking_rule kind is not supported")
    threshold = ranking_rule["threshold"]
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise QtfRequestInvalid("ranking_rule threshold must be numeric")
    if not math.isfinite(float(threshold)) or float(threshold) < 0 or float(threshold) > 100:
        raise QtfRequestInvalid("ranking_rule threshold must be within [0, 100]")
