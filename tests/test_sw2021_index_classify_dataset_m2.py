from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import (
    DatasetActionRequest,
    DatasetActionResolver,
    DatasetTimeInput,
)
from src.foundation.ingestion.errors import (
    IngestionNormalizeError,
    IngestionValidationError,
    IngestionWriteError,
)
from src.foundation.ingestion.execution_plan import ValidatedDatasetActionRequest
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.ingestion.normalizer import DatasetNormalizer, NormalizedBatch
from src.foundation.ingestion.pre_write_validators import (
    PreWriteValidationError,
    get_pre_write_validator,
)
from src.foundation.ingestion.source_client import (
    DatasetSourceClient,
    SourceFetchResult,
)
from src.foundation.models.core_serving.sw_industry_classification import (
    SwIndustryClassification,
)
from src.ops.dataset_definition_projection import get_dataset_freshness_projection
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.queries.manual_action_query_service import ManualActionQueryService
from src.ops.schemas.freshness import DatasetFreshnessItem
from src.ops.services.operations_dataset_status_snapshot_service import (
    DatasetStatusSnapshotService,
)
from src.ops.services.schedule_automation_capability_resolver import (
    ScheduleAutomationCapabilityResolver,
)


SOURCE_FIELDS = (
    "index_code",
    "industry_name",
    "parent_code",
    "level",
    "industry_code",
    "is_pub",
    "src",
)


def _classification_source_rows() -> list[dict]:
    rows = [
        {
            "index_code": "801040.SI",
            "industry_name": "钢铁",
            "parent_code": "0",
            "level": "L1",
            "industry_code": "230000",
            "src": "SW2021",
        },
        {
            "index_code": "801045.SI",
            "industry_name": "特钢Ⅱ",
            "parent_code": "230000",
            "level": "L2",
            "industry_code": "230500",
            "src": "SW2021",
        },
        {
            "index_code": "850401.SI",
            "industry_name": "特钢Ⅲ",
            "parent_code": "230500",
            "level": "L3",
            "industry_code": "230501",
            "src": "SW2021",
        },
    ]

    l1_codes = ["230000"]
    for index in range(30):
        industry_code = f"{100000 + index:06d}"
        l1_codes.append(industry_code)
        rows.append(
            {
                "index_code": f"{801000 + index:06d}.SI",
                "industry_name": f"一级行业{index:02d}",
                "parent_code": "0",
                "level": "L1",
                "industry_code": industry_code,
                "src": "SW2021",
            }
        )

    l2_codes = ["230500"]
    for index in range(133):
        industry_code = f"{400000 + index:06d}"
        l2_codes.append(industry_code)
        rows.append(
            {
                "index_code": f"{802000 + index:06d}.SI",
                "industry_name": f"二级行业{index:03d}",
                "parent_code": l1_codes[index % len(l1_codes)],
                "level": "L2",
                "industry_code": industry_code,
                "src": "SW2021",
            }
        )

    for index in range(345):
        rows.append(
            {
                "index_code": f"{850000 + index:06d}.SI",
                "industry_name": f"三级行业{index:03d}",
                "parent_code": l2_codes[index % len(l2_codes)],
                "level": "L3",
                "industry_code": f"{500000 + index:06d}",
                "src": "SW2021",
            }
        )

    assert len(rows) == 511
    assert Counter(row["level"] for row in rows) == {"L1": 31, "L2": 134, "L3": 346}
    for index, row in enumerate(rows):
        row["is_pub"] = "1" if index < 414 else "0"
    return rows


class _PagedClassificationConnector:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = deepcopy(rows)
        self.calls: list[dict] = []

    def call(
        self, *, api_name: str, params: dict, fields: tuple[str, ...]
    ) -> list[dict]:
        assert api_name == "index_classify"
        assert fields == SOURCE_FIELDS
        assert params["src"] == "SW2021"
        assert set(params) == {"src", "offset", "limit"}
        self.calls.append(dict(params))
        offset = int(params["offset"])
        limit = int(params["limit"])
        return deepcopy(self.rows[offset : offset + limit])


def _plan():  # type: ignore[no-untyped-def]
    return DatasetActionResolver(None).build_plan(
        DatasetActionRequest(
            dataset_key="index_classify",
            action="maintain",
            time_input=DatasetTimeInput(mode="none"),
        )
    )


def _validated_request(plan) -> ValidatedDatasetActionRequest:  # type: ignore[no-untyped-def]
    return ValidatedDatasetActionRequest(
        request_id=plan.plan_id,
        dataset_key=plan.dataset_key,
        action=plan.action,
        run_profile=plan.run_profile,
        trigger_source="test",
        params=dict(plan.filters),
        source_key=plan.source.source_key,
    )


@pytest.fixture()
def classification_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        SwIndustryClassification.__table__.create(connection)
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def ops_snapshot_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS ops")
        DatasetStatusSnapshot.__table__.create(connection)
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_index_classify_plan_and_pagination_are_sw2021_only(mocker) -> None:
    plan = _plan()
    definition = get_dataset_definition("index_classify")
    connector = _PagedClassificationConnector(_classification_source_rows())
    mocker.patch(
        "src.foundation.ingestion.source_client.create_source_connector",
        return_value=connector,
    )

    result = DatasetSourceClient().fetch(definition=definition, unit=plan.units[0])

    assert plan.run_profile == "snapshot_refresh"
    assert plan.time_scope.mode == "none"
    assert plan.filters == {}
    assert len(plan.units) == 1
    assert plan.units[0].request_params == {}
    assert plan.units[0].page_limit == 200
    assert [call["offset"] for call in connector.calls] == [0, 200, 400]
    assert [
        len(connector.rows[call["offset"] : call["offset"] + 200])
        for call in connector.calls
    ] == [200, 200, 111]
    assert len(result.rows_raw) == 511
    assert result.rows_raw == connector.rows
    assert result.pagination_diagnostics == {
        "policy": "offset_limit",
        "page_limit": 200,
        "page_count": 3,
        "total_rows_merged": 511,
        "terminal_offset": 400,
        "terminal_page_rows": 111,
        "observed_short_page": True,
    }

    with pytest.raises(IngestionValidationError, match="未定义参数：src"):
        DatasetActionResolver(None).build_plan(
            DatasetActionRequest(
                dataset_key="index_classify",
                action="maintain",
                time_input=DatasetTimeInput(mode="none"),
                filters={"src": "SW2014"},
            )
        )
    with pytest.raises(IngestionValidationError):
        DatasetActionResolver(None).build_plan(
            DatasetActionRequest(
                dataset_key="index_classify",
                action="maintain",
                time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 18)),
            )
        )


def test_index_classify_normalization_and_prewrite_enforce_frozen_contract() -> None:
    definition = get_dataset_definition("index_classify")
    rows = _classification_source_rows()
    batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="index-classify-m2",
            request_count=3,
            retry_count=0,
            latency_ms=1,
            rows_raw=rows,
        ),
    )

    assert len(batch.rows_normalized) == 511
    assert batch.rows_rejected == 0
    assert batch.rows_deduplicated == 0
    assert Counter(row["level"] for row in batch.rows_normalized) == {
        "L1": 31,
        "L2": 134,
        "L3": 346,
    }
    assert Counter(row["is_pub"] for row in batch.rows_normalized) == {
        True: 414,
        False: 97,
    }
    alias = next(
        row for row in batch.rows_normalized if row["industry_code"] == "230501"
    )
    assert alias["source_index_code"] == "850401.SI"
    assert alias["index_code"] == "850412.SI"
    assert not any(row["index_code"] == "840401.SI" for row in batch.rows_normalized)
    get_pre_write_validator("sw2021_classification_snapshot")(
        None,  # type: ignore[arg-type]
        batch.rows_normalized,
        definition,
        _plan().units[0],
    )

    typo_rows = deepcopy(rows)
    typo_rows[2]["index_code"] = "840401.SI"
    typo_batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="typo",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=typo_rows,
        ),
    )
    assert typo_batch.rows_rejected == 1
    assert typo_batch.rejected_reasons == {"normalize.sw_industry_code_invalid": 1}

    conflicting_rows = deepcopy(rows)
    conflicting_rows.append({**conflicting_rows[-1], "index_code": "859999.SI"})
    with pytest.raises(IngestionNormalizeError) as exc_info:
        DatasetNormalizer().normalize(
            definition=definition,
            fetch_result=SourceFetchResult(
                unit_id="identity-conflict",
                request_count=1,
                retry_count=0,
                latency_ms=1,
                rows_raw=conflicting_rows,
            ),
        )
    assert (
        exc_info.value.structured_error.error_code
        == "normalize.batch_unique_key_conflicting"
    )

    orphan_rows = deepcopy(batch.rows_normalized)
    orphan_rows[-1]["parent_code"] = "999999"
    with pytest.raises(PreWriteValidationError, match="父子层级不闭合"):
        get_pre_write_validator("sw2021_classification_snapshot")(
            None,  # type: ignore[arg-type]
            orphan_rows,
            definition,
            _plan().units[0],
        )

    duplicate_business_code_rows = deepcopy(batch.rows_normalized)
    duplicate_business_code_rows[-1]["index_code"] = duplicate_business_code_rows[-2][
        "index_code"
    ]
    with pytest.raises(PreWriteValidationError, match="重复业务身份"):
        get_pre_write_validator("sw2021_classification_snapshot")(
            None,  # type: ignore[arg-type]
            duplicate_business_code_rows,
            definition,
            _plan().units[0],
        )


def test_index_classify_executor_replaces_one_scope_idempotently_and_rolls_back(
    classification_session: Session,
    mocker,
) -> None:
    definition = get_dataset_definition("index_classify")
    plan = _plan()
    source_rows = _classification_source_rows()
    connector = _PagedClassificationConnector(source_rows)
    mocker.patch(
        "src.foundation.ingestion.source_client.create_source_connector",
        return_value=connector,
    )
    classification_session.add(
        SwIndustryClassification(
            src="SW2014",
            industry_code="legacy",
            source_index_code="801999.SI",
            index_code="801999.SI",
            industry_name="历史范围保留样本",
            source_parent_code=None,
            parent_code=None,
            level="L1",
            is_pub=True,
            source="test",
            normalization_rule_version="legacy",
        )
    )
    classification_session.commit()

    first = IngestionExecutor(classification_session).run(
        request=_validated_request(plan),
        definition=definition,
        units=plan.units,
    )
    assert first.rows_fetched == 511
    assert first.rows_written == first.rows_committed == 511
    assert first.rows_rejected == 0
    assert first.unit_done == 1
    assert first.ingestion_diagnostics["source"]["pagination"]["unit_samples"] == [
        {
            "unit_id": plan.units[0].unit_id,
            "page_count": 3,
            "terminal_offset": 400,
            "terminal_page_rows": 111,
        }
    ]
    assert (
        classification_session.scalar(
            select(func.count())
            .select_from(SwIndustryClassification)
            .where(SwIndustryClassification.src == "SW2021")
        )
        == 511
    )

    connector.rows = deepcopy(source_rows)
    replay = IngestionExecutor(classification_session).run(
        request=_validated_request(plan),
        definition=definition,
        units=plan.units,
    )
    assert replay.rows_written == replay.rows_committed == 511
    assert (
        replay.ingestion_diagnostics["persistence"]["immutable_fact"][
            "scope_existing_count"
        ]
        == 511
    )

    removed_source_row = source_rows[-1]
    connector.rows = deepcopy(source_rows[:-1])
    shrunk = IngestionExecutor(classification_session).run(
        request=_validated_request(plan),
        definition=definition,
        units=plan.units,
    )
    assert shrunk.rows_written == shrunk.rows_committed == 510
    assert (
        classification_session.scalar(
            select(func.count())
            .select_from(SwIndustryClassification)
            .where(SwIndustryClassification.src == "SW2021")
        )
        == 510
    )
    assert (
        classification_session.scalar(
            select(SwIndustryClassification).where(
                SwIndustryClassification.src == "SW2021",
                SwIndustryClassification.industry_code
                == removed_source_row["industry_code"],
            )
        )
        is None
    )
    assert (
        classification_session.scalar(
            select(func.count())
            .select_from(SwIndustryClassification)
            .where(SwIndustryClassification.src == "SW2014")
        )
        == 1
    )

    orphan_rows = deepcopy(source_rows[:-1])
    orphan_rows[-1]["parent_code"] = "999999"
    connector.rows = orphan_rows
    with pytest.raises(IngestionWriteError) as exc_info:
        IngestionExecutor(classification_session).run(
            request=_validated_request(plan),
            definition=definition,
            units=plan.units,
        )
    assert exc_info.value.structured_error.error_code == "write.scope_preflight_failed"
    assert (
        classification_session.scalar(
            select(func.count())
            .select_from(SwIndustryClassification)
            .where(SwIndustryClassification.src == "SW2021")
        )
        == 510
    )


def test_index_classify_writer_rejects_empty_partial_and_cross_scope_before_dml(
    classification_session: Session,
) -> None:
    definition = get_dataset_definition("index_classify")
    normalized = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="preflight",
            request_count=3,
            retry_count=0,
            latency_ms=1,
            rows_raw=_classification_source_rows(),
        ),
    )
    executor = IngestionExecutor(classification_session)

    with pytest.raises(IngestionWriteError) as empty_error:
        executor.writer.write(
            definition=definition,
            batch=NormalizedBatch(
                unit_id="empty",
                rows_normalized=[],
                rows_rejected=0,
                rejected_reasons={},
            ),
            plan_unit=_plan().units[0],
        )
    assert empty_error.value.structured_error.error_code == "write.scope_empty"

    with pytest.raises(IngestionWriteError) as partial_error:
        executor.writer.write(
            definition=definition,
            batch=NormalizedBatch(
                unit_id="partial",
                rows_normalized=normalized.rows_normalized,
                rows_rejected=1,
                rejected_reasons={"normalize.sw_industry_code_invalid": 1},
            ),
            plan_unit=_plan().units[0],
        )
    assert (
        partial_error.value.structured_error.error_code == "write.scope_rows_rejected"
    )

    cross_scope_rows = deepcopy(normalized.rows_normalized)
    cross_scope_rows[-1]["src"] = "SW2014"
    with pytest.raises(IngestionWriteError) as cross_scope_error:
        executor.writer.write(
            definition=definition,
            batch=NormalizedBatch(
                unit_id="cross-scope",
                rows_normalized=cross_scope_rows,
                rows_rejected=0,
                rejected_reasons={},
            ),
            plan_unit=_plan().units[0],
        )
    assert (
        cross_scope_error.value.structured_error.error_code
        == "write.scope_preflight_failed"
    )
    assert (
        classification_session.scalar(
            select(func.count()).select_from(SwIndustryClassification)
        )
        == 0
    )


def test_index_classify_ops_projection_is_manual_snapshot() -> None:
    route = ManualActionQueryService().get_action_route("index_classify.maintain")
    assert route is not None
    assert route.group_key == "board_theme"
    assert route.action_order == 80
    assert route.filters == ()
    assert route.time_form.default_mode == "none"
    assert [mode.mode for mode in route.time_form.modes] == ["none"]

    projection = get_dataset_freshness_projection("index_classify")
    assert projection is not None
    assert projection.target_table == "core_serving.sw_industry_classification"
    assert projection.raw_table is None
    assert projection.freshness_policy == "snapshot_run_trace"
    assert projection.observed_date_column is None
    assert projection.primary_action_key == "index_classify.maintain"

    definition = get_dataset_definition("index_classify")
    assert definition.completeness.scope == "not_applicable"
    assert definition.date_model.audit_applicable is False
    assert definition.capabilities.get_action("maintain").schedule_enabled is False
    assert (
        ScheduleAutomationCapabilityResolver().resolve(
            target_type="dataset_action",
            target_key="index_classify.maintain",
        )
        is None
    )


def test_index_classify_snapshot_rebuild_keeps_serving_only_projection(
    ops_snapshot_session: Session,
) -> None:
    class _ClassificationFreshnessQueryService:
        def build_live_items(
            self,
            session: Session,
            *,
            today: date | None = None,
            resource_keys: list[str] | None = None,
        ) -> list[DatasetFreshnessItem]:
            assert session is ops_snapshot_session
            assert today == date(2026, 8, 18)
            assert resource_keys == ["index_classify"]
            return [
                DatasetFreshnessItem(
                    dataset_key="index_classify",
                    resource_key="index_classify",
                    display_name="申万 SW2021 行业分类",
                    domain_key="board_theme",
                    domain_display_name="板块 / 题材",
                    target_table="core_serving.sw_industry_classification",
                    freshness_policy="snapshot_run_trace",
                    freshness_status="fresh",
                    last_sync_date=date(2026, 8, 18),
                )
            ]

    service = DatasetStatusSnapshotService(
        query_service=_ClassificationFreshnessQueryService()
    )

    assert (
        service.refresh_resources(
            ops_snapshot_session,
            ["index_classify"],
            today=date(2026, 8, 18),
        )
        == 1
    )
    response = DatasetStatusSnapshotService().read_snapshot(ops_snapshot_session)
    assert response is not None
    item = next(
        item
        for group in response.groups
        for item in group.items
        if item.dataset_key == "index_classify"
    )
    assert item.target_table == "core_serving.sw_industry_classification"
    assert item.raw_table is None
    assert item.freshness_policy == "snapshot_run_trace"
    assert item.latest_business_date is None
    assert item.last_sync_date == date(2026, 8, 18)
