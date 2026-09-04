from __future__ import annotations


from datetime import date, datetime, timezone
from dataclasses import replace
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
from src.foundation.models.core_serving.wealth_sector_dual_momentum_daily import (
    WealthSectorDualMomentumDaily,
)
from src.foundation.models.core_serving.wealth_sector_price_volume_daily import WealthSectorPriceVolumeDaily


TRADE_DATE = date(2026, 8, 28)
HIERARCHY_VERSION = "2026-08-28-v1"
SECTOR_CODES = ("BK1001.DC", "BK1002.DC", "BK1003.DC")


@pytest.fixture()
def price_volume_reader_session(momentum_reader_session):
    session, hierarchy = momentum_reader_session
    WealthSectorPriceVolumeDaily.__table__.create(session.get_bind())
    for source in session.scalars(select(WealthSectorMomentumDaily)):
        for period in (1, 5, 10, 20, 30):
            session.add(WealthSectorPriceVolumeDaily(
                **{name: getattr(source, name) for name in (
                    "batch_id", "trade_date", "comparison_scope", "comparison_key", "parent_sector_code",
                    "sector_code", "sector_name", "industry_level", "hierarchy_path", "calculated_at",
                )}, period=period, price_momentum_pct=source.return_pct,
                amount_activity_pct=source.return_pct, price_rank=source.strength_rank,
                amount_rank=source.strength_rank, price_rankable_count=3, amount_rankable_count=3,
                price_missing_reason=None, amount_missing_reason=None, distribution_state="JOINT",
                formula_key="sector-price-volume-distribution", formula_version=1,
                calculation_status="CALCULABLE", missing_reason="NONE",
            ))
    session.commit()
    return session, hierarchy


def _read_price_volume(session, hierarchy, **overrides):
    params = dict(batch_id=uuid5(NAMESPACE_URL, f"momentum-reader:{TRADE_DATE.isoformat()}"),
                  trade_date=TRADE_DATE, scope="LEVEL_1", level1_code=None, level2_code=None,
                  period=20, hierarchy=hierarchy)
    params.update(overrides)
    return SectorAnalysisFactReader().load_price_volume_rows(session, **params)


@pytest.mark.parametrize("period", [1, 5, 10, 20, 30])
def test_price_volume_reader_one_sql_exact_period_without_source_tables(price_volume_reader_session, period):
    session, hierarchy = price_volume_reader_session
    statements = []
    def record(_c, _cur, sql, _p, _ctx, _many):
        statements.append(sql)
    event.listen(session.get_bind(), "before_cursor_execute", record)
    try:
        rows = _read_price_volume(session, hierarchy, period=period)
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", record)
    assert len(statements) == 1 and len(rows) == 3
    assert [r.price_rank for r in rows] == [1, 2, 3]
    assert all(r.period == period for r in rows)
    assert "wealth_sector_price_volume_daily" in statements[0]
    assert "dc_daily" not in statements[0]


@pytest.mark.parametrize(("field", "value"), [
    ("sector_name", "错误名称"), ("hierarchy_path", "错误路径"), ("price_rank", 0),
    ("formula_key", "wrong"), ("formula_version", 2), ("missing_reason", "DATE_MISSING"),
    ("price_missing_reason", "UNKNOWN"), ("price_rank", 4), ("price_rankable_count", 2),
    ("distribution_state", "NEUTRAL"), ("calculation_status", "UNAVAILABLE"),
    ("price_momentum_pct", None), ("amount_rankable_count", None),
])
def test_price_volume_reader_rejects_malformed_published_row(price_volume_reader_session, field, value):
    session, hierarchy = price_volume_reader_session
    row = session.scalar(select(WealthSectorPriceVolumeDaily).where(
        WealthSectorPriceVolumeDaily.sector_code == SECTOR_CODES[0],
        WealthSectorPriceVolumeDaily.period == 20,
    ))
    setattr(row, field, value)
    session.commit()
    with pytest.raises(SectorDataQueryError):
        _read_price_volume(session, hierarchy)


@pytest.mark.parametrize("field", ["hierarchy_version", "formula_bundle_version"])
def test_price_volume_reader_rejects_wrong_batch_identity(price_volume_reader_session, field):
    session, hierarchy = price_volume_reader_session
    row = session.scalar(select(WealthSectorAnalysisPublishBatch))
    setattr(row, field, "wrong")
    session.commit()
    with pytest.raises(SectorDataQueryError):
        _read_price_volume(session, hierarchy)


@pytest.mark.parametrize("damage", ["missing", "unpublished", "wrong_period", "wrong_key"])
def test_price_volume_reader_rejects_missing_slice_without_fallback(price_volume_reader_session, damage):
    session, hierarchy = price_volume_reader_session
    row = session.scalar(select(WealthSectorPriceVolumeDaily).where(WealthSectorPriceVolumeDaily.period == 20))
    if damage == "missing":
        session.delete(row)
    elif damage == "unpublished":
        session.scalar(select(WealthSectorAnalysisPublishBatch)).status = "SUPERSEDED"
    elif damage == "wrong_period":
        session.delete(row)
        # Other periods remain present but must never substitute this slice.
    else:
        row.comparison_key = "GLOBAL:L2"
        row.comparison_scope = "LEVEL_2"
        row.industry_level = 2
    session.commit()
    with pytest.raises(SectorDataQueryError):
        _read_price_volume(session, hierarchy)


@pytest.mark.parametrize("missing_prefix", ["price", "amount"])
def test_price_volume_reader_preserves_independent_missing(price_volume_reader_session, missing_prefix):
    session, hierarchy = price_volume_reader_session
    rows = session.scalars(select(WealthSectorPriceVolumeDaily).where(WealthSectorPriceVolumeDaily.period == 20)).all()
    missing = rows[-1]
    field = "price_momentum_pct" if missing_prefix == "price" else "amount_activity_pct"
    reason = "CLOSE_MISSING" if missing_prefix == "price" else "AMOUNT_MISSING"
    setattr(missing, field, None)
    setattr(missing, f"{missing_prefix}_rank", None)
    setattr(missing, f"{missing_prefix}_rankable_count", None)
    setattr(missing, f"{missing_prefix}_missing_reason", reason)
    missing.distribution_state = None
    missing.calculation_status = "UNAVAILABLE"
    missing.missing_reason = reason
    for row in rows[:-1]:
        setattr(row, f"{missing_prefix}_rankable_count", 2)
    session.commit()
    result = _read_price_volume(session, hierarchy)[-1]
    assert getattr(result, field) is None and result.distribution_state is None
    other = "amount_activity_pct" if missing_prefix == "price" else "price_momentum_pct"
    assert getattr(result, other) == Decimal(1)


@pytest.mark.parametrize(("price", "amount", "state"), [
    ("0", "0", "NEUTRAL"), ("1", "0", "PRICE_ONLY"),
    ("0", "1", "AMOUNT_ONLY"), ("1", "1", "JOINT"),
])
def test_price_volume_reader_retains_zero_values_and_published_states(price_volume_reader_session, price, amount, state):
    session, hierarchy = price_volume_reader_session
    row = session.scalar(select(WealthSectorPriceVolumeDaily).where(WealthSectorPriceVolumeDaily.period == 20))
    row.price_momentum_pct, row.amount_activity_pct = Decimal(price), Decimal(amount)
    row.distribution_state = state
    session.commit()
    result = _read_price_volume(session, hierarchy)[0]
    assert (result.price_momentum_pct, result.amount_activity_pct, result.distribution_state) == (Decimal(price), Decimal(amount), state)


def test_price_volume_history_reads_only_selected_industry_and_bounds_dates(price_volume_reader_session):
    session, hierarchy = price_volume_reader_session
    source = _read_price_volume(session, hierarchy)[0]
    for row in session.scalars(select(WealthSectorPriceVolumeDaily).where(
        WealthSectorPriceVolumeDaily.sector_code != source.sector_code,
    )):
        session.delete(row)
    session.commit()
    kwargs = dict(batch_by_date={TRADE_DATE: source.batch_id}, scope="LEVEL_1", level1_code=None,
                  level2_code=None, period=20, hierarchy=hierarchy, selected_sector_code=source.sector_code)
    result = SectorAnalysisFactReader().load_price_volume_history(session, **kwargs)
    assert len(result) == 1 and result[0] == source
    with pytest.raises(SectorDataQueryError):
        SectorAnalysisFactReader().load_price_volume_history(session, **{**kwargs, "selected_sector_code": "OUTSIDE"})
    with pytest.raises(SectorDataQueryError):
        SectorAnalysisFactReader().load_price_volume_history(None, **{**kwargs, "batch_by_date": {
            date.fromordinal(TRADE_DATE.toordinal()-i): source.batch_id for i in range(61)
        }})
    assert SectorAnalysisFactReader().load_price_volume_history(None, **{**kwargs, "batch_by_date": {}}) == ()


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"), 1.0])
def test_price_volume_reader_rejects_non_finite_or_non_decimal_values(price_volume_reader_session, value):
    session, hierarchy = price_volume_reader_session
    row = replace(_read_price_volume(session, hierarchy)[0], price_momentum_pct=value)
    with pytest.raises(SectorDataQueryError):
        SectorAnalysisFactReader._validate_price_volume_values(row, pool_size=3)


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


@pytest.fixture()
def dual_reader_session(momentum_reader_session):
    session, hierarchy = momentum_reader_session
    WealthSectorDualMomentumDaily.__table__.create(session.get_bind())
    for row in session.scalars(select(WealthSectorMomentumDaily)):
        first = row.strength_rank == 1
        db_row = WealthSectorDualMomentumDaily(
            **{name: getattr(row, name) for name in (
                "batch_id", "trade_date", "comparison_scope", "comparison_key", "parent_sector_code",
                "sector_code", "sector_name", "industry_level", "hierarchy_path", "period",
                "return_pct", "strength_rank", "rankable_count", "percentile", "calculation_status",
                "missing_reason", "calculated_at",
            )},
            formula_key="sector-dual-momentum", formula_version=1, minimum_group_size=3,
            absolute_status="POSITIVE", coordinate_status="PLOTTABLE",
            **{f"{name}_{threshold}": value
               for threshold in (70, 80, 90)
               for name, value in (
                   ("relative_status", "LEADING" if first else "NOT_LEADING"),
                   ("qualification_status", "QUALIFIED" if first else "NOT_QUALIFIED"),
                   ("display_status", "QUALIFIED" if first else "UP_NOT_LEADING"),
               )},
        )
        session.add(db_row)
    session.commit()
    return session, hierarchy


def _read_dual(session, hierarchy, **overrides):
    params = dict(
        batch_id=uuid5(NAMESPACE_URL, f"momentum-reader:{TRADE_DATE.isoformat()}"),
        trade_date=TRADE_DATE, scope="LEVEL_1", level1_code=None, level2_code=None,
        period=20, leading_threshold=80, hierarchy=hierarchy,
    )
    params.update(overrides)
    return SectorAnalysisFactReader().load_dual_momentum_rows(session, **params)


def test_dual_reader_single_published_slice_one_sql_without_source_tables(dual_reader_session):
    session, hierarchy = dual_reader_session
    statements = []
    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)
    event.listen(session.get_bind(), "before_cursor_execute", record)
    try:
        rows = _read_dual(session, hierarchy)
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", record)
    assert len(statements) == 1
    assert "dc_daily" not in statements[0].lower()
    assert len(rows) == 3
    assert rows[0].qualification_status == "QUALIFIED"
    assert rows[1].display_status == "UP_NOT_LEADING"
    assert rows[2].percentile == 0


def test_dual_reader_selects_each_thresholds_stored_columns(dual_reader_session):
    session, hierarchy = dual_reader_session
    row = session.scalar(select(WealthSectorDualMomentumDaily).where(
        WealthSectorDualMomentumDaily.sector_code == SECTOR_CODES[0],
    ))
    row.percentile = Decimal("80")
    row.relative_status_90 = "NOT_LEADING"
    row.qualification_status_90 = "NOT_QUALIFIED"
    row.display_status_90 = "UP_NOT_LEADING"
    session.commit()
    for threshold in (70, 80, 90):
        result = _read_dual(session, hierarchy, leading_threshold=threshold)[0]
        assert result.qualification_status == ("NOT_QUALIFIED" if threshold == 90 else "QUALIFIED")
        assert result.relative_status == ("NOT_LEADING" if threshold == 90 else "LEADING")


@pytest.mark.parametrize(("field", "value"), (
    ("formula_key", "wrong"), ("formula_version", 2), ("minimum_group_size", 4),
    ("parent_sector_code", "BK9999.DC"), ("sector_name", "changed"),
    ("industry_level", 2), ("hierarchy_path", "wrong"),
    ("calculation_status", "BAD"), ("return_pct", None),
    ("strength_rank", 0), ("strength_rank", 4), ("rankable_count", 4),
    ("percentile", Decimal("101")), ("percentile", Decimal("Infinity")),
    ("return_pct", Decimal("Infinity")), ("missing_reason", "DATE_MISSING"),
))
def test_dual_reader_rejects_invalid_published_contract(dual_reader_session, field, value):
    session, hierarchy = dual_reader_session
    session.execute(text("PRAGMA ignore_check_constraints=ON"))
    row = session.scalar(select(WealthSectorDualMomentumDaily).where(
        WealthSectorDualMomentumDaily.sector_code == SECTOR_CODES[0],
    ))
    setattr(row, field, value)
    session.commit()
    with pytest.raises(SectorDataQueryError):
        _read_dual(session, hierarchy)


@pytest.mark.parametrize("change", ("missing_row", "extra_code", "unpublished", "hierarchy", "formula_bundle", "other_batch"))
def test_dual_reader_rejects_missing_or_mixed_published_identity(dual_reader_session, change):
    session, hierarchy = dual_reader_session
    row = session.scalar(select(WealthSectorDualMomentumDaily))
    batch = session.scalar(select(WealthSectorAnalysisPublishBatch))
    if change == "missing_row":
        session.delete(row)
    elif change == "extra_code":
        row.sector_code = "BK9999.DC"
    elif change == "unpublished":
        batch.status = "FAILED"
    elif change == "hierarchy":
        batch.hierarchy_version = "other"
    elif change == "formula_bundle":
        batch.formula_bundle_version = "other"
    session.commit()
    with pytest.raises(SectorDataQueryError):
        _read_dual(session, hierarchy, **({"batch_id": uuid5(NAMESPACE_URL, "not-the-selected-batch")} if change == "other_batch" else {}))


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

@pytest.fixture()
def rotation_reader_session(momentum_reader_session):
    from src.foundation.models.core_serving.wealth_sector_relative_rotation_daily import WealthSectorRelativeRotationDaily
    session, hierarchy = momentum_reader_session
    WealthSectorRelativeRotationDaily.__table__.create(session.get_bind())
    for row in session.scalars(select(WealthSectorMomentumDaily)):
        session.add(WealthSectorRelativeRotationDaily(
            **{name: getattr(row, name) for name in (
                "batch_id", "trade_date", "comparison_scope", "comparison_key", "parent_sector_code",
                "sector_code", "sector_name", "industry_level", "hierarchy_path", "period",
                "return_pct", "strength_rank", "rankable_count", "percentile", "calculation_status",
                "missing_reason", "calculated_at",
            )},
            formula_key="sector-relative-rotation", formula_version=1, minimum_group_size=3,
            comparison_trade_date=date(2026, 8, 21), comparison_return_pct=row.return_pct,
            comparison_strength_rank=row.strength_rank, comparison_rankable_count=3,
            comparison_percentile=row.percentile, percentile_delta_5d=Decimal(0),
            coordinate_status="PLOTTABLE", group_interpretation="QUADRANT",
            rotation_status="STRONG_NOT_IMPROVING" if row.percentile >= 50 else "WEAK_NOT_IMPROVING",
            current_missing_reason=None, comparison_missing_reason=None,
        ))
    session.commit()
    return session, hierarchy


def _read_rotation(session, hierarchy, **overrides):
    kwargs = dict(
        batch_id=uuid5(NAMESPACE_URL, f"momentum-reader:{TRADE_DATE.isoformat()}"),
        trade_date=TRADE_DATE, scope="LEVEL_1", level1_code=None, level2_code=None,
        period=20, hierarchy=hierarchy,
    )
    kwargs.update(overrides)
    return SectorAnalysisFactReader().load_relative_rotation_rows(session, **kwargs)


def test_rotation_reads_stored_full_pool_and_selected_history_without_raw(rotation_reader_session):
    session, hierarchy = rotation_reader_session
    statements = []
    def observe(_c, _cursor, statement, _params, _context, _many):
        statements.append(statement)
    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", observe)
    try:
        rows = _read_rotation(session, hierarchy)
        history = SectorAnalysisFactReader().load_relative_rotation_history(
            session, batch_by_date={TRADE_DATE: rows[0].batch_id}, scope="LEVEL_1",
            level1_code=None, level2_code=None, period=20, hierarchy=hierarchy,
            selected_sector_code=SECTOR_CODES[1],
        )
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert len(rows) == 3 and len(history) == 1
    assert history[0] == rows[1]
    assert len(statements) == 2
    assert "sector_code =" in statements[1]
    assert all("dc_daily" not in sql.lower() and "SELECT" in sql for sql in statements)


@pytest.mark.parametrize(("field", "value"), [
    ("formula_version", 2), ("formula_key", "wrong"),
    ("parent_sector_code", "BK9999.DC"), ("sector_name", "wrong"),
    ("hierarchy_path", "wrong"), ("minimum_group_size", 4),
    ("comparison_trade_date", TRADE_DATE),
    ("return_pct", None), ("percentile", Decimal("101")), ("rankable_count", 4),
    ("comparison_return_pct", None), ("comparison_percentile", Decimal("-1")),
    ("comparison_rankable_count", 4), ("percentile_delta_5d", Decimal("101")),
    ("current_missing_reason", "DATE_MISSING"), ("comparison_missing_reason", "DATE_MISSING"),
    ("calculation_status", "UNAVAILABLE"), ("missing_reason", "DATE_MISSING"),
    ("group_interpretation", "wrong"), ("coordinate_status", "UNAVAILABLE"),
    ("rotation_status", "DATA_INSUFFICIENT"),
])
def test_rotation_rejects_inconsistent_stored_fields(rotation_reader_session, field, value):
    from src.foundation.models.core_serving.wealth_sector_relative_rotation_daily import WealthSectorRelativeRotationDaily
    session, hierarchy = rotation_reader_session
    row = session.scalars(select(WealthSectorRelativeRotationDaily)).first()
    # Fixture-only corruption: prove the read boundary even when a stored row is malformed.
    session.execute(text("PRAGMA ignore_check_constraints = ON"))
    setattr(row, field, value)
    session.flush()
    with pytest.raises(SectorDataQueryError):
        _read_rotation(session, hierarchy)


@pytest.mark.parametrize("field", ["status", "hierarchy_version", "formula_bundle_version"])
def test_rotation_rejects_unpublished_or_mismatched_batch(rotation_reader_session, field):
    session, hierarchy = rotation_reader_session
    batch = session.scalars(select(WealthSectorAnalysisPublishBatch)).one()
    setattr(batch, field, "SUPERSEDED" if field == "status" else "other")
    session.flush()
    with pytest.raises(SectorDataQueryError):
        _read_rotation(session, hierarchy)


def test_rotation_published_missing_selected_row_is_error_not_fake_gap(rotation_reader_session):
    from src.foundation.models.core_serving.wealth_sector_relative_rotation_daily import WealthSectorRelativeRotationDaily
    session, hierarchy = rotation_reader_session
    row = session.scalars(select(WealthSectorRelativeRotationDaily)).first()
    batch_id, code = row.batch_id, row.sector_code
    session.delete(row)
    session.flush()
    with pytest.raises(SectorDataQueryError):
        _read_rotation(session, hierarchy)
    with pytest.raises(SectorDataQueryError):
        SectorAnalysisFactReader().load_relative_rotation_history(
            session, batch_by_date={TRADE_DATE: batch_id}, scope="LEVEL_1",
            level1_code=None, level2_code=None, period=20, hierarchy=hierarchy,
            selected_sector_code=code,
        )


def test_rotation_history_limits_and_wrong_identity_stop_without_query(rotation_reader_session):
    from datetime import timedelta
    session, hierarchy = rotation_reader_session
    kwargs = dict(
        session=session, scope="LEVEL_1", level1_code=None, level2_code=None,
        period=20, hierarchy=hierarchy, selected_sector_code=SECTOR_CODES[0],
    )
    batch_id = uuid5(NAMESPACE_URL, f"momentum-reader:{TRADE_DATE.isoformat()}")
    reader = SectorAnalysisFactReader()
    assert reader.load_relative_rotation_history(batch_by_date={}, **kwargs) == ()
    with pytest.raises(SectorDataQueryError):
        reader.load_relative_rotation_history(
            batch_by_date={TRADE_DATE-timedelta(days=n): batch_id for n in range(60)}, **kwargs,
        )
    for mapping in (
        {TRADE_DATE: uuid5(NAMESPACE_URL, "another")},
        {TRADE_DATE-timedelta(days=1): batch_id},
    ):
        with pytest.raises(SectorDataQueryError):
            reader.load_relative_rotation_history(batch_by_date=mapping, **kwargs)
