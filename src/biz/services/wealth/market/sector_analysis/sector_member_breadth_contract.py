from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, cast

from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorMomentumScope,
    SectorScopeInvalidError,
)


SectorMemberBreadthMetric = Literal["MEMBER_COUNT", "TURNOVER", "MA_POSITION"]
SectorMemberBreadthDirection = Literal["UP", "DOWN"]
SectorMemberBreadthMaPeriod = Literal[5, 10, 15, 20, 30, 60]
SectorMemberBreadthHistoryRange = Literal[20, 30, 60]
SectorMemberBreadthQualification = Literal["ELIGIBLE", "INELIGIBLE"]
SectorMemberBreadthAvailability = Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"]
SectorMemberBreadthReason = Literal[
    "SOURCE_MEMBER_EMPTY",
    "MARKET_ROW_MISSING",
    "PCT_CHANGE_MISSING",
    "AMOUNT_MISSING",
    "AMOUNT_NON_POSITIVE",
    "ADJ_FACTOR_MISSING",
    "ADJ_FACTOR_NON_POSITIVE",
    "MA_HISTORY_INSUFFICIENT",
    "MINIMUM_COUNT_NOT_MET",
    "COVERAGE_NOT_MET",
]
SectorMemberMaRelation = Literal["ABOVE", "EQUAL", "BELOW"]

MEMBER_BREADTH_FORMULA_KEY = "sector-member-breadth"
MEMBER_BREADTH_FORMULA_VERSION = 1
MEMBER_BREADTH_MINIMUM_CALCULABLE_COUNT = 5
MEMBER_BREADTH_MINIMUM_COVERAGE_PCT = Decimal("80")

ALLOWED_MEMBER_BREADTH_METRICS: tuple[SectorMemberBreadthMetric, ...] = (
    "MEMBER_COUNT",
    "TURNOVER",
    "MA_POSITION",
)
ALLOWED_MEMBER_BREADTH_DIRECTIONS: tuple[SectorMemberBreadthDirection, ...] = (
    "UP",
    "DOWN",
)
ALLOWED_MEMBER_BREADTH_MA_PERIODS: tuple[SectorMemberBreadthMaPeriod, ...] = (
    5,
    10,
    15,
    20,
    30,
    60,
)
ALLOWED_MEMBER_BREADTH_HISTORY_RANGES: tuple[SectorMemberBreadthHistoryRange, ...] = (
    20,
    30,
    60,
)
ALLOWED_MEMBER_BREADTH_REASONS: tuple[SectorMemberBreadthReason, ...] = (
    "SOURCE_MEMBER_EMPTY",
    "MARKET_ROW_MISSING",
    "PCT_CHANGE_MISSING",
    "AMOUNT_MISSING",
    "AMOUNT_NON_POSITIVE",
    "ADJ_FACTOR_MISSING",
    "ADJ_FACTOR_NON_POSITIVE",
    "MA_HISTORY_INSUFFICIENT",
    "MINIMUM_COUNT_NOT_MET",
    "COVERAGE_NOT_MET",
)


class SectorMemberBreadthFactMismatchError(RuntimeError):
    pass


class SectorMemberBreadthQueryError(RuntimeError):
    pass


class DuplicateMemberBreadthFactError(SectorMemberBreadthQueryError):
    pass


@dataclass(frozen=True, slots=True)
class SectorMemberBreadthRankingsRequest:
    market: Literal["CN_A"]
    trade_date: date
    scope: SectorMomentumScope
    level1_code: str | None
    level2_code: str | None
    direction: SectorMemberBreadthDirection
    metric: SectorMemberBreadthMetric
    ma_period: SectorMemberBreadthMaPeriod
    hierarchy_version: str


@dataclass(frozen=True, slots=True)
class SectorMemberBreadthDetailsRequest:
    market: Literal["CN_A"]
    trade_date: date
    sector_code: str
    direction: SectorMemberBreadthDirection
    ma_period: SectorMemberBreadthMaPeriod
    history_range: SectorMemberBreadthHistoryRange
    hierarchy_version: str


@dataclass(frozen=True, slots=True)
class MemberRelationFact:
    sector_code: str
    trade_date: date
    stock_code: str
    stock_name: str | None


@dataclass(frozen=True, slots=True)
class MemberMarketFact:
    stock_code: str
    trade_date: date
    close: Decimal | None
    pct_change: Decimal | None
    amount_thousand_yuan: Decimal | None
    adj_factor: Decimal | None


@dataclass(frozen=True, slots=True)
class MemberBreadthWindowRelationsFact:
    coverage_start_date: date
    coverage_end_date: date
    open_dates: tuple[date, ...]
    relation_dates: tuple[date, ...]
    relations: tuple[MemberRelationFact, ...]


@dataclass(frozen=True, slots=True)
class MetricCoverageFact:
    source_count: int
    calculable_count: int
    coverage_pct: Decimal
    eligible: bool
    reason_codes: tuple[SectorMemberBreadthReason, ...]


@dataclass(frozen=True, slots=True)
class MemberBreadthCompositionFact:
    metric: SectorMemberBreadthMetric
    up_count: int
    flat_count: int
    down_count: int
    up_pct: Decimal | None
    flat_pct: Decimal | None
    down_pct: Decimal | None
    coverage: MetricCoverageFact


@dataclass(frozen=True, slots=True)
class MemberBreadthRankFact:
    sector_code: str
    metric_calculable: bool
    metric_value_pct: Decimal | None
    rank: int | None
    rank_total: int | None
    coverage: MetricCoverageFact
    reason_codes: tuple[SectorMemberBreadthReason, ...]


@dataclass(frozen=True, slots=True)
class MemberBreadthTrendPointFact:
    trade_date: date
    member_pct: Decimal | None
    turnover_pct: Decimal | None
    ma_position_pct: Decimal | None
    member_reason_codes: tuple[SectorMemberBreadthReason, ...]
    turnover_reason_codes: tuple[SectorMemberBreadthReason, ...]
    ma_position_reason_codes: tuple[SectorMemberBreadthReason, ...]


@dataclass(frozen=True, slots=True)
class MemberBreadthMemberFact:
    stock_code: str
    stock_name: str | None
    daily_pct_change: Decimal | None
    amount_thousand_yuan: Decimal | None
    amount_contribution_pct: Decimal | None
    ma_relation: SectorMemberMaRelation | None
    ma_distance_pct: Decimal | None
    reason_codes: tuple[SectorMemberBreadthReason, ...]


@dataclass(frozen=True, slots=True)
class MemberBreadthDetailsFact:
    compositions: tuple[MemberBreadthCompositionFact, ...]
    trend: tuple[MemberBreadthTrendPointFact, ...]
    members: tuple[MemberBreadthMemberFact, ...]


def parse_member_breadth_metric(value: str) -> SectorMemberBreadthMetric:
    if value not in ALLOWED_MEMBER_BREADTH_METRICS:
        raise SectorScopeInvalidError(f"metric 不支持：{value}")
    return cast(SectorMemberBreadthMetric, value)


def parse_member_breadth_direction(value: str) -> SectorMemberBreadthDirection:
    if value not in ALLOWED_MEMBER_BREADTH_DIRECTIONS:
        raise SectorScopeInvalidError(f"direction 不支持：{value}")
    return cast(SectorMemberBreadthDirection, value)


def parse_member_breadth_ma_period(value: int) -> SectorMemberBreadthMaPeriod:
    if value not in ALLOWED_MEMBER_BREADTH_MA_PERIODS:
        raise SectorScopeInvalidError(f"maPeriod 不支持：{value}")
    return cast(SectorMemberBreadthMaPeriod, value)


def parse_member_breadth_history_range(
    value: int,
) -> SectorMemberBreadthHistoryRange:
    if value not in ALLOWED_MEMBER_BREADTH_HISTORY_RANGES:
        raise SectorScopeInvalidError(f"historyRange 不支持：{value}")
    return cast(SectorMemberBreadthHistoryRange, value)


def ordered_member_breadth_reasons(
    reasons: set[SectorMemberBreadthReason],
) -> tuple[SectorMemberBreadthReason, ...]:
    return tuple(
        reason for reason in ALLOWED_MEMBER_BREADTH_REASONS if reason in reasons
    )
