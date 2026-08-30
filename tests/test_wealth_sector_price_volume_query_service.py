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
from src.biz.queries.wealth.market.sector_analysis.sector_price_volume_query_service import (
    SectorPriceVolumeQueryService,
)
from src.biz.queries.wealth.market.sector_analysis.sector_price_volume_query import (
    SectorPriceVolumeQuery,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorDataQueryError,
)
from src.biz.services.wealth.market.sector_analysis.sector_price_volume_contract import (
    SectorPriceVolumeCoverageFacts,
    SectorPriceVolumeDailyFact,
    SectorPriceVolumeDateAvailabilityFact,
    SectorPriceVolumeFactMismatchError,
)


OPEN_DATES = tuple(date(2026, 5, 2) + timedelta(days=index) for index in range(119))
TARGET_DATE = OPEN_DATES[-1]


def _hierarchy() -> SectorHierarchySnapshot:
    raw = (
        ("BK1001.DC", "一级甲", 1, None, None, "BK1001.DC", "一级甲", "一级甲"),
        ("BK1002.DC", "一级乙", 1, None, None, "BK1002.DC", "一级乙", "一级乙"),
        ("BK1101.DC", "二级甲一", 2, "BK1001.DC", "一级甲", "BK1001.DC", "一级甲", "一级甲/二级甲一"),
        ("BK1102.DC", "二级甲二", 2, "BK1001.DC", "一级甲", "BK1001.DC", "一级甲", "一级甲/二级甲二"),
        ("BK1103.DC", "二级乙一", 2, "BK1002.DC", "一级乙", "BK1002.DC", "一级乙", "一级乙/二级乙一"),
        ("BK1201.DC", "三级甲一一", 3, "BK1101.DC", "二级甲一", "BK1001.DC", "一级甲", "一级甲/二级甲一/三级甲一一"),
        ("BK1202.DC", "三级甲一二", 3, "BK1101.DC", "二级甲一", "BK1001.DC", "一级甲", "一级甲/二级甲一/三级甲一二"),
    )
    nodes = tuple(
        SectorHierarchyNode(
            sector_code=code,
            sector_name=name,
            industry_level=level,
            parent_sector_code=parent,
            parent_sector_name=parent_name,
            root_sector_code=root,
            root_sector_name=root_name,
            hierarchy_path=path,
            display_order=index,
            is_leaf=level == 3,
            baseline_version="v1",
        )
        for index, (
            code,
            name,
            level,
            parent,
            parent_name,
            root,
            root_name,
            path,
        ) in enumerate(raw, start=1)
    )
    children: dict[str | None, list[SectorHierarchyNode]] = {}
    for node in nodes:
        children.setdefault(node.parent_sector_code, []).append(node)
    return SectorHierarchySnapshot(
        baseline_version="v1",
        published_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        nodes=nodes,
        nodes_by_code={item.sector_code: item for item in nodes},
        children_by_parent={key: tuple(value) for key, value in children.items()},
    )


class _ContextQuery:
    def resolve_context(self, _session, *, market, requested_trade_date):
        assert market == "CN_A"
        assert requested_trade_date is None
        return MarketPageContext(
            market="CN_A",
            trade_date=TARGET_DATE,
            prev_trade_date=OPEN_DATES[-2],
            is_trading_day=True,
            session_status="CLOSED",
            generated_at=datetime(2026, 8, 28, 20, 1, tzinfo=timezone.utc),
            source="default",
        )


class _HierarchyQuery:
    def load(self, _session):
        return _hierarchy()


class _Query:
    def __init__(self, *, delayed: bool = False) -> None:
        self.delayed = delayed
        self.exact_calls = 0
        self.open_calls: list[int] = []
        self.fact_calls = 0

    def load_trade_date_coverage(self, _session, *, hierarchy_codes, expected_trade_date):
        assert len(hierarchy_codes) == 7
        dates = OPEN_DATES[-3:]
        rows = tuple(
            SectorPriceVolumeDateAvailabilityFact(
                trade_date=item,
                availability="PARTIAL" if self.delayed and item == TARGET_DATE else "COMPLETE",
                expected_sector_count=7,
                valid_sector_count=6 if self.delayed and item == TARGET_DATE else 7,
            )
            for item in dates
        )
        return SectorPriceVolumeCoverageFacts(dates[0], dates[-1], rows)

    def load_exact_trade_date_status(self, _session, *, hierarchy_codes, trade_date):
        self.exact_calls += 1
        assert len(hierarchy_codes) == 7
        return SectorPriceVolumeDateAvailabilityFact(
            trade_date=trade_date,
            availability="COMPLETE",
            expected_sector_count=7,
            valid_sector_count=7,
        )

    def load_open_dates(self, _session, *, end_date, count):
        self.open_calls.append(count)
        return tuple(item for item in OPEN_DATES if item <= end_date)[-count:]

    def load_facts(self, _session, *, sector_codes, start_date, end_date):
        self.fact_calls += 1
        return tuple(
            SectorPriceVolumeDailyFact(
                sector_code=code,
                trade_date=item,
                close=Decimal(100 + code_index * 10 + date_index),
                pct_change=Decimal(code_index),
                amount=Decimal(1000 + code_index * date_index),
            )
            for date_index, item in enumerate(OPEN_DATES)
            for code_index, code in enumerate(sector_codes, start=1)
            if start_date <= item <= end_date
        )


def _service(query: _Query) -> SectorPriceVolumeQueryService:
    return SectorPriceVolumeQueryService(
        context_query=_ContextQuery(),
        hierarchy_query=_HierarchyQuery(),
        price_volume_query=query,
    )


def test_meta_uses_price_amount_coverage_and_returns_delayed_default() -> None:
    response = _service(_Query(delayed=True)).build_meta(None, market="CN_A")
    assert response.dateContext.expectedTradeDate == TARGET_DATE
    assert response.dateContext.defaultTradeDate == OPEN_DATES[-2]
    assert response.dateContext.defaultStatus == "DELAYED"
    assert response.dateCoverageBasis == "INDUSTRY_PRICE_AMOUNT_DAILY"
    assert response.periods == [1, 5, 10, 20, 30]
    assert response.historyRanges == [20, 30, 60]


@pytest.mark.parametrize(
    ("scope", "level1", "level2", "expected_count"),
    (
        ("LEVEL_1", None, None, 2),
        ("LEVEL_2", None, None, 3),
        ("LEVEL_3", None, None, 2),
        ("LEVEL_1_CHILDREN", "BK1001.DC", None, 2),
        ("LEVEL_2_CHILDREN", "BK1001.DC", "BK1101.DC", 2),
    ),
)
def test_snapshot_supports_all_five_scopes_and_keeps_complete_pool(
    scope, level1, level2, expected_count
) -> None:
    query = _Query()
    response = _service(query).build_snapshot(
        None,
        market="CN_A",
        trade_date=TARGET_DATE,
        scope=scope,
        level1_code=level1,
        level2_code=level2,
        period=20,
        hierarchy_version="v1",
        debug=True,
    )
    assert response.status == "READY"
    assert response.snapshot is not None
    assert response.snapshot.totalCount == expected_count
    assert len(response.snapshot.rows) == expected_count
    assert response.snapshot.observedTradeDate == TARGET_DATE
    assert query.open_calls == [40]
    assert query.fact_calls == 1


def test_stale_version_stops_before_coverage_open_dates_or_facts() -> None:
    query = _Query()
    with pytest.raises(SectorPriceVolumeFactMismatchError):
        _service(query).build_snapshot(
            None,
            market="CN_A",
            trade_date=TARGET_DATE,
            scope="LEVEL_1",
            level1_code=None,
            level2_code=None,
            period=20,
            hierarchy_version="stale",
            debug=False,
        )
    assert query.exact_calls == 0
    assert query.open_calls == []
    assert query.fact_calls == 0


def test_details_uses_maximum_119_dates_and_returns_sixty_ascending_slots() -> None:
    query = _Query()
    response = _service(query).build_details(
        None,
        market="CN_A",
        trade_date=TARGET_DATE,
        scope="LEVEL_1",
        level1_code=None,
        level2_code=None,
        period=30,
        history_range=60,
        sector_code="BK1001.DC",
        hierarchy_version="v1",
        debug=True,
    )
    assert response.status == "READY"
    assert response.details is not None
    assert query.open_calls == [119]
    assert len(response.details.history) == 60
    assert response.details.history[-1].tradeDate == TARGET_DATE
    assert [item.tradeDate for item in response.details.history] == sorted(
        item.tradeDate for item in response.details.history
    )
    assert response.debugInfo is not None
    assert response.debugInfo.requestedOpenDateCount == 119
    assert response.debugInfo.loadedOpenDateCount == 119


def test_open_date_query_accepts_119_and_rejects_120_before_database_access() -> None:
    class _ScalarRows:
        @staticmethod
        def all():
            return []

    class _Session:
        @staticmethod
        def scalars(_statement):
            return _ScalarRows()

    assert SectorPriceVolumeQuery.load_open_dates(
        _Session(),  # type: ignore[arg-type]
        end_date=TARGET_DATE,
        count=119,
    ) == ()
    with pytest.raises(SectorDataQueryError):
        SectorPriceVolumeQuery.load_open_dates(
            None,  # type: ignore[arg-type]
            end_date=TARGET_DATE,
            count=120,
        )


def test_maximum_level_three_snapshot_keeps_all_337_rows_under_payload_budget() -> None:
    parent = SectorHierarchyNode(
        sector_code="BK2000.DC",
        sector_name="一级样本",
        industry_level=1,
        parent_sector_code=None,
        parent_sector_name=None,
        root_sector_code="BK2000.DC",
        root_sector_name="一级样本",
        hierarchy_path="一级样本",
        display_order=1,
        is_leaf=False,
        baseline_version="v1",
    )
    level_two = SectorHierarchyNode(
        sector_code="BK2001.DC",
        sector_name="二级样本",
        industry_level=2,
        parent_sector_code=parent.sector_code,
        parent_sector_name=parent.sector_name,
        root_sector_code=parent.sector_code,
        root_sector_name=parent.sector_name,
        hierarchy_path="一级样本/二级样本",
        display_order=2,
        is_leaf=False,
        baseline_version="v1",
    )
    leaves = tuple(
        SectorHierarchyNode(
            sector_code=f"BK{2100 + index:04d}.DC",
            sector_name=f"三级样本{index + 1}",
            industry_level=3,
            parent_sector_code=level_two.sector_code,
            parent_sector_name=level_two.sector_name,
            root_sector_code=parent.sector_code,
            root_sector_name=parent.sector_name,
            hierarchy_path=f"一级样本/二级样本/三级样本{index + 1}",
            display_order=index + 3,
            is_leaf=True,
            baseline_version="v1",
        )
        for index in range(337)
    )
    nodes = (parent, level_two, *leaves)
    hierarchy = SectorHierarchySnapshot(
        baseline_version="v1",
        published_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        nodes=nodes,
        nodes_by_code={item.sector_code: item for item in nodes},
        children_by_parent={
            None: (parent,),
            parent.sector_code: (level_two,),
            level_two.sector_code: leaves,
        },
    )

    class _LargeHierarchyQuery:
        def load(self, _session):
            return hierarchy

    class _LargeQuery(_Query):
        def load_exact_trade_date_status(
            self, _session, *, hierarchy_codes, trade_date
        ):
            self.exact_calls += 1
            return SectorPriceVolumeDateAvailabilityFact(
                trade_date=trade_date,
                availability="COMPLETE",
                expected_sector_count=len(hierarchy_codes),
                valid_sector_count=len(hierarchy_codes),
            )

    response = SectorPriceVolumeQueryService(
        context_query=_ContextQuery(),
        hierarchy_query=_LargeHierarchyQuery(),
        price_volume_query=_LargeQuery(),
    ).build_snapshot(
        None,
        market="CN_A",
        trade_date=TARGET_DATE,
        scope="LEVEL_3",
        level1_code=None,
        level2_code=None,
        period=30,
        hierarchy_version="v1",
        debug=False,
    )

    assert response.status == "READY"
    assert response.snapshot is not None
    assert response.snapshot.totalCount == 337
    assert response.snapshot.coordinateCount == 337
    assert len(response.model_dump_json().encode()) <= 256 * 1024
