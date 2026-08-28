from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchySnapshot,
)
from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContext,
)
from src.biz.queries.wealth.market.sector_analysis.sector_momentum_snapshot_query_service import (
    SectorMomentumSnapshotQueryService,
)
from src.biz.queries.wealth.market.sector_analysis.sector_momentum_query_service import (
    SectorMomentumQueryService,
)
from src.biz.services.wealth.market.sector_analysis.sector_dual_momentum_contract import (
    SectorMomentumFactVersionMismatchError,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorDailyFact,
    SectorDateAvailabilityFact,
    SectorScopeInvalidError,
    SectorSelectionInvalidError,
    SectorTradingDateResolution,
)


TARGET_DATE = date(2026, 8, 27)
OPEN_DATES = tuple(TARGET_DATE - timedelta(days=offset) for offset in range(5, -1, -1))


def _context() -> MarketPageContext:
    return MarketPageContext(
        market="CN_A",
        trade_date=TARGET_DATE,
        prev_trade_date=OPEN_DATES[-2],
        is_trading_day=True,
        session_status="CLOSED",
        generated_at=datetime(2026, 8, 27, 20, 1, tzinfo=timezone.utc),
        source="default",
    )


def _hierarchy() -> SectorHierarchySnapshot:
    nodes = tuple(
        SectorHierarchyNode(
            sector_code=code,
            sector_name=name,
            industry_level=1,
            parent_sector_code=None,
            parent_sector_name=None,
            root_sector_code=code,
            root_sector_name=name,
            hierarchy_path=name,
            display_order=display_order,
            is_leaf=True,
            baseline_version="v1",
        )
        for code, name, display_order in (
            ("BK1002.DC", "行业乙", 2),
            ("BK1001.DC", "行业甲", 1),
            ("BK1003.DC", "行业丙", 3),
        )
    )
    return SectorHierarchySnapshot(
        baseline_version="v1",
        published_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        nodes=nodes,
        nodes_by_code={node.sector_code: node for node in nodes},
        children_by_parent={None: nodes},
    )


class _ContextQuery:
    def resolve_context(self, _session, *, market, requested_trade_date):
        assert market == "CN_A"
        assert requested_trade_date is None
        return _context()


class _HierarchyQuery:
    def load(self, _session):
        return _hierarchy()


class _MomentumQuery:
    def __init__(self, *, missing: bool = False, invalid_date: bool = False) -> None:
        self.missing = missing
        self.invalid_date = invalid_date
        self.resolve_calls = 0
        self.open_calls = 0
        self.fact_calls = 0

    def resolve_trading_date(self, _session, **_kwargs):
        self.resolve_calls += 1
        if self.invalid_date:
            raise SectorScopeInvalidError("tradeDate 必须是 SSE 开市日")
        expected = SectorDateAvailabilityFact(
            trade_date=TARGET_DATE,
            availability="MISSING" if self.missing else "COMPLETE",
            expected_sector_count=3,
            valid_sector_count=0 if self.missing else 3,
        )
        return SectorTradingDateResolution(
            coverage_start_date=OPEN_DATES[0],
            coverage_end_date=TARGET_DATE,
            expected=expected,
            observed=expected,
            is_explicit=True,
        )

    def load_open_dates(self, _session, **_kwargs):
        self.open_calls += 1
        return OPEN_DATES

    def load_facts(self, _session, **_kwargs):
        self.fact_calls += 1
        facts = []
        for code, start, end in (
            ("BK1001.DC", "100", "110"),
            ("BK1002.DC", "100", "105"),
            ("BK1003.DC", "100", None),
        ):
            for trade_date in OPEN_DATES:
                if end is None and trade_date == TARGET_DATE:
                    continue
                close = end if trade_date == TARGET_DATE else start
                facts.append(
                    SectorDailyFact(
                        code,
                        trade_date,
                        Decimal(close),
                        Decimal("0"),
                    )
                )
        return tuple(facts)


def _service(query: _MomentumQuery) -> SectorMomentumSnapshotQueryService:
    return SectorMomentumSnapshotQueryService(
        context_query=_ContextQuery(),
        hierarchy_query=_HierarchyQuery(),
        momentum_query=query,  # type: ignore[arg-type]
    )


def test_snapshot_keeps_scope_order_and_missing_rows_without_extra_reads() -> None:
    query = _MomentumQuery()
    snapshot = _service(query).build(
        object(),  # type: ignore[arg-type]
        market="CN_A",
        trade_date=TARGET_DATE,
        scope="LEVEL_1",
        level1_code=None,
        level2_code=None,
        period=5,
    )

    assert [row.node.sector_code for row in snapshot.rows] == [
        "BK1001.DC",
        "BK1002.DC",
        "BK1003.DC",
    ]
    assert [row.return_fact.return_pct for row in snapshot.rows] == [
        Decimal("10.0000"),
        Decimal("5.0000"),
        None,
    ]
    assert [row.rank_fact.strength_rank for row in snapshot.rows] == [1, 2, None]
    assert snapshot.rows[-1].return_fact.missing_reason == "DATE_MISSING"
    assert query.resolve_calls == query.open_calls == query.fact_calls == 1


def test_snapshot_version_mismatch_stops_before_date_and_daily_queries() -> None:
    query = _MomentumQuery()

    with pytest.raises(SectorMomentumFactVersionMismatchError):
        _service(query).build(
            object(),  # type: ignore[arg-type]
            market="CN_A",
            trade_date=TARGET_DATE,
            scope="LEVEL_1",
            level1_code=None,
            level2_code=None,
            period=5,
            expected_hierarchy_version="stale",
        )

    assert query.resolve_calls == query.open_calls == query.fact_calls == 0


def test_explicit_missing_snapshot_keeps_all_rows_and_skips_window_queries() -> None:
    query = _MomentumQuery(missing=True)
    snapshot = _service(query).build(
        object(),  # type: ignore[arg-type]
        market="CN_A",
        trade_date=TARGET_DATE,
        scope="LEVEL_1",
        level1_code=None,
        level2_code=None,
        period=5,
    )

    assert len(snapshot.rows) == 3
    assert all(row.return_fact.return_pct is None for row in snapshot.rows)
    assert all(row.return_fact.missing_reason == "DATE_MISSING" for row in snapshot.rows)
    assert query.resolve_calls == 1
    assert query.open_calls == query.fact_calls == 0


def test_dual_date_mode_converts_only_date_resolution_errors() -> None:
    query = _MomentumQuery(invalid_date=True)

    with pytest.raises(SectorSelectionInvalidError):
        _service(query).build(
            object(),  # type: ignore[arg-type]
            market="CN_A",
            trade_date=TARGET_DATE,
            scope="LEVEL_1",
            level1_code=None,
            level2_code=None,
            period=5,
            date_errors_are_selection=True,
        )


def test_existing_rankings_contract_is_preserved_on_the_shared_snapshot() -> None:
    query = _MomentumQuery()
    response = SectorMomentumQueryService(
        context_query=_ContextQuery(),
        hierarchy_query=_HierarchyQuery(),
        momentum_query=query,  # type: ignore[arg-type]
    ).build_rankings(
        object(),  # type: ignore[arg-type]
        market="CN_A",
        trade_date=TARGET_DATE,
        scope="LEVEL_1",
        level1_code=None,
        level2_code=None,
        period=5,
        direction="GAINERS",
        debug=True,
    )

    payload = response.model_dump(mode="json")
    assert payload["status"] == "READY"
    assert payload["exceptionCode"] is None
    assert payload["ranking"]["formulaKey"] == "sector-cross-sectional-momentum"
    assert payload["ranking"]["formulaVersion"] == 1
    assert payload["ranking"]["hierarchyVersion"] == "v1"
    assert payload["ranking"]["totalCount"] == 3
    assert payload["ranking"]["calculableCount"] == 2
    assert [row["sectorCode"] for row in payload["ranking"]["rows"]] == [
        "BK1001.DC",
        "BK1002.DC",
        "BK1003.DC",
    ]
    assert payload["ranking"]["rows"][-1]["returnPct"] is None
    assert query.resolve_calls == query.open_calls == query.fact_calls == 1
