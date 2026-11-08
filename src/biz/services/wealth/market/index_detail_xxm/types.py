from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TYPE_CHECKING

from goldenshare_technical_indicators.xxm.types import XxmReferenceFacts, XxmStructureRecord, XxmWaveFacts

if TYPE_CHECKING:
    from .forecast_math import Interval


@dataclass(frozen=True, slots=True)
class ForecastPrecheck:
    snapshot: dict[str, Any]
    direction: Literal["TOP", "BOTTOM"] | None
    references: dict[str, XxmReferenceFacts | None]
    active_role: Literal["NEAR", "FAR"] | None
    nearest_decision: dict[str, str | None]
    stop_reason: str | None
    following_structures: tuple[XxmStructureRecord, ...]


@dataclass(frozen=True, slots=True)
class ComparisonRanges:
    certain_true: tuple[Interval, ...]
    certain_false: tuple[Interval, ...]
    undecided: tuple[Interval, ...]


@dataclass(frozen=True, slots=True)
class ForecastConditionDraft:
    outcome: str
    reference_role: Literal["NEAR", "FAR"]
    price_ranges: tuple[dict[str, Any], ...]
    predicates: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ReferenceForecast:
    conditions: tuple[ForecastConditionDraft, ...]
    relationship_ranges: tuple[Interval, ...]
    relationship_precision_ranges: tuple[Interval, ...]
    precision_ranges: tuple[Interval, ...]
    far_evaluated: bool = False


@dataclass(frozen=True, slots=True)
class StructureFollowConditionDraft:
    outcome: Literal["SIGNAL_DISAPPEARED"]
    related_structure_id: str
    direction: Literal["TOP", "BOTTOM"]
    origin_wave: XxmWaveFacts
    next_same_color_start: str | None
    next_same_color_count: int
    price_ranges: tuple[dict[str, Any], ...]
    precision_ranges: tuple[dict[str, Any], ...]
    predicates: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ForecastKernelResult:
    status: str
    reason_code: str | None
    target_endpoint: str | None
    bars_ahead: Literal[1] | None
    references: dict[str, XxmReferenceFacts | None]
    selected_reference: Literal["NEAR", "FAR"] | None
    nearest_decision: dict[str, str | None]
    far_evaluated: bool
    conditions: tuple[ForecastConditionDraft, ...]
    precision_ranges: tuple[dict[str, Any], ...]
    structure_follow_conditions: tuple[StructureFollowConditionDraft, ...]
