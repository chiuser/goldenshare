from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchySnapshot,
)
from src.biz.queries.wealth.market.sector_analysis.sector_analysis_fact_reader import (
    SectorAnalysisFactReader,
    SectorMomentumHistorySelection,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    FORMULA_BUNDLE_VERSION,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    FORMULA_KEY,
    FORMULA_VERSION,
    SectorDataQueryError,
)
from src.foundation.models.core_serving.wealth_sector_analysis_publish_batch import (
    WealthSectorAnalysisPublishBatch,
)
from src.foundation.models.core_serving.wealth_sector_hierarchy import (
    WealthSectorHierarchy,
)
from src.foundation.models.core_serving.wealth_sector_momentum_daily import (
    WealthSectorMomentumDaily,
)


TRADE_DATE = date(2026, 8, 28)
HIERARCHY_VERSION = "2026-08-28-v1"
SECTOR_CODES = ("BK1001.DC", "BK1002.DC", "BK1003.DC")


@pytest.fixture()
def momentum_reader_session() -> tuple[Session, SectorHierarchySnapshot]:
    engine = create_engine("sqlite+pysqlite://", future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        WealthSectorHierarchy.__table__.create(connection)
        WealthSectorAnalysisPublishBatch.__table__.create(connection)
        WealthSectorMomentumDaily.__table__.create(connection)

    session = Session(engine, future=True)
    published_at = datetime(2026, 8, 28, 20, 0, tzinfo=timezone.utc)
    nodes = tuple(
        SectorHierarchyNode(
            sector_code=sector_code,
            sector_name=f"一级行业{index}",
            industry_level=1,
            parent_sector_code=None,
            parent_sector_name=None,
            root_sector_code=sector_code,
            root_sector_name=f"一级行业{index}",
            hierarchy_path=f"一级行业{index}",
            display_order=index,
            is_leaf=False,
            baseline_version=HIERARCHY_VERSION,
        )
        for index, sector_code in enumerate(SECTOR_CODES, start=1)
    )
    for node in nodes:
        session.add(
            WealthSectorHierarchy(
                sector_code=node.sector_code,
                sector_name=node.sector_name,
                industry_level=node.industry_level,
                industry_level_name="1级行业",
                parent_sector_code=None,
                parent_sector_name=None,
                root_sector_code=node.root_sector_code,
                root_sector_name=node.root_sector_name,
                hierarchy_path=node.hierarchy_path,
                is_leaf=node.is_leaf,
                display_order=node.display_order,
                baseline_version=HIERARCHY_VERSION,
                source_received_date=TRADE_DATE,
                code_reference_trade_date=TRADE_DATE,
                published_at=published_at,
            )
        )

    batch_id = uuid5(NAMESPACE_URL, f"momentum-reader:{TRADE_DATE.isoformat()}")
    session.add(
        WealthSectorAnalysisPublishBatch(
            batch_id=batch_id,
            trade_date=TRADE_DATE,
            status="PUBLISHED",
            previous_trade_date=None,
            previous_batch_id=None,
            hierarchy_version=HIERARCHY_VERSION,
            formula_bundle_version=FORMULA_BUNDLE_VERSION,
            template_version="sector-daily-insight-template@1",
            source_hash="a" * 64,
            plan_hash="b" * 64,
            content_hash="c" * 64,
            source_dates_json={},
            source_row_counts_json={},
            expected_fact_counts_json={"wealth_sector_momentum_daily": 3},
            actual_fact_counts_json={"wealth_sector_momentum_daily": 3},
            started_at=published_at,
            calculated_at=published_at,
            published_at=published_at,
        )
    )
    for rank, node in enumerate(nodes, start=1):
        session.add(
            WealthSectorMomentumDaily(
                batch_id=batch_id,
                trade_date=TRADE_DATE,
                comparison_scope="LEVEL_1",
                comparison_key="GLOBAL:L1",
                parent_sector_code=None,
                sector_code=node.sector_code,
                sector_name=node.sector_name,
                industry_level=1,
                hierarchy_path=node.hierarchy_path,
                period=20,
                return_pct=Decimal(4 - rank),
                strength_rank=rank,
                rankable_count=3,
                percentile=Decimal(100 - (rank - 1) * 50),
                formula_key=FORMULA_KEY,
                formula_version=FORMULA_VERSION,
                calculation_status="CALCULABLE",
                missing_reason="NONE",
                calculated_at=published_at,
            )
        )
    session.commit()

    snapshot = SectorHierarchySnapshot(
        baseline_version=HIERARCHY_VERSION,
        published_at=published_at,
        nodes=nodes,
        nodes_by_code={node.sector_code: node for node in nodes},
        children_by_parent={None: nodes},
    )
    try:
        yield session, snapshot
    finally:
        session.close()
        engine.dispose()


def _selection(
    *,
    expected_sector_codes: tuple[str, ...] = SECTOR_CODES,
    selected_sector_code: str = "BK1002.DC",
) -> SectorMomentumHistorySelection:
    return SectorMomentumHistorySelection(
        trade_dates=(TRADE_DATE,),
        comparison_scope="LEVEL_1",
        comparison_key="GLOBAL:L1",
        selected_sector_code=selected_sector_code,
        expected_sector_codes=expected_sector_codes,
    )


def test_history_selection_rejects_invalid_dates_scope_pool_and_selected_sector() -> (
    None
):
    with pytest.raises(SectorDataQueryError):
        SectorMomentumHistorySelection(
            trade_dates=(),
            comparison_scope="LEVEL_1",
            comparison_key="GLOBAL:L1",
            selected_sector_code="BK1001.DC",
            expected_sector_codes=SECTOR_CODES,
        )
    with pytest.raises(SectorDataQueryError):
        SectorMomentumHistorySelection(
            trade_dates=(TRADE_DATE, TRADE_DATE),
            comparison_scope="LEVEL_1",
            comparison_key="GLOBAL:L1",
            selected_sector_code="BK1001.DC",
            expected_sector_codes=SECTOR_CODES,
        )
    with pytest.raises(SectorDataQueryError):
        SectorMomentumHistorySelection(
            trade_dates=(TRADE_DATE,),
            comparison_scope="LEVEL_1",
            comparison_key="GLOBAL:L2",
            selected_sector_code="BK1001.DC",
            expected_sector_codes=SECTOR_CODES,
        )
    with pytest.raises(SectorDataQueryError):
        _selection(expected_sector_codes=("BK1001.DC", "BK1001.DC"))
    with pytest.raises(SectorDataQueryError):
        _selection(selected_sector_code="BK9999.DC")
    with pytest.raises(SectorDataQueryError):
        SectorMomentumHistorySelection(
            trade_dates=tuple(date(2026, 1, day) for day in range(1, 29))
            + tuple(date(2026, 2, day) for day in range(1, 29))
            + tuple(date(2026, 3, day) for day in range(1, 6)),
            comparison_scope="LEVEL_1",
            comparison_key="GLOBAL:L1",
            selected_sector_code="BK1001.DC",
            expected_sector_codes=SECTOR_CODES,
        )
    with pytest.raises(SectorDataQueryError):
        SectorMomentumHistorySelection(
            trade_dates=(TRADE_DATE,),
            comparison_scope="LEVEL_1_CHILDREN",
            comparison_key="PARENT:L1:",
            selected_sector_code="BK1001.DC",
            expected_sector_codes=SECTOR_CODES,
        )


def test_history_reader_returns_one_compact_slice_in_one_sql(
    momentum_reader_session,
) -> None:
    session, hierarchy = momentum_reader_session
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    event.listen(session.get_bind(), "before_cursor_execute", record)
    try:
        rows = SectorAnalysisFactReader().load_momentum_history_slices(
            session,
            selections=(_selection(),),
            period=20,
            hierarchy=hierarchy,
        )
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", record)

    assert len(statements) == 1
    assert len(rows) == 1
    row = rows[0]
    assert row.trade_date == TRADE_DATE
    assert row.comparison_key == "GLOBAL:L1"
    assert row.selected_sector_code == "BK1002.DC"
    assert row.selected_return_pct == Decimal("2.000000")
    assert row.selected_strength_rank == 2
    assert row.selected_percentile == Decimal("50.0000")
    assert row.selected_calculation_status == "CALCULABLE"
    assert row.selected_missing_reason == "NONE"
    assert row.row_count == row.calculable_count == 3


def test_history_reader_preserves_group_count_when_selected_sector_is_unavailable(
    momentum_reader_session,
) -> None:
    session, hierarchy = momentum_reader_session
    rows = tuple(
        session.scalars(
            select(WealthSectorMomentumDaily).where(
                WealthSectorMomentumDaily.trade_date == TRADE_DATE,
                WealthSectorMomentumDaily.comparison_key == "GLOBAL:L1",
                WealthSectorMomentumDaily.period == 20,
            )
        )
    )
    selected = next(row for row in rows if row.sector_code == "BK1002.DC")
    selected.return_pct = None
    selected.strength_rank = None
    selected.rankable_count = None
    selected.percentile = None
    selected.calculation_status = "UNAVAILABLE"
    selected.missing_reason = "DATE_MISSING"
    remaining = tuple(row for row in rows if row is not selected)
    for rank, row in enumerate(remaining, start=1):
        row.strength_rank = rank
        row.rankable_count = 2
        row.percentile = Decimal(100 if rank == 1 else 0)
    session.commit()

    result = SectorAnalysisFactReader().load_momentum_history_slices(
        session,
        selections=(_selection(),),
        period=20,
        hierarchy=hierarchy,
    )[0]

    assert result.row_count == 3
    assert result.calculable_count == 2
    assert result.selected_return_pct is None
    assert result.selected_strength_rank is None
    assert result.selected_percentile is None
    assert result.selected_calculation_status == "UNAVAILABLE"
    assert result.selected_missing_reason == "DATE_MISSING"


@pytest.mark.parametrize(
    "corruption",
    (
        "missing_row",
        "unexpected_sector",
        "hierarchy_name",
        "hierarchy_level",
        "hierarchy_path",
        "hierarchy_baseline",
        "parent",
        "formula_version",
        "formula_bundle",
        "nullable",
        "invalid_status",
        "unavailable_with_values",
        "rank_over_denominator",
        "denominator",
    ),
)
def test_history_reader_fails_closed_for_incomplete_or_corrupt_slices(
    momentum_reader_session,
    corruption: str,
) -> None:
    session, hierarchy = momentum_reader_session
    rows = tuple(
        session.scalars(
            select(WealthSectorMomentumDaily).where(
                WealthSectorMomentumDaily.trade_date == TRADE_DATE,
                WealthSectorMomentumDaily.comparison_key == "GLOBAL:L1",
                WealthSectorMomentumDaily.period == 20,
            )
        )
    )
    if corruption == "missing_row":
        session.delete(rows[-1])
    elif corruption == "hierarchy_name":
        rows[0].sector_name = "错误行业名"
    elif corruption == "hierarchy_level":
        session.execute(text("PRAGMA ignore_check_constraints = ON"))
        rows[0].industry_level = 2
    elif corruption == "hierarchy_path":
        rows[0].hierarchy_path = "错误路径"
    elif corruption == "hierarchy_baseline":
        hierarchy_row = session.get(WealthSectorHierarchy, rows[0].sector_code)
        assert hierarchy_row is not None
        hierarchy_row.baseline_version = "wrong-baseline"
    elif corruption == "parent":
        session.execute(text("PRAGMA ignore_check_constraints = ON"))
        rows[0].parent_sector_code = "BK9999.DC"
    elif corruption == "formula_version":
        rows[0].formula_version = FORMULA_VERSION + 1
    elif corruption == "formula_bundle":
        batch = session.scalars(select(WealthSectorAnalysisPublishBatch)).one()
        batch.formula_bundle_version = "wrong-formula-bundle"
    elif corruption == "nullable":
        rows[0].return_pct = None
    elif corruption == "invalid_status":
        session.execute(text("PRAGMA ignore_check_constraints = ON"))
        rows[0].calculation_status = "BROKEN"
    elif corruption == "unavailable_with_values":
        rows[0].calculation_status = "UNAVAILABLE"
        rows[0].missing_reason = "DATE_MISSING"
    elif corruption == "rank_over_denominator":
        session.execute(text("PRAGMA ignore_check_constraints = ON"))
        rows[0].strength_rank = 4
    elif corruption == "denominator":
        for row in rows:
            row.rankable_count = 4
    session.commit()

    expected_codes = (
        SECTOR_CODES[:2] if corruption == "unexpected_sector" else SECTOR_CODES
    )
    with pytest.raises(SectorDataQueryError):
        SectorAnalysisFactReader().load_momentum_history_slices(
            session,
            selections=(_selection(expected_sector_codes=expected_codes),),
            period=20,
            hierarchy=hierarchy,
        )


def test_history_reader_rejects_duplicate_selection_identity(
    momentum_reader_session,
) -> None:
    session, hierarchy = momentum_reader_session
    with pytest.raises(SectorDataQueryError):
        SectorAnalysisFactReader().load_momentum_history_slices(
            session,
            selections=(_selection(), _selection()),
            period=20,
            hierarchy=hierarchy,
        )
