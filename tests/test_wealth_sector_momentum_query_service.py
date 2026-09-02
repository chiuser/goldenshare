from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import pytest

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchySnapshot,
    SectorHierarchyUnavailableError,
)
from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContext
from src.biz.queries.wealth.market.sector_analysis.sector_momentum_query_service import (
    SectorMomentumQueryService,
)
from src.biz.queries.wealth.market.sector_analysis.sector_analysis_fact_reader import (
    SectorAnalysisFactReader,
    SectorPublishedCalendarDate,
    SectorPublishedCoverage,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorDateAvailabilityFact,
    SectorSelectionInvalidError,
)


TARGET_DATE = date(2026, 8, 27)


def _context() -> MarketPageContext:
    return MarketPageContext(
        market="CN_A",
        trade_date=TARGET_DATE,
        prev_trade_date=date(2026, 8, 26),
        is_trading_day=True,
        session_status="CLOSED",
        generated_at=datetime(2026, 8, 27, 20, 1, tzinfo=timezone.utc),
        source="default",
    )


def _snapshot() -> SectorHierarchySnapshot:
    node = SectorHierarchyNode(
        sector_code="BK1001.DC",
        sector_name="一级行业",
        industry_level=1,
        parent_sector_code=None,
        parent_sector_name=None,
        root_sector_code="BK1001.DC",
        root_sector_name="一级行业",
        hierarchy_path="一级行业",
        display_order=1,
        is_leaf=False,
        baseline_version="v1",
    )
    return SectorHierarchySnapshot(
        baseline_version="v1",
        published_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        nodes=(node,),
        nodes_by_code={node.sector_code: node},
        children_by_parent={None: (node,)},
    )


class _ContextQuery:
    def resolve_context(self, _session, *, market, requested_trade_date):
        assert market == "CN_A"
        assert requested_trade_date is None
        return _context()


class _HierarchyQuery:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def load(self, _session):
        if self.fail:
            raise SectorHierarchyUnavailableError("sensitive hierarchy failure")
        return _snapshot()


class _MissingFactReader:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.open_date_calls = 0
        self.row_calls = 0

    def load_momentum_coverage(self, _session, **_kwargs):
        if self.fail:
            raise RuntimeError("SELECT secret FROM private_table")
        previous = SectorDateAvailabilityFact(
            trade_date=date(2026, 8, 26),
            availability="COMPLETE",
            expected_sector_count=1,
            valid_sector_count=1,
        )
        missing = SectorDateAvailabilityFact(
            trade_date=TARGET_DATE,
            availability="MISSING",
            expected_sector_count=1,
            valid_sector_count=0,
        )
        return SectorPublishedCoverage(
            coverage_start_date=date(2026, 1, 1),
            coverage_end_date=TARGET_DATE,
            calendar_dates=(
                SectorPublishedCalendarDate(
                    availability=previous,
                    batch_id=UUID("00000000-0000-0000-0000-000000000001"),
                ),
                SectorPublishedCalendarDate(
                    availability=missing,
                    batch_id=None,
                ),
            ),
        )

    def load_open_dates(self, *_args, **_kwargs):
        self.open_date_calls += 1
        return ()

    def load_momentum_rows(self, *_args, **_kwargs):
        self.row_calls += 1
        return ()

    resolve_trading_date = staticmethod(SectorAnalysisFactReader.resolve_trading_date)


def _service(*, hierarchy_fail: bool = False, query_fail: bool = False):
    reader = _MissingFactReader(fail=query_fail)
    return (
        SectorMomentumQueryService(
            context_query=_ContextQuery(),
            hierarchy_query=_HierarchyQuery(fail=hierarchy_fail),
            fact_reader=reader,  # type: ignore[arg-type]
        ),
        reader,
    )


def test_explicit_missing_date_returns_empty_before_window_or_fact_query() -> None:
    service, query = _service()

    response = service.build_rankings(
        object(),  # type: ignore[arg-type]
        market="CN_A",
        trade_date=TARGET_DATE,
        scope="LEVEL_1",
        level1_code=None,
        level2_code=None,
        period=1,
        direction="GAINERS",
        debug=True,
    )

    assert response.status == "EMPTY"
    assert response.exceptionCode == "SA_SOURCE_EMPTY"
    assert response.tradingDay.observedTradeDate == TARGET_DATE
    assert query.open_date_calls == 0
    assert query.row_calls == 0


def test_hierarchy_failure_returns_safe_error_shell_for_rankings() -> None:
    service, query = _service(hierarchy_fail=True)

    response = service.build_rankings(
        object(),  # type: ignore[arg-type]
        market="CN_A",
        trade_date=None,
        scope="LEVEL_1",
        level1_code=None,
        level2_code=None,
        period=1,
        direction="GAINERS",
        debug=True,
    )

    assert response.status == "ERROR"
    assert response.exceptionCode == "SA_HIERARCHY_UNAVAILABLE"
    assert "sensitive" not in (response.message or "")
    assert response.tradingDay.expectedSectorCount == 0
    assert query.open_date_calls == 0


def test_query_failure_returns_safe_error_shell_without_technical_payload() -> None:
    service, _query = _service(query_fail=True)

    response = service.build_rankings(
        object(),  # type: ignore[arg-type]
        market="CN_A",
        trade_date=TARGET_DATE,
        scope="LEVEL_1",
        level1_code=None,
        level2_code=None,
        period=1,
        direction="GAINERS",
        debug=True,
    )

    assert response.status == "ERROR"
    assert response.exceptionCode == "SA_QUERY_FAILED"
    assert "SELECT" not in (response.message or "")
    assert response.ranking is None


def test_history_selection_error_is_not_hidden_as_query_error() -> None:
    service, _query = _service()

    with pytest.raises(SectorSelectionInvalidError):
        service.build_history(
            object(),  # type: ignore[arg-type]
            market="CN_A",
            trade_date=TARGET_DATE,
            scope="LEVEL_1",
            level1_code=None,
            level2_code=None,
            period=1,
            history_range=20,
            sector_code="BK1101.DC",
            debug=False,
        )
