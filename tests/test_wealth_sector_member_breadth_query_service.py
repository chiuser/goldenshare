from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.dialects import postgresql

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchySnapshot,
    SectorHierarchyUnavailableError,
)
from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContext,
)
from src.biz.queries.wealth.market.sector_analysis.sector_analysis_meta_query_service import (
    SectorAnalysisMetaFacts,
)
from src.biz.queries.wealth.market.sector_analysis.sector_member_breadth_query_service import (
    SectorMemberBreadthQueryService,
)
from src.biz.queries.wealth.market.sector_analysis.sector_member_breadth_query import (
    SectorMemberBreadthQuery,
)
from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_contract import (
    MemberBreadthDailyProjectionFact,
    MemberBreadthDetailsProjectionFact,
    MemberBreadthDetailsWindowFact,
    MemberBreadthMemberProjectionFact,
    MemberBreadthWindowRelationsFact,
    MemberMarketFact,
    MemberRelationFact,
    SectorMemberBreadthDetailsRequest,
    SectorMemberBreadthFactMismatchError,
    SectorMemberBreadthRankingsRequest,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorDateAvailabilityFact,
    SectorScopeInvalidError,
    SectorSelectionInvalidError,
)


TARGET_DATE = date(2026, 8, 28)
VERSION = "dc-industry-v1"


def _node(
    code: str,
    name: str,
    level: int,
    *,
    parent: str | None,
    root: str,
    order: int,
) -> SectorHierarchyNode:
    return SectorHierarchyNode(
        sector_code=code,
        sector_name=name,
        industry_level=level,
        parent_sector_code=parent,
        parent_sector_name=None,
        root_sector_code=root,
        root_sector_name="一级甲" if root == "BK1001.DC" else "一级乙",
        hierarchy_path=name,
        display_order=order,
        is_leaf=level == 3,
        baseline_version=VERSION,
    )


def _hierarchy() -> SectorHierarchySnapshot:
    nodes = (
        _node("BK1001.DC", "一级甲", 1, parent=None, root="BK1001.DC", order=1),
        _node("BK1002.DC", "一级乙", 1, parent=None, root="BK1002.DC", order=2),
        _node(
            "BK1101.DC", "二级甲一", 2, parent="BK1001.DC", root="BK1001.DC", order=3
        ),
        _node(
            "BK1102.DC", "二级甲二", 2, parent="BK1001.DC", root="BK1001.DC", order=4
        ),
        _node(
            "BK1103.DC", "二级乙一", 2, parent="BK1002.DC", root="BK1002.DC", order=5
        ),
        _node(
            "BK1201.DC", "三级甲一", 3, parent="BK1101.DC", root="BK1001.DC", order=6
        ),
        _node(
            "BK1202.DC", "三级甲二", 3, parent="BK1101.DC", root="BK1001.DC", order=7
        ),
    )
    by_code = {node.sector_code: node for node in nodes}
    children: dict[str | None, tuple[SectorHierarchyNode, ...]] = {}
    for parent in {node.parent_sector_code for node in nodes}:
        children[parent] = tuple(
            node for node in nodes if node.parent_sector_code == parent
        )
    return SectorHierarchySnapshot(
        baseline_version=VERSION,
        published_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        nodes=nodes,
        nodes_by_code=by_code,
        children_by_parent=children,
    )


def _context() -> MarketPageContext:
    return MarketPageContext(
        market="CN_A",
        trade_date=TARGET_DATE,
        prev_trade_date=TARGET_DATE - timedelta(days=1),
        is_trading_day=True,
        session_status="CLOSED",
        generated_at=datetime(2026, 8, 28, 20, 0, tzinfo=timezone.utc),
        source="default",
    )


class _HierarchyQuery:
    def __init__(self, hierarchy: SectorHierarchySnapshot | None = None) -> None:
        self.hierarchy = hierarchy or _hierarchy()
        self.calls = 0

    def load(self, _session) -> SectorHierarchySnapshot:
        self.calls += 1
        return self.hierarchy


class _UnavailableHierarchyQuery:
    def load(self, _session) -> SectorHierarchySnapshot:
        raise SectorHierarchyUnavailableError("sensitive hierarchy details")


class _ContextQuery:
    def __init__(self) -> None:
        self.calls = 0

    def resolve_context(self, _session, *, market, requested_trade_date):
        self.calls += 1
        assert market == "CN_A"
        assert requested_trade_date is None
        return _context()


class _MetaService:
    def __init__(self, availability: tuple[str, ...]) -> None:
        self.availability = availability

    def load(self, _session, *, market) -> SectorAnalysisMetaFacts:
        assert market == "CN_A"
        dates = tuple(
            TARGET_DATE - timedelta(days=len(self.availability) - index - 1)
            for index in range(len(self.availability))
        )
        hierarchy = _hierarchy()
        return SectorAnalysisMetaFacts(
            context=_context(),
            hierarchy=hierarchy,
            coverage_start_date=dates[0],
            coverage_end_date=dates[-1],
            trade_dates=tuple(
                SectorDateAvailabilityFact(
                    trade_date=item,
                    availability=status,  # type: ignore[arg-type]
                    expected_sector_count=len(hierarchy.nodes),
                    valid_sector_count=(
                        len(hierarchy.nodes)
                        if status == "COMPLETE"
                        else 1
                        if status == "PARTIAL"
                        else 0
                    ),
                )
                for item, status in zip(dates, self.availability, strict=True)
            ),
        )


class _FactQuery:
    def __init__(self, *, empty_relations: bool = False, fail: bool = False) -> None:
        self.empty_relations = empty_relations
        self.fail = fail
        self.window_calls: list[dict] = []
        self.market_calls: list[dict] = []
        self.details_window_calls: list[dict] = []
        self.details_projection_calls: list[dict] = []

    def load_window_relations(self, _session, **kwargs):
        if self.fail:
            raise RuntimeError("sensitive sql details")
        self.window_calls.append(kwargs)
        open_dates = tuple(
            kwargs["target_date"]
            - timedelta(days=kwargs["open_date_count"] - index - 1)
            for index in range(kwargs["open_date_count"])
        )
        relation_dates = open_dates[-kwargs["relation_date_count"] :]
        relations = ()
        if not self.empty_relations:
            relations = tuple(
                MemberRelationFact(
                    sector_code=sector_code,
                    trade_date=item,
                    stock_code=f"{sector_index:02d}{stock_index:04d}.SZ",
                    stock_name=f"股票{stock_index}",
                )
                for item in relation_dates
                for sector_index, sector_code in enumerate(
                    kwargs["relation_sector_codes"], start=1
                )
                for stock_index in range(1, 6)
            )
        return MemberBreadthWindowRelationsFact(
            coverage_start_date=TARGET_DATE - timedelta(days=200),
            coverage_end_date=kwargs["coverage_end_date"],
            open_dates=open_dates,
            relation_dates=relation_dates,
            relations=relations,
        )

    def load_market_facts(self, _session, **kwargs):
        self.market_calls.append(kwargs)
        dates = tuple(
            kwargs["start_date"] + timedelta(days=index)
            for index in range((kwargs["end_date"] - kwargs["start_date"]).days + 1)
        )
        return tuple(
            MemberMarketFact(
                stock_code=stock_code,
                trade_date=item,
                close=Decimal("10"),
                pct_change=Decimal("1"),
                amount_thousand_yuan=Decimal("100"),
                adj_factor=Decimal("1") if kwargs["include_adj_factor"] else None,
            )
            for item in dates
            for stock_code in kwargs["stock_codes"]
        )

    def load_details_window(self, _session, **kwargs):
        if self.fail:
            raise RuntimeError("sensitive sql details")
        self.details_window_calls.append(kwargs)
        open_dates = tuple(
            kwargs["target_date"]
            - timedelta(days=kwargs["open_date_count"] - index - 1)
            for index in range(kwargs["open_date_count"])
        )
        relation_dates = open_dates[-kwargs["relation_date_count"] :]
        return MemberBreadthDetailsWindowFact(
            coverage_start_date=TARGET_DATE - timedelta(days=200),
            coverage_end_date=kwargs["coverage_end_date"],
            open_dates=open_dates,
            relation_dates=relation_dates,
            target_source_count=0 if self.empty_relations else 5,
        )

    def load_details_projection(self, _session, **kwargs):
        if self.fail:
            raise RuntimeError("sensitive sql details")
        self.details_projection_calls.append(kwargs)
        daily = tuple(
            MemberBreadthDailyProjectionFact(
                trade_date=item,
                source_count=5,
                member_calculable_count=5,
                member_up_count=5,
                member_flat_count=0,
                member_down_count=0,
                turnover_calculable_count=5,
                turnover_up_count=5,
                turnover_flat_count=0,
                turnover_down_count=0,
                turnover_up_amount=Decimal("500"),
                turnover_flat_amount=Decimal(0),
                turnover_down_amount=Decimal(0),
                ma_calculable_count=5,
                ma_above_count=0,
                ma_equal_count=5,
                ma_below_count=0,
                member_source_reasons=(),
                turnover_source_reasons=(),
                ma_source_reasons=(),
            )
            for item in kwargs["relation_dates"]
        )
        members = tuple(
            MemberBreadthMemberProjectionFact(
                trade_date=kwargs["target_date"],
                stock_code=f"01{index:04d}.SZ",
                stock_name=f"股票{index}",
                daily_pct_change=Decimal(1),
                amount_thousand_yuan=Decimal(100),
                current_adjusted_basis=Decimal(10),
                rolling_adjusted_sum=Decimal(10) * kwargs["ma_period"],
                rolling_slot_count=kwargs["ma_period"],
                rolling_valid_count=kwargs["ma_period"],
                source_reasons=(),
            )
            for index in range(1, 6)
        )
        return MemberBreadthDetailsProjectionFact(daily=daily, members=members)


class _CaptureProjectionStatementSession:
    def __init__(self) -> None:
        self.sql: str | None = None

    def execute(self, statement):
        self.sql = str(statement.compile(dialect=postgresql.dialect()))
        raise RuntimeError("statement captured")


@pytest.mark.parametrize(
    ("availability", "status", "default_date"),
    [
        (("COMPLETE",), "READY", TARGET_DATE),
        (("COMPLETE", "PARTIAL"), "DELAYED", TARGET_DATE - timedelta(days=1)),
        (("MISSING",), "EMPTY", None),
    ],
)
def test_meta_uses_public_coverage_for_ready_delayed_and_empty(
    availability,
    status,
    default_date,
) -> None:
    response = SectorMemberBreadthQueryService(
        meta_service=_MetaService(availability)
    ).build_meta(object(), market="CN_A")

    assert response.dateContext.defaultStatus == status
    assert response.dateContext.defaultTradeDate == default_date
    assert response.maPeriods == [5, 10, 15, 20, 30, 60]
    assert response.metrics == ["MEMBER_COUNT", "TURNOVER", "MA_POSITION"]


def test_stale_version_stops_before_public_date_and_source_queries() -> None:
    hierarchy_query = _HierarchyQuery()
    context_query = _ContextQuery()
    fact_query = _FactQuery()
    service = SectorMemberBreadthQueryService(
        hierarchy_query=hierarchy_query,
        context_query=context_query,
        query=fact_query,
    )

    with pytest.raises(SectorMemberBreadthFactMismatchError):
        service.build_rankings(
            object(),
            request=_ranking_request(hierarchy_version="stale"),
        )

    assert hierarchy_query.calls == 1
    assert context_query.calls == 0
    assert fact_query.window_calls == []
    assert fact_query.market_calls == []


@pytest.mark.parametrize(
    ("scope", "level1_code", "level2_code", "expected_count"),
    [
        ("LEVEL_1", None, None, 2),
        ("LEVEL_2", None, None, 3),
        ("LEVEL_3", None, None, 2),
        ("LEVEL_1_CHILDREN", "BK1001.DC", None, 2),
        ("LEVEL_2_CHILDREN", "BK1001.DC", "BK1101.DC", 2),
    ],
)
def test_rankings_support_all_five_scopes(
    scope,
    level1_code,
    level2_code,
    expected_count,
) -> None:
    response = SectorMemberBreadthQueryService(
        hierarchy_query=_HierarchyQuery(),
        context_query=_ContextQuery(),
        query=_FactQuery(),
    ).build_rankings(
        object(),
        request=_ranking_request(
            scope=scope,
            level1_code=level1_code,
            level2_code=level2_code,
        ),
    )

    assert response.status == "READY"
    assert response.totalSectorCount == expected_count
    assert len(response.rows) == expected_count
    assert response.eligibleSectorCount == expected_count


@pytest.mark.parametrize(
    ("metric", "expected_open_count", "include_factor"),
    [
        ("MEMBER_COUNT", 1, False),
        ("TURNOVER", 1, False),
        ("MA_POSITION", 30, True),
    ],
)
def test_rankings_only_projects_the_requested_metric_inputs(
    metric,
    expected_open_count,
    include_factor,
) -> None:
    fact_query = _FactQuery()
    response = SectorMemberBreadthQueryService(
        hierarchy_query=_HierarchyQuery(),
        context_query=_ContextQuery(),
        query=fact_query,
    ).build_rankings(
        object(),
        request=_ranking_request(metric=metric, ma_period=30),
    )

    assert response.status == "READY"
    assert fact_query.window_calls[0]["open_date_count"] == expected_open_count
    assert fact_query.market_calls[0]["include_adj_factor"] is include_factor


def test_details_use_119_day_window_and_keep_three_independent_compositions() -> None:
    fact_query = _FactQuery()
    response = SectorMemberBreadthQueryService(
        hierarchy_query=_HierarchyQuery(),
        context_query=_ContextQuery(),
        query=fact_query,
    ).build_details(
        object(),
        request=_details_request(ma_period=60, history_range=60),
    )

    assert response.status == "READY"
    assert fact_query.details_window_calls[0]["open_date_count"] == 119
    assert fact_query.details_window_calls[0]["relation_date_count"] == 60
    assert fact_query.details_projection_calls[0]["ma_period"] == 60
    assert [item.metric for item in response.compositions] == [
        "MEMBER_COUNT",
        "TURNOVER",
        "MA_POSITION",
    ]
    assert len(response.trend) == 60


def test_query_rejects_a_120_day_open_window_before_sql() -> None:
    with pytest.raises(SectorSelectionInvalidError, match="1 到 119"):
        SectorMemberBreadthQuery.load_window_relations(
            object(),  # type: ignore[arg-type]
            target_date=TARGET_DATE,
            coverage_end_date=TARGET_DATE,
            hierarchy_sector_codes=("BK1001.DC",),
            relation_sector_codes=("BK1001.DC",),
            open_date_count=120,
            relation_date_count=60,
        )

    with pytest.raises(SectorSelectionInvalidError, match="1 到 119"):
        SectorMemberBreadthQuery.load_details_window(
            object(),  # type: ignore[arg-type]
            target_date=TARGET_DATE,
            coverage_end_date=TARGET_DATE,
            hierarchy_sector_codes=("BK1001.DC",),
            sector_code="BK1001.DC",
            open_date_count=120,
            relation_date_count=60,
        )


def test_details_projection_compiles_for_postgresql_without_a_dialect_branch() -> None:
    session = _CaptureProjectionStatementSession()

    with pytest.raises(RuntimeError, match="statement captured"):
        SectorMemberBreadthQuery.load_details_projection(
            session,  # type: ignore[arg-type]
            sector_code="BK1001.DC",
            target_date=TARGET_DATE,
            open_dates=tuple(
                TARGET_DATE - timedelta(days=19 - index) for index in range(20)
            ),
            relation_dates=tuple(
                TARGET_DATE - timedelta(days=19 - index) for index in range(20)
            ),
            ma_period=20,
        )

    assert session.sql is not None
    lowered = session.sql.lower()
    assert "with" in lowered
    assert "rows between" in lowered
    assert "union all" in lowered
    assert "sqlite" not in lowered


def test_details_source_empty_and_query_failure_use_safe_local_shells() -> None:
    common = {
        "hierarchy_query": _HierarchyQuery(),
        "context_query": _ContextQuery(),
    }
    empty = SectorMemberBreadthQueryService(
        **common,
        query=_FactQuery(empty_relations=True),
    ).build_details(object(), request=_details_request())
    failed = SectorMemberBreadthQueryService(
        **common,
        query=_FactQuery(fail=True),
    ).build_details(object(), request=_details_request())

    assert empty.status == "EMPTY"
    assert empty.exceptionCode == "SA_BREADTH_SOURCE_EMPTY"
    assert failed.status == "ERROR"
    assert failed.exceptionCode == "SA_BREADTH_QUERY_FAILED"
    assert "sensitive" not in (failed.message or "")


def test_hierarchy_unavailable_has_a_distinct_safe_error_for_business_responses() -> (
    None
):
    service = SectorMemberBreadthQueryService(
        hierarchy_query=_UnavailableHierarchyQuery(),
        context_query=_ContextQuery(),
        query=_FactQuery(),
    )

    rankings = service.build_rankings(object(), request=_ranking_request())
    details = service.build_details(object(), request=_details_request())

    assert rankings.status == "ERROR"
    assert rankings.exceptionCode == "SA_HIERARCHY_UNAVAILABLE"
    assert rankings.rows == []
    assert details.status == "ERROR"
    assert details.exceptionCode == "SA_HIERARCHY_UNAVAILABLE"
    assert details.compositions == []
    assert details.trend == []
    assert details.members == []
    assert "sensitive" not in (rankings.message or "")
    assert "sensitive" not in (details.message or "")


def test_invalid_scope_and_sector_are_not_silently_replaced() -> None:
    service = SectorMemberBreadthQueryService(
        hierarchy_query=_HierarchyQuery(),
        context_query=_ContextQuery(),
        query=_FactQuery(),
    )
    with pytest.raises(SectorScopeInvalidError):
        service.build_rankings(
            object(),
            request=_ranking_request(
                scope="LEVEL_1_CHILDREN",
                level1_code=None,
            ),
        )
    with pytest.raises(SectorSelectionInvalidError):
        service.build_details(
            object(),
            request=_details_request(sector_code="BK9999.DC"),
        )


def _ranking_request(**changes) -> SectorMemberBreadthRankingsRequest:
    values = {
        "market": "CN_A",
        "trade_date": TARGET_DATE,
        "scope": "LEVEL_1",
        "level1_code": None,
        "level2_code": None,
        "direction": "UP",
        "metric": "MEMBER_COUNT",
        "ma_period": 20,
        "hierarchy_version": VERSION,
    }
    values.update(changes)
    return SectorMemberBreadthRankingsRequest(**values)  # type: ignore[arg-type]


def _details_request(**changes) -> SectorMemberBreadthDetailsRequest:
    values = {
        "market": "CN_A",
        "trade_date": TARGET_DATE,
        "sector_code": "BK1001.DC",
        "direction": "UP",
        "ma_period": 20,
        "history_range": 20,
        "hierarchy_version": VERSION,
    }
    values.update(changes)
    return SectorMemberBreadthDetailsRequest(**values)  # type: ignore[arg-type]
