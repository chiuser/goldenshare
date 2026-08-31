from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchySnapshot,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    SectorAnalysisDailyFactsPlanDriftError,
    SectorAnalysisDailyFactsReadbackError,
    SectorAnalysisSourceBundle,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.materialization_service import (
    SectorAnalysisDailyFactsMaterializationService,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.repository import (
    SectorAnalysisDailyFactsRepository,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.source_query import (
    SectorAnalysisDailyFactsSourceQuery,
)
from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_contract import (
    MemberMarketFact,
    MemberRelationFact,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorDailyFact,
)
from src.biz.services.wealth.market.sector_analysis.sector_price_volume_contract import (
    SectorPriceVolumeDailyFact,
)
from src.foundation.models.core_serving.wealth_sector_analysis_publish_batch import (
    WealthSectorAnalysisPublishBatch,
)
from src.foundation.models.core_serving.wealth_sector_daily_insight_item import (
    WealthSectorDailyInsightItem,
)
from src.foundation.models.core_serving.wealth_sector_daily_insight_summary import (
    WealthSectorDailyInsightSummary,
)
from src.foundation.models.core_serving.wealth_sector_dual_momentum_daily import (
    WealthSectorDualMomentumDaily,
)
from src.foundation.models.core_serving.wealth_sector_member_breadth_daily import (
    WealthSectorMemberBreadthDaily,
)
from src.foundation.models.core_serving.wealth_sector_member_ma_breadth_daily import (
    WealthSectorMemberMaBreadthDaily,
)
from src.foundation.models.core_serving.wealth_sector_momentum_daily import (
    WealthSectorMomentumDaily,
)
from src.foundation.models.core_serving.wealth_sector_price_volume_daily import (
    WealthSectorPriceVolumeDaily,
)
from src.foundation.models.core_serving.wealth_sector_relative_rotation_daily import (
    WealthSectorRelativeRotationDaily,
)


MODELS = (
    WealthSectorAnalysisPublishBatch,
    WealthSectorMomentumDaily,
    WealthSectorDualMomentumDaily,
    WealthSectorRelativeRotationDaily,
    WealthSectorMemberBreadthDaily,
    WealthSectorMemberMaBreadthDaily,
    WealthSectorPriceVolumeDaily,
    WealthSectorDailyInsightSummary,
    WealthSectorDailyInsightItem,
)


class SourceStub:
    def __init__(self, bundle: SectorAnalysisSourceBundle) -> None:
        self.bundle = bundle
        self.calls = 0

    def load_bundle(self, session, *, trade_date):  # type: ignore[no-untyped-def]
        del session
        self.calls += 1
        assert trade_date == self.bundle.trade_date
        return self.bundle


class TamperingRepository(SectorAnalysisDailyFactsRepository):
    def readback(self, session: Session, *, batch_id, expected):  # type: ignore[no-untyped-def]
        session.execute(
            delete(WealthSectorMomentumDaily).where(
                WealthSectorMomentumDaily.batch_id == batch_id,
                WealthSectorMomentumDaily.period == 1,
            )
        )
        session.flush()
        return super().readback(session, batch_id=batch_id, expected=expected)


def _engine():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        for model in MODELS:
            model.__table__.create(connection)
    return engine


def _node(
    code: str,
    name: str,
    level: int,
    parent_code: str | None,
    parent_name: str | None,
    root_code: str,
    root_name: str,
) -> SectorHierarchyNode:
    path_names = {1: root_name, 2: f"{root_name} > {name}", 3: f"{root_name} > 二级行业 > {name}"}
    return SectorHierarchyNode(
        sector_code=code,
        sector_name=name,
        industry_level=level,
        parent_sector_code=parent_code,
        parent_sector_name=parent_name,
        root_sector_code=root_code,
        root_sector_name=root_name,
        hierarchy_path=path_names[level],
        display_order=level,
        is_leaf=level == 3,
        baseline_version="dc-industry-hierarchy@20260831",
    )


def _bundle(
    *,
    amount_shift: Decimal = Decimal("0"),
    source_hash: str = "a" * 64,
    start_offset: int = 0,
) -> SectorAnalysisSourceBundle:
    nodes = (
        _node("L1.DC", "一级行业", 1, None, None, "L1.DC", "一级行业"),
        _node("L2.DC", "二级行业", 2, "L1.DC", "一级行业", "L1.DC", "一级行业"),
        _node("L3.DC", "三级行业", 3, "L2.DC", "二级行业", "L1.DC", "一级行业"),
    )
    snapshot = SectorHierarchySnapshot(
        baseline_version="dc-industry-hierarchy@20260831",
        published_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
        nodes=nodes,
        nodes_by_code={node.sector_code: node for node in nodes},
        children_by_parent={None: (nodes[0],), "L1.DC": (nodes[1],), "L2.DC": (nodes[2],)},
    )
    start = date(2026, 6, 1) + timedelta(days=start_offset)
    open_dates = tuple(start + timedelta(days=offset) for offset in range(60))
    sector_facts = []
    price_volume = []
    relations = []
    market = []
    stock_codes = tuple(f"00000{index}.SZ" for index in range(1, 6))
    for day_index, trade_date in enumerate(open_dates, start=1):
        for sector_index, node in enumerate(nodes, start=1):
            close = Decimal(100 + day_index + sector_index)
            pct_change = Decimal(sector_index) / Decimal("10")
            amount = Decimal(1000 + day_index * sector_index) + amount_shift
            sector_facts.append(SectorDailyFact(node.sector_code, trade_date, close, pct_change))
            price_volume.append(
                SectorPriceVolumeDailyFact(node.sector_code, trade_date, close, pct_change, amount)
            )
            relations.extend(
                MemberRelationFact(node.sector_code, trade_date, stock_code, f"股票{stock_code}")
                for stock_code in stock_codes
            )
        market.extend(
            MemberMarketFact(
                stock_code,
                trade_date,
                Decimal(10 + day_index),
                Decimal("1.0"),
                Decimal(100 + day_index),
                Decimal("1.0"),
            )
            for stock_code in stock_codes
        )
    pools = SectorAnalysisDailyFactsSourceQuery._comparison_pools(snapshot)
    return SectorAnalysisSourceBundle(
        trade_date=open_dates[-1],
        previous_trade_date=open_dates[-2],
        open_dates=open_dates,
        hierarchy=snapshot,
        comparison_pools=pools,
        sector_facts=tuple(sector_facts),
        price_volume_facts=tuple(price_volume),
        member_relations=tuple(relations),
        member_market_facts=tuple(market),
        source_dates={"dc_daily": f"{open_dates[0]}..{open_dates[-1]}"},
        source_row_counts={"dc_daily": len(sector_facts)},
        source_hash=source_hash,
    )


def _preview_and_materialize(service, session_factory, target):  # type: ignore[no-untyped-def]
    with session_factory() as session:
        preview = service.preview_trade_date(session, trade_date=target)
        session.rollback()
    result = service.materialize_trade_date(
        trade_date=target,
        expected_source_hash=preview.source_hash,
        expected_plan_hash=preview.plan_hash,
        expected_content_hash=preview.content_hash,
    )
    return preview, result


def test_single_day_build_has_all_five_scopes_and_expected_typed_rows() -> None:
    engine = _engine()
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    source = SourceStub(_bundle())
    service = SectorAnalysisDailyFactsMaterializationService(
        session_factory=session_factory,
        source_query=source,
    )

    preview, result = _preview_and_materialize(service, session_factory, source.bundle.trade_date)

    assert preview.expected_fact_counts == {
        "wealth_sector_analysis_publish_batch": 1,
        "wealth_sector_momentum_daily": 25,
        "wealth_sector_dual_momentum_daily": 20,
        "wealth_sector_relative_rotation_daily": 20,
        "wealth_sector_member_breadth_daily": 5,
        "wealth_sector_member_ma_breadth_daily": 30,
        "wealth_sector_price_volume_daily": 25,
        "wealth_sector_daily_insight_summary": 3,
        "wealth_sector_daily_insight_item": 3,
    }
    assert result.status == "PUBLISHED"
    assert result.rows_saved == 132
    assert source.calls == 2
    with session_factory() as session:
        batch = session.scalar(select(WealthSectorAnalysisPublishBatch))
        assert batch is not None and batch.status == "PUBLISHED"
        assert batch.expected_fact_counts_json == batch.actual_fact_counts_json
        assert session.scalar(select(func.count()).select_from(WealthSectorMomentumDaily)) == 25


def test_same_content_replay_is_idempotent_with_zero_new_rows() -> None:
    engine = _engine()
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    source = SourceStub(_bundle())
    service = SectorAnalysisDailyFactsMaterializationService(
        session_factory=session_factory,
        source_query=source,
    )
    _, first = _preview_and_materialize(service, session_factory, source.bundle.trade_date)
    _, second = _preview_and_materialize(service, session_factory, source.bundle.trade_date)

    assert first.status == "PUBLISHED"
    assert second.status == "IDEMPOTENT"
    assert second.idempotent is True
    assert second.rows_saved == 0
    assert second.batch_id == first.batch_id
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WealthSectorAnalysisPublishBatch)) == 1
        assert session.scalar(select(func.count()).select_from(WealthSectorMomentumDaily)) == 25


def test_expected_hash_drift_creates_no_batch_or_child_rows() -> None:
    engine = _engine()
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    source = SourceStub(_bundle())
    service = SectorAnalysisDailyFactsMaterializationService(
        session_factory=session_factory,
        source_query=source,
    )
    with session_factory() as session:
        preview = service.preview_trade_date(session, trade_date=source.bundle.trade_date)
        session.rollback()

    with pytest.raises(SectorAnalysisDailyFactsPlanDriftError):
        service.materialize_trade_date(
            trade_date=source.bundle.trade_date,
            expected_source_hash="f" * 64,
            expected_plan_hash=preview.plan_hash,
            expected_content_hash=preview.content_hash,
        )

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WealthSectorAnalysisPublishBatch)) == 0
        assert session.scalar(select(func.count()).select_from(WealthSectorMomentumDaily)) == 0


def test_new_content_supersedes_exactly_one_previous_batch() -> None:
    engine = _engine()
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    source = SourceStub(_bundle())
    service = SectorAnalysisDailyFactsMaterializationService(
        session_factory=session_factory,
        source_query=source,
    )
    _, first = _preview_and_materialize(service, session_factory, source.bundle.trade_date)
    source.bundle = _bundle(amount_shift=Decimal("100"), source_hash="b" * 64)
    _, second = _preview_and_materialize(service, session_factory, source.bundle.trade_date)

    assert first.batch_id != second.batch_id
    with session_factory() as session:
        rows = tuple(
            session.scalars(
                select(WealthSectorAnalysisPublishBatch).order_by(
                    WealthSectorAnalysisPublishBatch.started_at,
                    WealthSectorAnalysisPublishBatch.batch_id,
                )
            )
        )
        assert sorted(row.status for row in rows) == ["PUBLISHED", "SUPERSEDED"]
        assert sum(row.status == "PUBLISHED" for row in rows) == 1


def test_superseded_content_cannot_silently_replace_current_published_facts() -> None:
    engine = _engine()
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    original_bundle = _bundle()
    source = SourceStub(original_bundle)
    service = SectorAnalysisDailyFactsMaterializationService(
        session_factory=session_factory,
        source_query=source,
    )
    _preview_and_materialize(service, session_factory, source.bundle.trade_date)
    source.bundle = _bundle(amount_shift=Decimal("100"), source_hash="b" * 64)
    _, current = _preview_and_materialize(service, session_factory, source.bundle.trade_date)

    source.bundle = original_bundle
    with pytest.raises(SectorAnalysisDailyFactsPlanDriftError, match="禁止静默回退"):
        _preview_and_materialize(service, session_factory, source.bundle.trade_date)

    with session_factory() as session:
        batches = tuple(session.scalars(select(WealthSectorAnalysisPublishBatch)))
        assert len(batches) == 2
        [published] = [row for row in batches if row.status == "PUBLISHED"]
        assert published.batch_id == current.batch_id


def test_single_sector_gap_is_published_as_typed_missing_without_blocking_other_facts() -> None:
    engine = _engine()
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    complete = _bundle()
    source = SourceStub(
        replace(
            complete,
            sector_facts=tuple(
                row
                for row in complete.sector_facts
                if not (
                    row.sector_code == "L3.DC"
                    and row.trade_date == complete.trade_date
                )
            ),
            source_hash="c" * 64,
        )
    )
    service = SectorAnalysisDailyFactsMaterializationService(
        session_factory=session_factory,
        source_query=source,
    )

    _, result = _preview_and_materialize(service, session_factory, source.bundle.trade_date)

    assert result.status == "PUBLISHED"
    with session_factory() as session:
        missing_rows = tuple(
            session.scalars(
                select(WealthSectorMomentumDaily).where(
                    WealthSectorMomentumDaily.batch_id == result.batch_id,
                    WealthSectorMomentumDaily.sector_code == "L3.DC",
                    WealthSectorMomentumDaily.period == 1,
                )
            )
        )
        assert len(missing_rows) == 2
        assert all(row.calculation_status == "UNAVAILABLE" for row in missing_rows)
        assert all(row.missing_reason != "NONE" for row in missing_rows)
        assert session.scalar(
            select(func.count())
            .select_from(WealthSectorMomentumDaily)
            .where(
                WealthSectorMomentumDaily.batch_id == result.batch_id,
                WealthSectorMomentumDaily.calculation_status == "CALCULABLE",
            )
        ) > 0


def test_readback_tamper_marks_new_batch_failed_and_never_publishes_it() -> None:
    engine = _engine()
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    source = SourceStub(_bundle())
    service = SectorAnalysisDailyFactsMaterializationService(
        session_factory=session_factory,
        source_query=source,
        repository=TamperingRepository(),
    )
    with session_factory() as session:
        preview = service.preview_trade_date(session, trade_date=source.bundle.trade_date)
        session.rollback()

    with pytest.raises(SectorAnalysisDailyFactsReadbackError, match="逐表计数不一致"):
        service.materialize_trade_date(
            trade_date=source.bundle.trade_date,
            expected_source_hash=preview.source_hash,
            expected_plan_hash=preview.plan_hash,
            expected_content_hash=preview.content_hash,
        )

    with session_factory() as session:
        [batch] = tuple(session.scalars(select(WealthSectorAnalysisPublishBatch)))
        assert batch.status == "FAILED"
        assert batch.failure_reason_code == "SA_DAILY_FACT_READBACK_MISMATCH"


def test_content_hash_is_stable_after_numeric_database_rounding() -> None:
    engine = _engine()
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    source = SourceStub(_bundle())
    service = SectorAnalysisDailyFactsMaterializationService(
        session_factory=session_factory,
        source_query=source,
    )

    preview, result = _preview_and_materialize(service, session_factory, source.bundle.trade_date)

    assert result.content_hash == preview.content_hash
    with session_factory() as session:
        [batch] = tuple(session.scalars(select(WealthSectorAnalysisPublishBatch)))
        assert batch.content_hash == preview.content_hash


def test_next_day_batch_binds_the_exact_previous_published_batch() -> None:
    engine = _engine()
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    source = SourceStub(_bundle())
    service = SectorAnalysisDailyFactsMaterializationService(
        session_factory=session_factory,
        source_query=source,
    )
    _, first = _preview_and_materialize(service, session_factory, source.bundle.trade_date)
    source.bundle = _bundle(start_offset=1, source_hash="d" * 64)
    _, second = _preview_and_materialize(service, session_factory, source.bundle.trade_date)

    with session_factory() as session:
        second_batch = session.get(WealthSectorAnalysisPublishBatch, second.batch_id)
        assert second_batch is not None
        assert second_batch.previous_trade_date == first.trade_date
        assert second_batch.previous_batch_id == first.batch_id
