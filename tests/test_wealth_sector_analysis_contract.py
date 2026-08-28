from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchySnapshot,
)
from src.biz.schemas.wealth.market.sector_analysis import (
    SectorAnalysisPageStatusDto,
    SectorAnalysisTradingDayDto,
    SectorMemberDetailResponseDto,
    SectorMemberRowDto,
    SectorMomentumRankingsResponseDto,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorScopeInvalidError,
    resolve_scope_pool,
)


TARGET_DATE = date(2026, 8, 27)


def _node(
    code: str,
    *,
    level: int,
    parent: str | None,
    root: str,
    order: int,
) -> SectorHierarchyNode:
    return SectorHierarchyNode(
        sector_code=code,
        sector_name=code,
        industry_level=level,
        parent_sector_code=parent,
        parent_sector_name=parent,
        root_sector_code=root,
        root_sector_name=root,
        hierarchy_path=code,
        display_order=order,
        is_leaf=level == 3,
        baseline_version="v1",
    )


def _snapshot() -> SectorHierarchySnapshot:
    nodes = (
        _node("BK1001.DC", level=1, parent=None, root="BK1001.DC", order=1),
        _node("BK1002.DC", level=1, parent=None, root="BK1002.DC", order=2),
        _node("BK1101.DC", level=2, parent="BK1001.DC", root="BK1001.DC", order=3),
        _node("BK1102.DC", level=2, parent="BK1001.DC", root="BK1001.DC", order=4),
        _node("BK1201.DC", level=3, parent="BK1101.DC", root="BK1001.DC", order=5),
        _node("BK1202.DC", level=3, parent="BK1101.DC", root="BK1001.DC", order=6),
    )
    children: dict[str | None, tuple[SectorHierarchyNode, ...]] = {}
    for parent in {node.parent_sector_code for node in nodes}:
        children[parent] = tuple(
            node for node in nodes if node.parent_sector_code == parent
        )
    return SectorHierarchySnapshot(
        baseline_version="v1",
        published_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        nodes=nodes,
        nodes_by_code={node.sector_code: node for node in nodes},
        children_by_parent=children,
    )


@pytest.mark.parametrize(
    ("scope", "level1", "level2", "expected"),
    [
        ("LEVEL_1", None, None, ("BK1001.DC", "BK1002.DC")),
        ("LEVEL_2", None, None, ("BK1101.DC", "BK1102.DC")),
        ("LEVEL_3", None, None, ("BK1201.DC", "BK1202.DC")),
        ("LEVEL_1_CHILDREN", "BK1001.DC", None, ("BK1101.DC", "BK1102.DC")),
        (
            "LEVEL_2_CHILDREN",
            "BK1001.DC",
            "BK1101.DC",
            ("BK1201.DC", "BK1202.DC"),
        ),
    ],
)
def test_scope_pool_resolves_the_five_frozen_comparison_sets(
    scope,
    level1,
    level2,
    expected,
) -> None:
    rows = resolve_scope_pool(
        _snapshot(),
        scope=scope,
        level1_code=level1,
        level2_code=level2,
    )

    assert tuple(row.sector_code for row in rows) == expected


@pytest.mark.parametrize(
    ("scope", "level1", "level2"),
    [
        ("LEVEL_1", "BK1001.DC", None),
        ("LEVEL_1_CHILDREN", None, None),
        ("LEVEL_1_CHILDREN", "BK1101.DC", None),
        ("LEVEL_2_CHILDREN", "BK1002.DC", "BK1101.DC"),
    ],
)
def test_scope_pool_rejects_parent_shape_and_closure_errors(
    scope, level1, level2
) -> None:
    with pytest.raises(SectorScopeInvalidError):
        resolve_scope_pool(
            _snapshot(),
            scope=scope,
            level1_code=level1,
            level2_code=level2,
        )


def test_response_contract_rejects_ready_without_ranking() -> None:
    with pytest.raises(ValidationError):
        SectorMomentumRankingsResponseDto(
            status="READY",
            tradingDay=SectorAnalysisTradingDayDto(
                expectedTradeDate=TARGET_DATE,
                observedTradeDate=TARGET_DATE,
                expectedAvailability="COMPLETE",
                expectedSectorCount=2,
                expectedValidSectorCount=2,
                observedAvailability="COMPLETE",
                observedValidSectorCount=2,
            ),
            pageStatus=SectorAnalysisPageStatusDto(
                status="READY",
                displayText="ready",
                asOfTime=datetime(2026, 8, 27, tzinfo=timezone.utc),
            ),
        )


def test_response_contract_rejects_delayed_without_complete_older_observation() -> None:
    with pytest.raises(ValidationError):
        SectorMomentumRankingsResponseDto(
            status="DELAYED",
            tradingDay=SectorAnalysisTradingDayDto(
                expectedTradeDate=TARGET_DATE,
                observedTradeDate=TARGET_DATE,
                expectedAvailability="PARTIAL",
                expectedSectorCount=2,
                expectedValidSectorCount=1,
                observedAvailability="PARTIAL",
                observedValidSectorCount=1,
            ),
            pageStatus=SectorAnalysisPageStatusDto(
                status="DELAYED",
                displayText="delayed",
                asOfTime=datetime(2026, 8, 27, tzinfo=timezone.utc),
            ),
            exceptionCode="SA_SOURCE_DELAYED",
        )


def test_response_contract_allows_zero_count_only_for_unavailable_error_shell() -> None:
    dto = SectorAnalysisTradingDayDto(
        expectedTradeDate=TARGET_DATE,
        expectedAvailability="MISSING",
        expectedSectorCount=0,
        expectedValidSectorCount=0,
        observedValidSectorCount=0,
    )
    assert dto.expectedSectorCount == 0

    with pytest.raises(ValidationError):
        SectorAnalysisTradingDayDto(
            expectedTradeDate=TARGET_DATE,
            observedTradeDate=TARGET_DATE,
            expectedAvailability="MISSING",
            expectedSectorCount=0,
            expectedValidSectorCount=0,
            observedAvailability="MISSING",
            observedValidSectorCount=0,
        )


def test_member_contract_allows_independent_close_and_return_coverage() -> None:
    dto = SectorMemberDetailResponseDto(
        status="READY",
        tradeDate=TARGET_DATE,
        hierarchyVersion="v1",
        sectorCode="BK1201.DC",
        sectorName="三级甲",
        period=5,
        direction="GAINERS",
        totalMemberCount=2,
        closeAvailableCount=1,
        calculableCount=1,
        rows=[
            SectorMemberRowDto(
                stockName="甲",
                stockCode="000001.SZ",
                close=None,
                returnPct=Decimal("2"),
            ),
            SectorMemberRowDto(
                stockName="乙",
                stockCode="000002.SZ",
                close=Decimal("10"),
                returnPct=None,
            ),
        ],
    )
    assert dto.closeAvailableCount == dto.calculableCount == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"totalMemberCount": 1},
        {"closeAvailableCount": 2},
        {"calculableCount": 2},
        {"status": "EMPTY", "exceptionCode": "SA_MEMBER_SOURCE_EMPTY"},
        {
            "rows": [
                SectorMemberRowDto(
                    stockName="乙",
                    stockCode="000002.SZ",
                    close=Decimal("10"),
                    returnPct=None,
                ),
                SectorMemberRowDto(
                    stockName="甲",
                    stockCode="000001.SZ",
                    close=None,
                    returnPct=Decimal("2"),
                ),
            ]
        },
    ],
)
def test_member_contract_rejects_count_state_and_sort_mismatches(changes) -> None:
    values = {
        "status": "READY",
        "tradeDate": TARGET_DATE,
        "hierarchyVersion": "v1",
        "sectorCode": "BK1201.DC",
        "sectorName": "三级甲",
        "period": 5,
        "direction": "GAINERS",
        "totalMemberCount": 2,
        "closeAvailableCount": 1,
        "calculableCount": 1,
        "rows": [
            SectorMemberRowDto(
                stockName="甲",
                stockCode="000001.SZ",
                close=None,
                returnPct=Decimal("2"),
            ),
            SectorMemberRowDto(
                stockName="乙",
                stockCode="000002.SZ",
                close=Decimal("10"),
                returnPct=None,
            ),
        ],
    }
    values.update(changes)
    with pytest.raises(ValidationError):
        SectorMemberDetailResponseDto(**values)
