from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
import hashlib
import json
from typing import Any, Mapping
from uuid import UUID

from src.biz.queries.wealth.market.common.sector_hierarchy_query import SectorHierarchySnapshot
from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_contract import (
    MemberMarketFact,
    MemberRelationFact,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import SectorDailyFact
from src.biz.services.wealth.market.sector_analysis.sector_price_volume_contract import SectorPriceVolumeDailyFact


FORMULA_BUNDLE_VERSION = "sector-analysis-daily-facts@1"
TEMPLATE_VERSION = "sector-daily-insight-template@1"
TEMPLATE_KEY = "sector-daily-insight"
SOURCE_NOT_READY = "SA_DAILY_FACT_SOURCE_NOT_READY"
PLAN_DRIFT = "SA_DAILY_FACT_PLAN_DRIFT"
READBACK_MISMATCH = "SA_DAILY_FACT_READBACK_MISMATCH"
BATCH_MISMATCH = "SA_DAILY_INSIGHT_BATCH_MISMATCH"
ALLOWED_SCOPES = (
    "LEVEL_1",
    "LEVEL_2",
    "LEVEL_3",
    "LEVEL_1_CHILDREN",
    "LEVEL_2_CHILDREN",
)


class SectorAnalysisDailyFactsError(RuntimeError):
    code = "SA_DAILY_FACT_SOURCE_NOT_READY"


class SectorAnalysisDailyFactsSourceNotReadyError(SectorAnalysisDailyFactsError):
    code = SOURCE_NOT_READY


class SectorAnalysisDailyFactsPlanDriftError(SectorAnalysisDailyFactsError):
    code = PLAN_DRIFT


class SectorAnalysisDailyFactsReadbackError(SectorAnalysisDailyFactsError):
    code = READBACK_MISMATCH


@dataclass(frozen=True, slots=True)
class SectorComparisonPool:
    scope: str
    comparison_key: str
    parent_sector_code: str | None
    sector_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SectorAnalysisSourceBundle:
    trade_date: date
    previous_trade_date: date
    open_dates: tuple[date, ...]
    hierarchy: SectorHierarchySnapshot
    comparison_pools: tuple[SectorComparisonPool, ...]
    sector_facts: tuple[SectorDailyFact, ...]
    price_volume_facts: tuple[SectorPriceVolumeDailyFact, ...]
    member_relations: tuple[MemberRelationFact, ...]
    member_market_facts: tuple[MemberMarketFact, ...]
    source_dates: Mapping[str, str]
    source_row_counts: Mapping[str, int]
    source_hash: str


@dataclass(frozen=True, slots=True)
class FactIdentity:
    trade_date: date
    comparison_scope: str
    comparison_key: str
    parent_sector_code: str | None
    sector_code: str
    sector_name: str
    industry_level: int
    hierarchy_path: str


@dataclass(frozen=True, slots=True)
class MomentumFactRow:
    identity: FactIdentity
    period: int
    return_pct: Decimal | None
    strength_rank: int | None
    rankable_count: int | None
    percentile: Decimal | None
    calculation_status: str
    missing_reason: str


@dataclass(frozen=True, slots=True)
class DualMomentumFactRow:
    identity: FactIdentity
    period: int
    return_pct: Decimal | None
    strength_rank: int | None
    rankable_count: int | None
    percentile: Decimal | None
    absolute_status: str
    coordinate_status: str
    relative_status_70: str
    qualification_status_70: str
    display_status_70: str
    relative_status_80: str
    qualification_status_80: str
    display_status_80: str
    relative_status_90: str
    qualification_status_90: str
    display_status_90: str
    minimum_group_size: int
    calculation_status: str
    missing_reason: str


@dataclass(frozen=True, slots=True)
class RelativeRotationFactRow:
    identity: FactIdentity
    period: int
    comparison_trade_date: date
    return_pct: Decimal | None
    strength_rank: int | None
    rankable_count: int | None
    percentile: Decimal | None
    comparison_return_pct: Decimal | None
    comparison_strength_rank: int | None
    comparison_rankable_count: int | None
    comparison_percentile: Decimal | None
    percentile_delta_5d: Decimal | None
    rotation_status: str
    coordinate_status: str
    group_interpretation: str
    current_missing_reason: str | None
    comparison_missing_reason: str | None
    minimum_group_size: int
    calculation_status: str
    missing_reason: str


@dataclass(frozen=True, slots=True)
class MemberBreadthFactRow:
    identity: FactIdentity
    values: Mapping[str, Any]
    calculation_status: str
    missing_reason: str


@dataclass(frozen=True, slots=True)
class MemberMaBreadthFactRow:
    identity: FactIdentity
    ma_period: int
    values: Mapping[str, Any]
    calculation_status: str
    missing_reason: str


@dataclass(frozen=True, slots=True)
class PriceVolumeFactRow:
    identity: FactIdentity
    period: int
    values: Mapping[str, Any]
    calculation_status: str
    missing_reason: str


@dataclass(frozen=True, slots=True)
class DailyInsightSummaryRow:
    trade_date: date
    industry_level: int
    values: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class DailyInsightItemRow:
    trade_date: date
    industry_level: int
    category: str
    sector_code: str
    values: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class BuiltMethodFacts:
    momentum: tuple[MomentumFactRow, ...]
    dual_momentum: tuple[DualMomentumFactRow, ...]
    relative_rotation: tuple[RelativeRotationFactRow, ...]
    member_breadth: tuple[MemberBreadthFactRow, ...]
    member_ma_breadth: tuple[MemberMaBreadthFactRow, ...]
    price_volume: tuple[PriceVolumeFactRow, ...]


@dataclass(frozen=True, slots=True)
class PreviousSectorEvidence:
    sector_code: str
    rank_20d: int | None
    rankable_count_20d: int | None
    percentile_20d: Decimal | None
    price_volume_state: str | None
    dual_qualification_20d_80: str | None
    rotation_status_20d: str | None
    member_up_pct: Decimal | None
    turnover_up_pct: Decimal | None
    ma20_above_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class PreviousPublishedEvidence:
    batch_id: UUID
    trade_date: date
    hierarchy_version: str
    formula_bundle_version: str
    by_sector: Mapping[str, PreviousSectorEvidence]


@dataclass(frozen=True, slots=True)
class BuiltDailyFacts:
    trade_date: date
    previous_trade_date: date
    previous_batch_id: UUID | None
    hierarchy_version: str
    source_hash: str
    source_dates: Mapping[str, str]
    source_row_counts: Mapping[str, int]
    momentum: tuple[MomentumFactRow, ...]
    dual_momentum: tuple[DualMomentumFactRow, ...]
    relative_rotation: tuple[RelativeRotationFactRow, ...]
    member_breadth: tuple[MemberBreadthFactRow, ...]
    member_ma_breadth: tuple[MemberMaBreadthFactRow, ...]
    price_volume: tuple[PriceVolumeFactRow, ...]
    insight_summaries: tuple[DailyInsightSummaryRow, ...]
    insight_items: tuple[DailyInsightItemRow, ...]
    content_hash: str

    @property
    def fact_counts(self) -> dict[str, int]:
        return {
            "wealth_sector_analysis_publish_batch": 1,
            "wealth_sector_momentum_daily": len(self.momentum),
            "wealth_sector_dual_momentum_daily": len(self.dual_momentum),
            "wealth_sector_relative_rotation_daily": len(self.relative_rotation),
            "wealth_sector_member_breadth_daily": len(self.member_breadth),
            "wealth_sector_member_ma_breadth_daily": len(self.member_ma_breadth),
            "wealth_sector_price_volume_daily": len(self.price_volume),
            "wealth_sector_daily_insight_summary": len(self.insight_summaries),
            "wealth_sector_daily_insight_item": len(self.insight_items),
        }


@dataclass(frozen=True, slots=True)
class DailyFactsPreview:
    trade_date: date
    hierarchy_version: str
    source_hash: str
    plan_hash: str
    content_hash: str
    source_dates: Mapping[str, str]
    source_row_counts: Mapping[str, int]
    expected_fact_counts: Mapping[str, int]
    missing_counts: Mapping[str, int]
    finite_summary: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class DailyFactsMaterializationResult:
    trade_date: date
    batch_id: UUID | None
    status: str
    rows_saved: int
    plan_hash: str
    content_hash: str
    idempotent: bool


def canonical_json_hash(value: Any) -> str:
    encoded = json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_row(row: Any) -> dict[str, Any]:
    return _json_value(asdict(row))


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, UUID)):
        return str(value)
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value
