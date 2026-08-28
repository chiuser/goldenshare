from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchySnapshot,
)
from src.biz.queries.wealth.market.sector_analysis.sector_member_detail_query_service import (
    SectorMemberDetailQueryService,
)
from src.biz.services.wealth.market.sector_analysis.sector_member_detail_contract import (
    SectorMemberDailyFact,
    SectorMemberDetailRequest,
    SectorMemberFactMismatchError,
    SectorMemberSourceFact,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorSelectionInvalidError,
)


TARGET_DATE = date(2026, 8, 27)


def _snapshot(*, level: int = 3) -> SectorHierarchySnapshot:
    node = SectorHierarchyNode(
        sector_code="BK1201.DC",
        sector_name="三级甲",
        industry_level=level,
        parent_sector_code="BK1101.DC",
        parent_sector_name="二级甲",
        root_sector_code="BK1001.DC",
        root_sector_name="一级甲",
        hierarchy_path="一级甲/二级甲/三级甲",
        display_order=1,
        is_leaf=level == 3,
        baseline_version="v1",
    )
    return SectorHierarchySnapshot(
        baseline_version="v1",
        published_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        nodes=(node,),
        nodes_by_code={node.sector_code: node},
        children_by_parent={node.parent_sector_code: (node,)},
    )


class _HierarchyQuery:
    def __init__(self, snapshot: SectorHierarchySnapshot) -> None:
        self.snapshot = snapshot

    def load(self, _session):
        return self.snapshot


class _MemberQuery:
    def __init__(self, *, empty: bool = False, fail: bool = False) -> None:
        self.empty = empty
        self.fail = fail
        self.calls: list[str] = []

    def load_open_window(self, _session, **_kwargs):
        self.calls.append("dates")
        return (TARGET_DATE,)

    def load_members(self, _session, **_kwargs):
        self.calls.append("members")
        if self.fail:
            raise RuntimeError("SELECT secret FROM private_table")
        if self.empty:
            return ()
        return (SectorMemberSourceFact("000001.SZ", "甲"),)

    def load_daily_facts(self, _session, **_kwargs):
        self.calls.append("daily")
        return (
            SectorMemberDailyFact(
                stock_code="000001.SZ",
                trade_date=TARGET_DATE,
                close=Decimal("10"),
                pct_change=Decimal("2"),
            ),
        )


def _request(*, version: str = "v1") -> SectorMemberDetailRequest:
    return SectorMemberDetailRequest(
        market="CN_A",
        trade_date=TARGET_DATE,
        hierarchy_version=version,
        sector_code="BK1201.DC",
        period=1,
        direction="GAINERS",
    )


def test_version_mismatch_stops_before_member_and_market_queries() -> None:
    query = _MemberQuery()
    service = SectorMemberDetailQueryService(
        hierarchy_query=_HierarchyQuery(_snapshot()),
        member_query=query,
    )

    with pytest.raises(SectorMemberFactMismatchError):
        service.build_members(object(), request=_request(version="old"))  # type: ignore[arg-type]

    assert query.calls == []


def test_non_level_three_selection_is_rejected() -> None:
    service = SectorMemberDetailQueryService(
        hierarchy_query=_HierarchyQuery(_snapshot(level=2)),
        member_query=_MemberQuery(),
    )

    with pytest.raises(SectorSelectionInvalidError):
        service.build_members(object(), request=_request())  # type: ignore[arg-type]


def test_empty_and_error_responses_are_local_safe_shells() -> None:
    empty_query = _MemberQuery(empty=True)
    empty = SectorMemberDetailQueryService(
        hierarchy_query=_HierarchyQuery(_snapshot()),
        member_query=empty_query,
    ).build_members(object(), request=_request())  # type: ignore[arg-type]
    assert empty.status == "EMPTY"
    assert empty.exceptionCode == "SA_MEMBER_SOURCE_EMPTY"
    assert empty_query.calls == ["dates", "members"]

    failed_query = _MemberQuery(fail=True)
    failed = SectorMemberDetailQueryService(
        hierarchy_query=_HierarchyQuery(_snapshot()),
        member_query=failed_query,
    ).build_members(object(), request=_request())  # type: ignore[arg-type]
    assert failed.status == "ERROR"
    assert failed.exceptionCode == "SA_MEMBER_QUERY_FAILED"
    assert "SELECT" not in (failed.message or "")
