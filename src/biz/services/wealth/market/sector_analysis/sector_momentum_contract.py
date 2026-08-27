from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, cast

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchySnapshot,
)


SectorMomentumScope = Literal[
    "LEVEL_1",
    "LEVEL_2",
    "LEVEL_3",
    "LEVEL_1_CHILDREN",
    "LEVEL_2_CHILDREN",
]
SectorMomentumDirection = Literal["GAINERS", "LOSERS"]
SectorMomentumPeriod = Literal[1, 5, 10, 20, 30]
SectorHistoryRange = Literal[20, 30, 60]
SectorAvailability = Literal["COMPLETE", "PARTIAL", "MISSING"]
MissingReason = Literal[
    "NONE",
    "HISTORY_INSUFFICIENT",
    "DATE_MISSING",
    "CLOSE_MISSING",
    "CLOSE_NON_POSITIVE",
    "PCT_CHANGE_MISSING",
]

FORMULA_KEY = "sector-cross-sectional-momentum"
FORMULA_VERSION = 1
ALLOWED_SCOPES: tuple[SectorMomentumScope, ...] = (
    "LEVEL_1",
    "LEVEL_2",
    "LEVEL_3",
    "LEVEL_1_CHILDREN",
    "LEVEL_2_CHILDREN",
)
ALLOWED_DIRECTIONS: tuple[SectorMomentumDirection, ...] = ("GAINERS", "LOSERS")
ALLOWED_PERIODS: tuple[SectorMomentumPeriod, ...] = (1, 5, 10, 20, 30)
ALLOWED_HISTORY_RANGES: tuple[SectorHistoryRange, ...] = (20, 30, 60)


class SectorScopeInvalidError(ValueError):
    pass


class SectorSelectionInvalidError(ValueError):
    pass


class SectorDataQueryError(RuntimeError):
    pass


class DuplicateSectorFactError(SectorDataQueryError):
    pass


@dataclass(frozen=True, slots=True)
class SectorDailyFact:
    sector_code: str
    trade_date: date
    close: Decimal | None
    pct_change: Decimal | None


@dataclass(frozen=True, slots=True)
class SectorReturnFact:
    sector_code: str
    trade_date: date
    return_pct: Decimal | None
    missing_reason: MissingReason


@dataclass(frozen=True, slots=True)
class SectorRankFact:
    sector_code: str
    return_pct: Decimal | None
    strength_rank: int | None
    percentile: Decimal | None


@dataclass(frozen=True, slots=True)
class SectorDateAvailabilityFact:
    trade_date: date
    availability: SectorAvailability
    expected_sector_count: int
    valid_sector_count: int


@dataclass(frozen=True, slots=True)
class SectorTradingDateResolution:
    coverage_start_date: date
    coverage_end_date: date
    expected: SectorDateAvailabilityFact
    observed: SectorDateAvailabilityFact | None
    is_explicit: bool


def classify_availability(*, valid_count: int, expected_count: int) -> SectorAvailability:
    if expected_count <= 0 or valid_count < 0 or valid_count > expected_count:
        raise SectorDataQueryError("invalid sector coverage counts")
    if valid_count == expected_count:
        return "COMPLETE"
    if valid_count == 0:
        return "MISSING"
    return "PARTIAL"


def resolve_scope_pool(
    snapshot: SectorHierarchySnapshot,
    *,
    scope: SectorMomentumScope,
    level1_code: str | None,
    level2_code: str | None,
) -> tuple[SectorHierarchyNode, ...]:
    _validate_parent_arguments(scope=scope, level1_code=level1_code, level2_code=level2_code)
    if scope in {"LEVEL_1", "LEVEL_2", "LEVEL_3"}:
        level = int(scope[-1])
        nodes = tuple(node for node in snapshot.nodes if node.industry_level == level)
    elif scope == "LEVEL_1_CHILDREN":
        parent = _require_node(snapshot, level1_code, expected_level=1, field_name="level1Code")
        nodes = tuple(
            node
            for node in snapshot.children_by_parent.get(parent.sector_code, ())
            if node.industry_level == 2
        )
    else:
        level1 = _require_node(snapshot, level1_code, expected_level=1, field_name="level1Code")
        level2 = _require_node(snapshot, level2_code, expected_level=2, field_name="level2Code")
        if level2.parent_sector_code != level1.sector_code:
            raise SectorScopeInvalidError("level2Code 必须是 level1Code 的直属二级行业")
        nodes = tuple(
            node
            for node in snapshot.children_by_parent.get(level2.sector_code, ())
            if node.industry_level == 3
        )
    if not nodes:
        raise SectorScopeInvalidError("当前比较范围没有行业")
    return tuple(sorted(nodes, key=lambda node: (node.display_order, node.sector_code)))


def global_level_pool(
    snapshot: SectorHierarchySnapshot,
    *,
    industry_level: int,
) -> tuple[SectorHierarchyNode, ...]:
    return tuple(
        sorted(
            (node for node in snapshot.nodes if node.industry_level == industry_level),
            key=lambda node: (node.display_order, node.sector_code),
        )
    )


def parent_pool(
    snapshot: SectorHierarchySnapshot,
    *,
    node: SectorHierarchyNode,
) -> tuple[SectorHierarchyNode, ...] | None:
    if node.industry_level == 1:
        return None
    return tuple(
        sorted(
            (
                child
                for child in snapshot.children_by_parent.get(node.parent_sector_code, ())
                if child.industry_level == node.industry_level
            ),
            key=lambda child: (child.display_order, child.sector_code),
        )
    )


def scope_title(
    *,
    scope: SectorMomentumScope,
    level1_name: str | None,
    level2_name: str | None,
) -> str:
    titles = {
        "LEVEL_1": "一级行业总榜",
        "LEVEL_2": "二级行业总榜",
        "LEVEL_3": "三级行业总榜",
        "LEVEL_1_CHILDREN": f"{level1_name or '--'}内二级行业",
        "LEVEL_2_CHILDREN": f"{level2_name or '--'}内三级行业",
    }
    return titles[scope]


def parse_scope(value: str) -> SectorMomentumScope:
    if value not in ALLOWED_SCOPES:
        raise SectorScopeInvalidError(f"scope 不支持：{value}")
    return cast(SectorMomentumScope, value)


def parse_direction(value: str) -> SectorMomentumDirection:
    if value not in ALLOWED_DIRECTIONS:
        raise SectorScopeInvalidError(f"direction 不支持：{value}")
    return cast(SectorMomentumDirection, value)


def parse_period(value: int) -> SectorMomentumPeriod:
    if value not in ALLOWED_PERIODS:
        raise SectorScopeInvalidError(f"period 不支持：{value}")
    return cast(SectorMomentumPeriod, value)


def parse_history_range(value: int) -> SectorHistoryRange:
    if value not in ALLOWED_HISTORY_RANGES:
        raise SectorScopeInvalidError(f"historyRange 不支持：{value}")
    return cast(SectorHistoryRange, value)


def _validate_parent_arguments(
    *,
    scope: SectorMomentumScope,
    level1_code: str | None,
    level2_code: str | None,
) -> None:
    if scope in {"LEVEL_1", "LEVEL_2", "LEVEL_3"} and (level1_code or level2_code):
        raise SectorScopeInvalidError("全层级总榜不接受父级参数")
    if scope == "LEVEL_1_CHILDREN" and (level1_code is None or level2_code is not None):
        raise SectorScopeInvalidError("LEVEL_1_CHILDREN 只接受 level1Code")
    if scope == "LEVEL_2_CHILDREN" and (level1_code is None or level2_code is None):
        raise SectorScopeInvalidError("LEVEL_2_CHILDREN 必须同时提供 level1Code 和 level2Code")


def _require_node(
    snapshot: SectorHierarchySnapshot,
    code: str | None,
    *,
    expected_level: int,
    field_name: str,
) -> SectorHierarchyNode:
    node = snapshot.nodes_by_code.get(code or "")
    if node is None or node.industry_level != expected_level:
        raise SectorScopeInvalidError(f"{field_name} 不是合法的 {expected_level} 级行业")
    return node
