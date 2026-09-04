from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import re
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.biz.queries.wealth.market.sector_analysis.sector_daily_insight_query import (
    SectorDailyInsightBatchMismatchError,
    SectorDailyInsightQuery,
)
from src.biz.queries.wealth.market.sector_analysis.sector_daily_insight_query_service import (
    SectorDailyInsightQueryService,
)
from src.biz.schemas.wealth.market.sector_daily_insight import (
    SectorDailyInsightSnapshotRequest,
    SectorDailyInsightSnapshotResponseDto,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    FORMULA_BUNDLE_VERSION,
    TEMPLATE_VERSION,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.template_renderer import (
    SectorDailyInsightTemplateRenderer,
)
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.wealth_sector_analysis_publish_batch import (
    WealthSectorAnalysisPublishBatch as Batch,
)
from src.foundation.models.core_serving.wealth_sector_daily_insight_item import (
    WealthSectorDailyInsightItem as Item,
)
from src.foundation.models.core_serving.wealth_sector_daily_insight_summary import (
    WealthSectorDailyInsightSummary as Summary,
)


DAY = date(2025, 8, 25)
NOW = datetime(2025, 8, 25, 21, tzinfo=timezone.utc)
BATCH_ID = UUID("3b3393fc-5a55-4b57-a59c-e7aa241ceabc")
HIERARCHY = "dc-industry-hierarchy@20260831"


def seed_insight(session: Session):
    for model in (TradeCalendar, Batch, Summary, Item):
        model.__table__.create(session.get_bind(), checkfirst=True)
    previous = date(2025, 8, 21)
    for index in range(7):
        day = date(2025, 8, 22) + timedelta(days=index)
        opened = day.weekday() < 5
        session.add(
            TradeCalendar(
                exchange="SSE", trade_date=day, is_open=opened, pretrade_date=previous
            )
        )
        if opened:
            previous = day
    session.add(
        Batch(
            batch_id=BATCH_ID,
            trade_date=DAY,
            previous_trade_date=date(2025, 8, 22),
            status="PUBLISHED",
            hierarchy_version=HIERARCHY,
            formula_bundle_version=FORMULA_BUNDLE_VERSION,
            template_version=TEMPLATE_VERSION,
            source_hash="a" * 64,
            plan_hash="b" * 64,
            content_hash="c" * 64,
            source_dates_json={},
            source_row_counts_json={},
            expected_fact_counts_json={},
            actual_fact_counts_json={},
            started_at=NOW,
            calculated_at=NOW,
            published_at=NOW,
        )
    )
    for level in (1, 2, 3):
        counts = {
            column.name: 0
            for column in Summary.__table__.columns
            if column.name.startswith("missing_")
        }
        counts["missing_count"] = 2
        counts["missing_price_count"] = 2
        # Independent evidence gaps must not be forced to sum to missing_count.
        counts["missing_coverage_count"] = 4
        session.add(
            Summary(
                batch_id=BATCH_ID,
                trade_date=DAY,
                industry_level=level,
                sector_count=5,
                calculable_count=3,
                up_count=1,
                down_count=1,
                flat_count=1,
                median_change_pct_1d=Decimal(0),
                dual_momentum_count_20d_80=1,
                leading_improving_count_20d_5d=1,
                price_volume_joint_count_20d=1,
                breadth_up_share_above_50_count=1,
                **counts,
            )
        )
        for category in ("HEAD_GAINER", "HEAD_LOSER", "STRENGTHENING", "WEAKENING"):
            positive = category in ("HEAD_GAINER", "STRENGTHENING")
            code = f"BK{level}00{1 if positive else 2}.DC"
            values = {
                column.name: None
                for column in Item.__table__.columns
                if column.name
                not in (
                    "batch_id",
                    "trade_date",
                    "industry_level",
                    "category",
                    "sector_code",
                )
            }
            values.update(
                stable_order=1,
                event_type=category,
                sector_name="通信网络设备及器件" if positive else "下跌行业",
                hierarchy_path="通信 > 通信设备 > 通信网络设备及器件",
                return_pct_1d=Decimal(3 if positive else -2),
                return_pct_5d=Decimal(4),
                return_pct_20d=Decimal(10),
                current_rank_20d=2 if positive else 4,
                current_rankable_count_20d=5,
                current_percentile_20d=Decimal(75 if positive else 25),
                previous_rank_20d=4 if positive else 2,
                previous_rankable_count_20d=5,
                previous_percentile_20d=Decimal(25 if positive else 75),
                rank_change=2 if positive else -2,
                percentile_change_pp=Decimal(50 if positive else -50),
                primary_evidence_type="PRICE_VOLUME",
                price_volume_state_current="JOINT",
                price_volume_state_previous="PRICE_ONLY",
                template_key="sector-daily-insight",
                template_version=TEMPLATE_VERSION,
            )
            values["rendered_text"] = SectorDailyInsightTemplateRenderer().render(
                category=category,
                sector_name=values["sector_name"],
                industry_level=level,
                values=values,
                evidence_types=("PRICE_VOLUME",),
                previous_evidence_types=("PRICE_VOLUME",),
            )[2]
            session.add(
                Item(
                    batch_id=BATCH_ID,
                    trade_date=DAY,
                    industry_level=level,
                    category=category,
                    sector_code=code,
                    **values,
                )
            )
    session.commit()


def request_params(**updates):
    return {
        "tradeDate": DAY.isoformat(),
        "industryLevel": 1,
        "batchKey": str(BATCH_ID),
        "hierarchyVersion": HIERARCHY,
        **updates,
    }


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
    monkeypatch.setattr(
        "src.biz.queries.wealth.market.context.market_page_context_query._now_cn",
        lambda: NOW,
    )
    with Session(engine) as session:
        seed_insight(session)
        yield session
    engine.dispose()


@contextmanager
def selects(session):
    statements = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().upper().startswith(("SELECT", "WITH")), statement
        tables = set(re.findall(r"core_serving\.(\w+)", statement))
        assert tables <= {
            "trade_calendar",
            "wealth_sector_analysis_publish_batch",
            "wealth_sector_daily_insight_summary",
            "wealth_sector_daily_insight_item",
        }
        statements.append(statement)

    event.listen(session.get_bind(), "before_cursor_execute", observe)
    try:
        yield statements
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", observe)


def snapshot(db, **updates):
    params = request_params()
    params.update(updates)
    return SectorDailyInsightQueryService().build_snapshot(
        db, request=SectorDailyInsightSnapshotRequest.model_validate(params)
    )


def test_meta_two_sql_and_snapshot_three_sql_all_levels(db):
    with selects(db) as sql:
        meta = SectorDailyInsightQueryService().build_meta(db)
    assert len(sql) == 2
    assert meta.status == "READY" and meta.defaultBatchKey == BATCH_ID
    assert [(row.tradeDate, row.availability) for row in meta.tradeDates] == [
        (date(2025, 8, 22), "MISSING"),
        (DAY, "PUBLISHED"),
    ]
    for level in (1, 2, 3):
        with selects(db) as sql:
            result = snapshot(db, industryLevel=level)
        assert len(sql) == 3
        assert result.status == "READY" and result.missingSectorCount == 2
        assert [
            len(getattr(result, key))
            for key in ("headGainers", "headLosers", "strengthening", "weakening")
        ] == [1, 1, 1, 1]
        assert result.headGainers[0].sectorCode == f"BK{level}001.DC"
        assert result.headGainers[0].secondaryEvidenceTypes == []
        assert [(row.reasonCode, row.count) for row in result.missingReasonCounts] == [
            ("PRICE", 2),
            ("COVERAGE", 4),
        ]
        assert result.headGainers[0].renderedText == db.scalar(
            select(Item.rendered_text).where(
                Item.batch_id == BATCH_ID,
                Item.industry_level == level,
                Item.category == "HEAD_GAINER",
            )
        )
        encoded = result.model_dump_json()
        assert (
            '"returnPct1d":3.0' in encoded
            and '"priceVolumeStatePrevious":"PRICE_ONLY"' in encoded
        )
        assert not any(
            key in encoded
            for key in (
                "source_hash",
                "sourceHash",
                "planHash",
                "contentHash",
                "core_serving",
            )
        )


@pytest.mark.parametrize("hour,expected", [(19, "READY"), (20, "DELAYED")])
def test_public_twenty_hour_rule_and_no_future_published_leak(
    db, monkeypatch, hour, expected
):
    now = datetime(2025, 8, 26, hour, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "src.biz.queries.wealth.market.context.market_page_context_query._now_cn",
        lambda: now,
    )
    with selects(db) as sql:
        meta = SectorDailyInsightQueryService().build_meta(db)
    assert len(sql) == 2 and meta.status == expected
    assert meta.defaultTradeDate == DAY and meta.dateContext.previousTradeDate == date(
        2025, 8, 22
    )
    if expected == "DELAYED":
        assert (
            meta.dateContext.isDelayed and meta.tradeDates[-1].availability == "MISSING"
        )
        assert "2025-08-25" in meta.message


def test_no_published_batch_returns_empty_calendar_without_method_queries(db):
    batch = db.get(Batch, BATCH_ID)
    batch.status = "SUPERSEDED"
    db.commit()
    with selects(db) as sql:
        meta = SectorDailyInsightQueryService().build_meta(db)
    assert len(sql) == 2 and meta.status == "EMPTY"
    assert meta.defaultBatchKey is None and len(meta.tradeDates) == 2
    assert all(row.availability == "MISSING" for row in meta.tradeDates)


@pytest.mark.parametrize(
    "updates",
    [
        {"batchKey": str(uuid4())},
        {"hierarchyVersion": "wrong"},
        {"tradeDate": "2025-08-22"},
    ],
)
def test_snapshot_mismatch_never_falls_back_or_loads_children(db, updates):
    with selects(db) as sql, pytest.raises(SectorDailyInsightBatchMismatchError):
        snapshot(db, **updates)
    assert len(sql) == 1


@pytest.mark.parametrize("phase", ["load_summary", "load_items"])
def test_publication_replacement_during_request_returns_mismatch(db, phase):
    class Race(SectorDailyInsightQuery):
        pass

    original = getattr(SectorDailyInsightQuery, phase)

    def replace_batch(self, session, **kwargs):
        session.get(Batch, BATCH_ID).status = "SUPERSEDED"
        session.flush()
        return original(self, session, **kwargs)

    setattr(Race, phase, replace_batch)
    with pytest.raises(SectorDailyInsightBatchMismatchError):
        SectorDailyInsightQueryService(query=Race()).build_snapshot(
            db,
            request=SectorDailyInsightSnapshotRequest.model_validate(request_params()),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("stable_order", 2),
        ("template_version", "wrong"),
        ("return_pct_1d", -1),
        ("rank_change", 99),
        ("percentile_change_pp", 10),
        ("current_rank_20d", 9),
        ("member_up_pct_current", 101),
        ("secondary_evidence_type_1", "PRICE_VOLUME"),
        ("rendered_text", ""),
    ],
)
def test_corrupt_published_item_is_rejected(db, field, value):
    row = db.scalar(
        select(Item).where(Item.industry_level == 1, Item.category == "HEAD_GAINER")
    )
    setattr(row, field, value)
    db.commit()
    with pytest.raises(ValueError):
        snapshot(db)


@pytest.mark.parametrize(
    "field,value",
    [
        ("up_count", 2),
        ("missing_count", 0),
        ("missing_coverage_count", 6),
        ("missing_previous_batch_count", 5),
    ],
)
def test_summary_and_complete_arrays_are_validated(db, field, value):
    setattr(db.get(Summary, (BATCH_ID, 1)), field, value)
    if field == "missing_count":
        # Keep the DB check valid, but contradict the 1d up/down/flat facts.
        db.get(Summary, (BATCH_ID, 1)).calculable_count = 5
    db.commit()
    with pytest.raises(ValueError):
        snapshot(db)


def test_strict_response_rejects_unknown_duplicate_missing_and_nonfinite(db):
    valid = snapshot(db).model_dump()
    for change in (
        {"arbitrary": True},
        {"headGainers": []},
        {"headGainers": valid["headGainers"] * 2},
        {"headGainers": [{**valid["headGainers"][0], "returnPct5d": float("nan")}]},
    ):
        with pytest.raises(ValidationError):
            SectorDailyInsightSnapshotResponseDto.model_validate({**valid, **change})


def test_versions_are_reported_from_batch_not_relabeled(db):
    db.get(Batch, BATCH_ID).template_version = "sector-daily-insight-template@1"
    for row in db.scalars(select(Item)):
        row.template_version = "sector-daily-insight-template@1"
    db.commit()
    assert snapshot(db).templateVersion.endswith("@1")
    assert (
        SectorDailyInsightQueryService().build_meta(db).templateVersion.endswith("@1")
    )


def test_builder_repository_and_api_roundtrip_with_real_calculators():
    from sqlalchemy.orm import sessionmaker
    from tests.test_wealth_sector_analysis_daily_materialization import (
        SourceStub,
        _bundle,
        _engine,
    )
    from src.biz.services.wealth.market.sector_analysis.daily_facts.source_query import (
        SectorAnalysisDailyFactsSourceQuery,
    )
    from src.biz.services.wealth.market.sector_analysis.daily_facts.materialization_service import (
        SectorAnalysisDailyFactsMaterializationService,
    )

    bundle = _bundle()
    codes = {f"L{level}.DC": f"BK{level}001.DC" for level in (1, 2, 3)}
    nodes = tuple(
        replace(
            node,
            sector_code=codes[node.sector_code],
            parent_sector_code=codes.get(node.parent_sector_code),
            root_sector_code=codes[node.root_sector_code],
        )
        for node in bundle.hierarchy.nodes
    )
    hierarchy = replace(
        bundle.hierarchy,
        nodes=nodes,
        nodes_by_code={node.sector_code: node for node in nodes},
        children_by_parent={node.parent_sector_code: (node,) for node in nodes},
    )
    bundle = replace(
        bundle,
        hierarchy=hierarchy,
        comparison_pools=SectorAnalysisDailyFactsSourceQuery._comparison_pools(
            hierarchy
        ),
        **{
            field: tuple(
                replace(row, sector_code=codes[row.sector_code])
                for row in getattr(bundle, field)
            )
            for field in ("sector_facts", "price_volume_facts", "member_relations")
        },
    )
    engine = _engine()
    try:
        sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
        materializer = SectorAnalysisDailyFactsMaterializationService(
            session_factory=sessions, source_query=SourceStub(bundle)
        )
        with sessions() as session:
            plan = materializer.preview_trade_date(
                session, trade_date=bundle.trade_date
            )
        result = materializer.materialize_trade_date(
            trade_date=bundle.trade_date,
            expected_source_hash=plan.source_hash,
            expected_plan_hash=plan.plan_hash,
            expected_content_hash=plan.content_hash,
        )
        with sessions() as session:
            for level in (1, 2, 3):
                response = SectorDailyInsightQueryService().build_snapshot(
                    session,
                    request=SectorDailyInsightSnapshotRequest(
                        tradeDate=bundle.trade_date,
                        industryLevel=level,
                        batchKey=result.batch_id,
                        hierarchyVersion=hierarchy.baseline_version,
                    ),
                )
                assert response.status == "READY" and len(response.headGainers) == 1
                assert response.templateVersion == TEMPLATE_VERSION
                assert response.summary.missingPreviousBatchCount == 1
                assert response.strengthening == response.weakening == []
                assert "佐证：" not in response.headGainers[0].renderedText
    finally:
        engine.dispose()


def test_empty_and_no_change_panels_do_not_erase_usable_facts(db):
    data = snapshot(db).model_dump()
    data["strengthening"] = []
    data["weakening"] = []
    assert SectorDailyInsightSnapshotResponseDto.model_validate(data).status == "READY"
    # All current 1d values can be missing while a valid 20d change still exists.
    data["summary"].update(
        calculableCount=0,
        upCount=0,
        downCount=0,
        flatCount=0,
        missingCount=5,
        medianChangePct1d=None,
    )
    data["missingSectorCount"] = 5
    data["headGainers"] = data["headLosers"] = []
    assert (
        SectorDailyInsightSnapshotResponseDto.model_validate(data).status == "READY"
    )  # Other overview evidence remains.
    data["summary"].update(
        dualMomentumCount20d80=0,
        leadingImprovingCount20d5d=0,
        priceVolumeJointCount20d=0,
        breadthUpShareAbove50Count=0,
    )
    data["status"] = "EMPTY"
    assert SectorDailyInsightSnapshotResponseDto.model_validate(data).status == "EMPTY"


@pytest.mark.parametrize(
    "change",
    [
        {"returnPct1d": True},
        {"returnPct5d": "5"},
        {"returnPct20d": float("inf")},
        {"currentRank20d": True},
        {"sectorName": "   "},
        {"rotationStatus20dCurrent": "UNKNOWN"},
    ],
)
def test_strict_values_reject_coercions(db, change):
    from src.biz.schemas.wealth.market.sector_daily_insight import (
        SectorDailyInsightItemDto,
    )

    data = snapshot(db).headGainers[0].model_dump()
    with pytest.raises(ValidationError):
        SectorDailyInsightItemDto.model_validate({**data, **change})


def test_full_order_no_top_n_and_invalid_order_rejected(db):
    data = snapshot(db).model_dump()
    template = data["headGainers"][0]
    data["headGainers"] = [
        {
            **template,
            "sectorCode": f"BK{index:04d}.DC",
            "returnPct1d": float(150 - index),
        }
        for index in range(1, 81)
    ]
    data["summary"].update(sectorCount=84, calculableCount=82, upCount=80)
    assert (
        len(SectorDailyInsightSnapshotResponseDto.model_validate(data).headGainers)
        == 80
    )
    data["headGainers"].reverse()
    with pytest.raises(ValidationError, match="published order"):
        SectorDailyInsightSnapshotResponseDto.model_validate(data)


def test_no_fallback_for_missing_future_or_unpublished_batches(db):
    for status in ("BUILDING", "FAILED", "SUPERSEDED"):
        db.get(Batch, BATCH_ID).status = status
        db.commit()
        with pytest.raises(SectorDailyInsightBatchMismatchError):
            snapshot(db)


def test_summary_reason_counts_are_not_recomputed_or_dropped(db):
    data = snapshot(db).model_dump()
    for reasons in (
        [],
        data["missingReasonCounts"][::-1],
        [{"reasonCode": "PRICE", "count": 9}],
    ):
        with pytest.raises(ValidationError, match="ordered summary"):
            SectorDailyInsightSnapshotResponseDto.model_validate(
                {**data, "missingReasonCounts": reasons}
            )


def test_cross_panel_fact_disagreement_is_rejected(db):
    data = snapshot(db).model_dump()
    data["strengthening"][0]["returnPct5d"] = 5
    with pytest.raises(ValidationError, match="across panels"):
        SectorDailyInsightSnapshotResponseDto.model_validate(data)


def test_meta_ignores_a_future_batch_and_preserves_partial_current_batch(db):
    current = db.get(Batch, BATCH_ID)
    fields = {
        column.name: getattr(current, column.name) for column in Batch.__table__.columns
    }
    fields.update(
        batch_id=uuid4(),
        trade_date=DAY + timedelta(days=1),
        plan_hash="d" * 64,
        content_hash="e" * 64,
    )
    db.add(Batch(**fields))
    db.commit()
    with selects(db) as sql:
        meta = SectorDailyInsightQueryService().build_meta(db)
    assert len(sql) == 2 and meta.defaultBatchKey == BATCH_ID
    assert meta.status == "READY"  # Two missing 1d industries do not cause a fallback.
    assert all(row.tradeDate <= DAY for row in meta.tradeDates)


def test_exact_head_zero_is_excluded_and_all_zero_market_is_ready(db):
    data = snapshot(db).model_dump()
    data.update(headGainers=[], headLosers=[], strengthening=[], weakening=[])
    data["summary"].update(upCount=0, downCount=0, flatCount=3)
    result = SectorDailyInsightSnapshotResponseDto.model_validate(data)
    assert result.status == "READY" and result.summary.medianChangePct1d == 0


@pytest.mark.parametrize(
    "current,previous,accepted", [(80, 79.9, True), (70, 60, True), (70, 60.1, False)]
)
def test_change_threshold_and_entering_top_twenty_percent(
    db, current, previous, accepted
):
    data = snapshot(db).model_dump()
    data["headGainers"] = []
    data["summary"].update(upCount=0, flatCount=2)
    row = data["strengthening"][0]
    row.update(
        currentPercentile20d=current,
        previousPercentile20d=previous,
        percentileChangePp=float(Decimal(str(current)) - Decimal(str(previous))),
    )
    if accepted:
        assert (
            SectorDailyInsightSnapshotResponseDto.model_validate(data).status == "READY"
        )
    else:
        with pytest.raises(ValidationError, match="threshold"):
            SectorDailyInsightSnapshotResponseDto.model_validate(data)
