from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

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
from src.biz.queries.wealth.market.sector_analysis.sector_analysis_fact_reader import (
    SectorPublishedBreadthRow,
    SectorPublishedBreadthDay,
    SectorPublishedCoverage,
    SectorPublishedCalendarDate,
    _breadth_composition,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import SectorDataQueryError
from src.biz.queries.wealth.market.sector_analysis.sector_member_breadth_query_service import (
    SectorMemberBreadthQueryService,
)
from src.biz.queries.wealth.market.sector_analysis.sector_member_breadth_query import (
    SectorMemberBreadthQuery,
)
from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_contract import (
    MemberBreadthCompositionFact,
    MetricCoverageFact,
    MemberBreadthMemberProjectionFact,
    SectorMemberBreadthDetailsRequest,
    SectorMemberBreadthFactMismatchError,
    SectorMemberBreadthRankingsRequest,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorDateAvailabilityFact,
    resolve_scope_pool,
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


class _FactReader:
    def __init__(
        self, *, statuses=("COMPLETE",), published=None, empty=False, fail=False
    ):
        self.statuses = statuses
        self.published = published if published is not None else (True,) * len(statuses)
        self.empty = empty
        self.fail = fail
        self.calls = []

    def load_momentum_coverage(self, _session, *, coverage_end_date, hierarchy):
        self.calls.append(("coverage", coverage_end_date))
        days = tuple(
            TARGET_DATE - timedelta(days=len(self.statuses) - i - 1)
            for i in range(len(self.statuses))
        )
        return SectorPublishedCoverage(
            days[0],
            days[-1],
            tuple(
                SectorPublishedCalendarDate(
                    SectorDateAvailabilityFact(
                        day,
                        status,
                        7,
                        7 if status == "COMPLETE" else 1 if status == "PARTIAL" else 0,
                    ),
                    UUID(int=i + 1) if published else None,
                )
                for i, (day, status, published) in enumerate(
                    zip(days, self.statuses, self.published, strict=True)
                )
            ),
        )

    def load_breadth_rankings(self, _session, **kwargs):
        self.calls.append(("rankings", kwargs))
        if self.fail:
            raise RuntimeError("sensitive SQL password")
        pool = resolve_scope_pool(
            kwargs["hierarchy"],
            scope=kwargs["scope"],
            level1_code=kwargs["level1_code"],
            level2_code=kwargs["level2_code"],
        )
        return tuple(
            SectorPublishedBreadthRow(
                node.sector_code, _composition(kwargs["metric"]), 1, len(pool)
            )
            for node in sorted(pool, key=lambda n: n.sector_code)
        )

    def load_breadth_history(self, _session, **kwargs):
        self.calls.append(("history", kwargs))
        if self.fail:
            raise RuntimeError("sensitive SQL password")
        return tuple(
            SectorPublishedBreadthDay(
                TARGET_DATE - timedelta(days=offset),
                UUID(int=1),
                tuple(
                    _composition(metric, empty=self.empty)
                    for metric in ("MEMBER_COUNT", "TURNOVER", "MA_POSITION")
                ),
            )
            for offset in reversed(range(kwargs["history_range"]))
        )


def _composition(metric, *, empty=False):
    return MemberBreadthCompositionFact(
        metric,
        0 if empty else 5,
        0,
        0,
        None if empty else Decimal("100"),
        None if empty else Decimal(0),
        None if empty else Decimal(0),
        MetricCoverageFact(
            0 if empty else 5,
            0 if empty else 5,
            Decimal(0 if empty else 100),
            not empty,
            ("SOURCE_MEMBER_EMPTY",) if empty else (),
        ),
    )


class _FactQuery:
    def __init__(self):
        self.calls = []

    def load_member_projection(self, _session, **kwargs):
        self.calls.append(kwargs)
        return (
            MemberBreadthMemberProjectionFact(
                TARGET_DATE,
                "000001.SZ",
                "股票甲",
                Decimal(1),
                Decimal(100),
                Decimal(11),
                Decimal(10 * kwargs["ma_period"]),
                kwargs["ma_period"],
                kwargs["ma_period"],
                (),
            ),
        )


def _service(*, reader=None, query=None, hierarchy=None, context=None):
    return SectorMemberBreadthQueryService(
        hierarchy_query=hierarchy or _HierarchyQuery(),
        context_query=context or _ContextQuery(),
        fact_reader=reader or _FactReader(),
        query=query or _FactQuery(),
    )


@pytest.mark.parametrize(
    ("statuses", "published", "status", "default_date"),
    [
        (("COMPLETE",), (True,), "READY", TARGET_DATE),
        (("COMPLETE", "PARTIAL"), (True, True), "READY", TARGET_DATE),
        (("COMPLETE", "MISSING"), (True, True), "READY", TARGET_DATE),
        (
            ("PARTIAL", "MISSING"),
            (True, False),
            "DELAYED",
            TARGET_DATE - timedelta(days=1),
        ),
        (("MISSING",), (False,), "EMPTY", None),
    ],
)
def test_meta_selects_published_not_complete_day(
    statuses, published, status, default_date
):
    response = _service(
        reader=_FactReader(statuses=statuses, published=published)
    ).build_meta(object(), market="CN_A")
    assert response.dateContext.defaultStatus == status
    assert response.dateContext.defaultTradeDate == default_date
    assert response.maPeriods == [5, 10, 15, 20, 30, 60]


def test_stale_version_stops_before_context_and_facts():
    context, reader, query = _ContextQuery(), _FactReader(), _FactQuery()
    with pytest.raises(SectorMemberBreadthFactMismatchError):
        _service(reader=reader, query=query, context=context).build_rankings(
            object(), request=_ranking_request(hierarchy_version="stale")
        )
    assert context.calls == 0 and reader.calls == [] and query.calls == []


@pytest.mark.parametrize(
    ("scope", "l1", "l2", "count"),
    [
        ("LEVEL_1", None, None, 2),
        ("LEVEL_2", None, None, 3),
        ("LEVEL_3", None, None, 2),
        ("LEVEL_1_CHILDREN", "BK1001.DC", None, 2),
        ("LEVEL_2_CHILDREN", "BK1001.DC", "BK1101.DC", 2),
    ],
)
@pytest.mark.parametrize("metric", ["MEMBER_COUNT", "TURNOVER", "MA_POSITION"])
@pytest.mark.parametrize("direction", ["UP", "DOWN"])
def test_rankings_only_read_requested_materialized_pool(
    scope, l1, l2, count, metric, direction
):
    reader, query = _FactReader(), _FactQuery()
    response = _service(reader=reader, query=query).build_rankings(
        object(),
        request=_ranking_request(
            scope=scope,
            level1_code=l1,
            level2_code=l2,
            metric=metric,
            direction=direction,
            ma_period=60,
        ),
    )
    assert response.status == "READY"
    assert len(response.rows) == response.eligibleSectorCount == count
    assert reader.calls[-1][1]["metric"] == metric
    assert reader.calls[-1][1]["direction"] == direction
    assert reader.calls[-1][1]["ma_period"] == 60
    assert query.calls == []


def test_explicit_unpublished_date_does_not_fallback_or_compute():
    reader, query = (
        _FactReader(statuses=("COMPLETE", "MISSING"), published=(True, False)),
        _FactQuery(),
    )
    result = _service(reader=reader, query=query).build_rankings(
        object(), request=_ranking_request()
    )
    assert result.status == "EMPTY"
    assert result.tradeDate == TARGET_DATE and len(result.rows) == 2
    assert all(row.reasonCodes == ["MARKET_ROW_MISSING"] for row in result.rows)
    assert [call[0] for call in reader.calls] == ["coverage"]
    assert query.calls == []


@pytest.mark.parametrize("history_range", [20, 30, 60])
@pytest.mark.parametrize("ma_period", [5, 10, 15, 20, 30, 60])
def test_details_read_history_but_only_current_members(history_range, ma_period):
    reader, query = _FactReader(), _FactQuery()
    response = _service(reader=reader, query=query).build_details(
        object(),
        request=_details_request(ma_period=ma_period, history_range=history_range),
    )
    assert response.status == "READY"
    assert len(response.trend) == history_range
    assert [row.metric for row in response.compositions] == [
        "MEMBER_COUNT",
        "TURNOVER",
        "MA_POSITION",
    ]
    assert response.members[0].maRelation == "ABOVE"
    assert query.calls == [
        dict(sector_code="BK1001.DC", target_date=TARGET_DATE, ma_period=ma_period)
    ]
    assert reader.calls[0][1]["history_range"] == history_range


def test_empty_and_failed_details_are_safe_and_do_not_read_stocks():
    query = _FactQuery()
    empty = _service(reader=_FactReader(empty=True), query=query).build_details(
        object(), request=_details_request()
    )
    failed = _service(reader=_FactReader(fail=True), query=query).build_details(
        object(), request=_details_request()
    )
    assert empty.status == "EMPTY" and empty.exceptionCode == "SA_BREADTH_SOURCE_EMPTY"
    assert (
        failed.status == "ERROR" and failed.exceptionCode == "SA_BREADTH_QUERY_FAILED"
    )
    assert "sensitive" not in failed.message
    assert query.calls == []


def test_hierarchy_failure_preserves_safe_shells():
    service = _service(hierarchy=_UnavailableHierarchyQuery())
    for response in (
        service.build_rankings(object(), request=_ranking_request()),
        service.build_details(object(), request=_details_request()),
    ):
        assert (
            response.status == "ERROR"
            and response.exceptionCode == "SA_HIERARCHY_UNAVAILABLE"
        )


def test_invalid_scope_sector_and_future_are_not_replaced():
    service = _service()
    with pytest.raises(SectorScopeInvalidError):
        service.build_rankings(
            object(), request=_ranking_request(scope="LEVEL_1_CHILDREN")
        )
    with pytest.raises(SectorSelectionInvalidError):
        service.build_details(
            object(), request=_details_request(sector_code="BK9999.DC")
        )
    with pytest.raises(SectorSelectionInvalidError):
        service.build_details(
            object(),
            request=_details_request(trade_date=TARGET_DATE + timedelta(days=1)),
        )


class _CaptureProjectionStatementSession:
    def execute(self, statement):
        self.compiled = statement.compile(dialect=postgresql.dialect())
        raise RuntimeError("statement captured")


def test_member_projection_bounds_stock_history_and_never_aggregates_industry_history():
    session = _CaptureProjectionStatementSession()
    with pytest.raises(RuntimeError, match="statement captured"):
        SectorMemberBreadthQuery.load_member_projection(
            session, sector_code="BK1001.DC", target_date=TARGET_DATE, ma_period=60
        )
    sql = str(session.compiled).lower()
    assert "rows between" in sql and "limit" in sql
    assert "dc_member.trade_date =" in sql and "dc_member.ts_code =" in sql
    assert "union all" not in sql and "dc_daily" not in sql
    assert 60 in session.compiled.params.values()
    assert TARGET_DATE in session.compiled.params.values()
    assert "sqlite" not in sql


def test_member_projection_rejects_unapproved_period_before_read():
    with pytest.raises(SectorSelectionInvalidError):
        SectorMemberBreadthQuery.load_member_projection(
            object(), sector_code="BK1001.DC", target_date=TARGET_DATE, ma_period=120
        )


def _stored_composition(**changes):
    values = dict(source_count=6, calculable_count=6, coverage_pct=Decimal(100),
                  qualification="ELIGIBLE", reason_codes=[], up_count=2, flat_count=2, down_count=2,
                  up_pct=Decimal("33.3333"), flat_pct=Decimal("33.3333"), down_pct=Decimal("33.3333"))
    values.update(changes)
    return values


def test_stored_composition_accepts_rounding_without_recomputing():
    result = _breadth_composition(_stored_composition(), "MEMBER_COUNT")
    assert result.up_pct == result.flat_pct == result.down_pct == Decimal("33.3333")
    result = _breadth_composition(_stored_composition(source_count=7, coverage_pct=Decimal("85.7143")), "MA_POSITION")
    assert result.coverage.coverage_pct == Decimal("85.7143")


@pytest.mark.parametrize("change", [
    dict(up_pct=Decimal("NaN")), dict(up_pct=Decimal("100.1")), dict(up_pct=None),
    dict(up_count=3), dict(coverage_pct=Decimal("99.9999")),
    dict(up_pct=Decimal("33.3332")), dict(qualification="INELIGIBLE"),
    dict(reason_codes=["UNKNOWN"]), dict(reason_codes=["AMOUNT_MISSING", "AMOUNT_MISSING"]),
])
def test_stored_composition_rejects_actual_contract_drift(change):
    with pytest.raises(SectorDataQueryError):
        _breadth_composition(_stored_composition(**change), "MEMBER_COUNT")


def test_stored_zero_turnover_retains_unavailable_even_when_coverage_is_complete():
    result = _breadth_composition(_stored_composition(
        up_pct=None, flat_pct=None, down_pct=None, qualification="INELIGIBLE",
        reason_codes=["AMOUNT_NON_POSITIVE"],
    ), "TURNOVER")
    assert result.coverage.calculable_count == 6 and result.coverage.coverage_pct == 100
    assert not result.coverage.eligible and result.up_pct is None


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
