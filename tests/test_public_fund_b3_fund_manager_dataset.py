from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import Text, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.foundation.dao.factory import DAOFactory
from src.foundation.dao.observed_snapshot_dao import ObservedSnapshotDAO
from src.foundation.datasets.public_fund_contracts import FUND_MANAGER_SOURCE_FIELDS
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import (
    DatasetActionRequest,
    DatasetActionResolver,
    DatasetTimeInput,
)
from src.foundation.ingestion import linter as linter_module
from src.foundation.ingestion.errors import IngestionNormalizeError, IngestionWriteError
from src.foundation.ingestion.linter import lint_all_dataset_definitions
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.source_client import (
    DatasetSourceClient,
    SourceFetchResult,
)
import src.foundation.ingestion.source_client as source_client_module
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core_serving.fund_manager_current import FundManagerCurrent
from src.foundation.models.core_serving.fund_manager_observation import (
    FundManagerObservation,
)
from src.foundation.models.table_model_registry import table_model_registry
from src.ops.action_catalog import list_workflow_definitions


def _manager_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": "000001.OF",
        "ann_date": "20240115",
        "name": "示例经理",
        "gender": "男",
        "birth_year": "1980",
        "edu": "硕士",
        "nationality": "中国",
        "begin_date": "20200101",
        "end_date": None,
        "resume": "示例履历",
    }
    row.update(overrides)
    return row


def _source_result(
    rows: list[dict[str, object]], *, unit_id: str = "fund-manager"
) -> SourceFetchResult:
    return SourceFetchResult(
        unit_id=unit_id,
        request_count=1,
        retry_count=0,
        latency_ms=0,
        rows_raw=rows,
    )


def test_fund_manager_definition_builds_one_unfiltered_full_snapshot_unit() -> None:
    definition = get_dataset_definition("fund_manager")
    plan = DatasetActionResolver(SimpleNamespace()).build_plan(
        DatasetActionRequest(
            dataset_key="fund_manager",
            action="maintain",
            time_input=DatasetTimeInput(mode="none"),
        )
    )

    assert definition.source.source_fields == FUND_MANAGER_SOURCE_FIELDS
    assert len(definition.source.source_fields) == 10
    assert definition.source.base_params == {}
    assert definition.input_model.time_fields == ()
    assert definition.input_model.filters == ()
    assert definition.planning.pagination_policy == "offset_limit"
    assert definition.planning.page_limit == 5_000
    assert definition.planning.fetch_concurrency == 1
    assert definition.planning.max_units_per_execution is None
    assert definition.quality.batch_unique_key_fields == ("source_entity_key",)
    assert definition.storage.write_path == "serving_observed_snapshot_refresh"
    assert definition.storage.raw_dao_name is None
    assert definition.storage.raw_table is None
    assert definition.capabilities.get_action("maintain").supported_time_modes == (
        "none",
    )
    assert len(plan.units) == 1
    assert plan.units[0].trade_date is None
    assert plan.units[0].request_params == {}


def test_fund_manager_source_client_uses_explicit_fields_and_short_page(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_manager")
    total_rows = 84_357
    calls: list[tuple[dict, tuple[str, ...]]] = []

    class Connector:
        def call(
            self, *, api_name: str, params: dict, fields: tuple[str, ...]
        ) -> list[dict]:
            assert api_name == "fund_manager"
            calls.append((dict(params), fields))
            offset = int(params["offset"])
            limit = int(params["limit"])
            page_size = max(min(limit, total_rows - offset), 0)
            return [
                _manager_row(ts_code=f"{offset + index:06d}.OF")
                for index in range(page_size)
            ]

    monkeypatch.setattr(
        source_client_module, "create_source_connector", lambda source_key: Connector()
    )
    plan = DatasetActionResolver(SimpleNamespace()).build_plan(
        DatasetActionRequest(
            dataset_key="fund_manager",
            action="maintain",
            time_input=DatasetTimeInput(mode="none"),
        )
    )

    result = DatasetSourceClient().fetch(definition=definition, unit=plan.units[0])

    assert [params["offset"] for params, _ in calls] == list(range(0, 85_000, 5_000))
    assert all(params["limit"] == 5_000 for params, _ in calls)
    assert all(
        "ts_code" not in params
        and "ann_date" not in params
        and "start_date" not in params
        for params, _ in calls
    )
    assert all(fields == FUND_MANAGER_SOURCE_FIELDS for _, fields in calls)
    assert result.request_count == 17
    assert len(result.rows_raw) == total_rows
    assert result.rows_raw[0]["ts_code"] == "000000.OF"
    assert result.rows_raw[-1]["ts_code"] == "084356.OF"


def test_fund_manager_identity_preserves_source_fields_and_separates_assignment_from_person() -> (
    None
):
    definition = get_dataset_definition("fund_manager")
    source_row = _manager_row(
        ts_code=" 000001.of ",
        ann_date=" 20240115 ",
        name=" 示例经理 ",
        gender=" m ",
        birth_year=" 1980 ",
        begin_date=" 20200101 ",
    )
    same_person_other_fund = _manager_row(
        ts_code="000002.OF",
        ann_date="20240201",
        name="示例经理",
        gender="M",
        birth_year="1980",
        begin_date="20210101",
    )
    missing_birth_year = _manager_row(
        ts_code="000003.OF",
        ann_date="20240301",
        name="示例经理",
        gender="M",
        birth_year=None,
        begin_date="20220101",
    )
    same_name_different_gender = _manager_row(
        ts_code="000004.OF",
        ann_date="20240401",
        name="示例经理",
        gender="F",
        birth_year="1980",
        begin_date=None,
    )
    batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=_source_result(
            [
                source_row,
                same_person_other_fund,
                missing_birth_year,
                same_name_different_gender,
            ]
        ),
    )

    first, second, third, fourth = batch.rows_normalized
    assert batch.rows_rejected == 0
    assert {field: first[field] for field in FUND_MANAGER_SOURCE_FIELDS} == source_row
    assert first["identity_basis"] == "assignment_fields"
    assert first["source_entity_key"].startswith("assignment:")
    assert first["source_entity_key"] != second["source_entity_key"]
    assert first["manager_identity_key"] == second["manager_identity_key"]
    assert first["manager_identity_key"].startswith("manager:")
    assert third["manager_identity_key"] is None
    assert fourth["begin_date"] is None
    assert fourth["source_entity_key"].startswith("assignment:")
    assert fourth["manager_identity_key"] != first["manager_identity_key"]


def test_fund_manager_assignment_key_uses_normalized_identity_values_only() -> None:
    definition = get_dataset_definition("fund_manager")

    first = (
        DatasetNormalizer()
        .normalize(
            definition=definition,
            fetch_result=_source_result(
                [
                    _manager_row(
                        ts_code=" 000001.of ",
                        ann_date=" 20240115 ",
                        name=" 示例经理 ",
                        begin_date=" 20200101 ",
                    )
                ]
            ),
        )
        .rows_normalized[0]
    )
    second = (
        DatasetNormalizer()
        .normalize(
            definition=definition,
            fetch_result=_source_result(
                [
                    _manager_row(
                        ts_code="000001.OF",
                        ann_date="20240115",
                        name="示例经理",
                        begin_date="20200101",
                    )
                ]
            ),
        )
        .rows_normalized[0]
    )

    assert first["source_entity_key"] == second["source_entity_key"]
    assert first["ts_code"] != second["ts_code"]


@pytest.mark.parametrize("field", ("ts_code", "ann_date", "name"))
def test_fund_manager_rejects_blank_required_source_identity_fields(field: str) -> None:
    definition = get_dataset_definition("fund_manager")

    batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=_source_result([_manager_row(**{field: "   "})]),
    )

    assert batch.rows_rejected == 1
    assert batch.rejected_reasons == {f"normalize.empty_not_allowed:{field}": 1}


@pytest.mark.parametrize(
    ("second_row", "expected_code"),
    (
        (_manager_row(), "normalize.batch_unique_key_duplicate"),
        (
            _manager_row(
                end_date="20231231",
                resume="sensitive-conflicting-resume-" + "x" * 1_000,
            ),
            "normalize.batch_unique_key_conflicting",
        ),
    ),
)
def test_fund_manager_batch_unique_gate_fails_closed_with_bounded_diagnostics(
    second_row: dict[str, object],
    expected_code: str,
) -> None:
    definition = get_dataset_definition("fund_manager")

    with pytest.raises(IngestionNormalizeError) as exc_info:
        DatasetNormalizer().normalize(
            definition=definition,
            fetch_result=_source_result([_manager_row(), second_row]),
        )

    error = exc_info.value.structured_error
    assert error.error_code == expected_code
    assert error.details["key_fields"] == ["source_entity_key"]
    assert error.details["first_row_index"] == 0
    assert error.details["duplicate_row_index"] == 1
    assert len(error.details["first_content_signature"]) == 64
    assert len(error.details["duplicate_content_signature"]) == 64
    assert "x" * 300 not in str(error.details)


@pytest.mark.parametrize(
    ("key_fields", "expected_code"),
    (
        (("",), "batch_unique_key_field_invalid"),
        (
            ("source_entity_key", "source_entity_key"),
            "batch_unique_key_fields_duplicate",
        ),
        (("manager_identity_key",), "batch_unique_key_field_not_required"),
    ),
)
def test_definition_linter_rejects_invalid_batch_unique_key_contract(
    monkeypatch,
    key_fields: tuple[str, ...],
    expected_code: str,
) -> None:
    definition = get_dataset_definition("fund_manager")
    invalid = replace(
        definition,
        quality=replace(definition.quality, batch_unique_key_fields=key_fields),
    )
    monkeypatch.setattr(linter_module, "list_dataset_definitions", lambda: (invalid,))
    monkeypatch.setattr(
        linter_module, "DATASET_RUNTIME_REGISTRY", {invalid.dataset_key: object()}
    )

    report = lint_all_dataset_definitions()

    assert expected_code in {issue.code for issue in report.issues}


@pytest.fixture()
def fund_manager_db_session():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    connection = engine.connect().execution_options(
        schema_translate_map={"core_serving": None}
    )
    for table in (FundManagerCurrent.__table__, FundManagerObservation.__table__):
        table.create(connection)
    connection.commit()
    session = Session(connection, future=True)
    try:
        yield session
    finally:
        session.close()
        connection.close()
        engine.dispose()


def _writer(session: Session, mocker) -> DatasetWriter:  # type: ignore[no-untyped-def]
    dao_factory = SimpleNamespace(
        fund_manager_current=ObservedSnapshotDAO(session, FundManagerCurrent),
        fund_manager_observation=ObservedSnapshotDAO(session, FundManagerObservation),
    )
    mocker.patch("src.foundation.ingestion.writer.DAOFactory", return_value=dao_factory)
    return DatasetWriter(session)


def test_fund_manager_writer_preserves_observation_versions_and_idempotent_repeats(
    fund_manager_db_session: Session,
    mocker,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_manager")
    writer = _writer(fund_manager_db_session, mocker)
    normalizer = DatasetNormalizer()
    first_time = datetime(2026, 8, 6, 1, tzinfo=timezone.utc)
    second_time = datetime(2026, 8, 6, 2, tzinfo=timezone.utc)
    third_time = datetime(2026, 8, 6, 3, tzinfo=timezone.utc)

    first_rows = [
        _manager_row(ts_code="000001.OF", name="经理甲", resume="旧履历"),
        _manager_row(ts_code="000002.OF", name="经理乙", begin_date="20210101"),
    ]
    first = normalizer.normalize(
        definition=definition, fetch_result=_source_result(first_rows, unit_id="first")
    )
    mocker.patch("src.foundation.ingestion.writer.utc_now", return_value=first_time)
    assert writer.write(definition=definition, batch=first).rows_written == 2
    fund_manager_db_session.commit()

    second_rows = [
        _manager_row(ts_code="000001.OF", name="经理甲", resume="新履历"),
        _manager_row(ts_code="000002.OF", name="经理乙", begin_date="20210101"),
    ]
    second = normalizer.normalize(
        definition=definition,
        fetch_result=_source_result(second_rows, unit_id="second"),
    )
    mocker.patch("src.foundation.ingestion.writer.utc_now", return_value=second_time)
    assert writer.write(definition=definition, batch=second).rows_written == 2
    fund_manager_db_session.commit()

    mocker.patch("src.foundation.ingestion.writer.utc_now", return_value=third_time)
    assert writer.write(definition=definition, batch=second).rows_written == 2
    fund_manager_db_session.commit()

    current = fund_manager_db_session.scalars(select(FundManagerCurrent)).all()
    observations = fund_manager_db_session.scalars(select(FundManagerObservation)).all()
    changed = next(
        row
        for row in observations
        if row.ts_code == "000001.OF" and row.resume == "新履历"
    )
    unchanged = next(row for row in observations if row.ts_code == "000002.OF")

    assert len(current) == 2
    assert {row.resume for row in current if row.ts_code == "000001.OF"} == {"新履历"}
    assert len(observations) == 3
    assert changed.first_observed_at.replace(tzinfo=timezone.utc) == second_time
    assert changed.last_observed_at.replace(tzinfo=timezone.utc) == third_time
    assert unchanged.first_observed_at.replace(tzinfo=timezone.utc) == first_time
    assert unchanged.last_observed_at.replace(tzinfo=timezone.utc) == third_time


def test_fund_manager_writer_rejects_empty_missing_field_and_partial_reject(
    fund_manager_db_session: Session,
    mocker,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_manager")
    writer = _writer(fund_manager_db_session, mocker)
    normalizer = DatasetNormalizer()

    empty = normalizer.normalize(
        definition=definition, fetch_result=_source_result([], unit_id="empty")
    )
    with pytest.raises(IngestionWriteError) as empty_error:
        writer.write(definition=definition, batch=empty)
    assert empty_error.value.structured_error.error_code == "write.snapshot_empty"

    missing_source_field = _manager_row()
    missing_source_field.pop("resume")
    missing = normalizer.normalize(
        definition=definition,
        fetch_result=_source_result([missing_source_field], unit_id="missing"),
    )
    with pytest.raises(IngestionWriteError) as missing_error:
        writer.write(definition=definition, batch=missing)
    assert (
        missing_error.value.structured_error.error_code == "write.source_field_missing"
    )

    rejected = normalizer.normalize(
        definition=definition,
        fetch_result=_source_result(
            [_manager_row(), _manager_row(ts_code="   ")], unit_id="rejected"
        ),
    )
    assert rejected.rows_rejected == 1
    with pytest.raises(IngestionWriteError) as rejected_error:
        writer.write(definition=definition, batch=rejected)
    assert (
        rejected_error.value.structured_error.error_code
        == "write.snapshot_rows_rejected"
    )


def test_fund_manager_writer_preserves_long_unicode_resume(
    fund_manager_db_session: Session,
    mocker,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_manager")
    writer = _writer(fund_manager_db_session, mocker)
    long_resume = "基金经理履历🙂" * 104
    batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=_source_result([_manager_row(resume=long_resume)]),
    )

    writer.write(definition=definition, batch=batch)
    fund_manager_db_session.commit()

    assert (
        fund_manager_db_session.scalar(select(FundManagerCurrent.resume)) == long_resume
    )
    assert (
        fund_manager_db_session.scalar(select(FundManagerObservation.resume))
        == long_resume
    )


@pytest.mark.parametrize("delete_before_failure", (False, True))
def test_fund_manager_writer_rollback_restores_current_and_observation_after_fault(
    fund_manager_db_session: Session,
    mocker,
    delete_before_failure: bool,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_manager")
    writer = _writer(fund_manager_db_session, mocker)
    baseline = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=_source_result(
            [_manager_row(resume="baseline")], unit_id="baseline"
        ),
    )
    mocker.patch(
        "src.foundation.ingestion.writer.utc_now",
        return_value=datetime(2026, 8, 6, 1, tzinfo=timezone.utc),
    )
    writer.write(definition=definition, batch=baseline)
    fund_manager_db_session.commit()

    real_current_dao = ObservedSnapshotDAO(fund_manager_db_session, FundManagerCurrent)

    class FailingCurrentDAO:
        model = FundManagerCurrent

        def replace_current_snapshot(self, rows, *, observed_at):  # type: ignore[no-untyped-def]
            if delete_before_failure:
                real_current_dao.replace_current_snapshot(rows, observed_at=observed_at)
            raise RuntimeError("injected fund manager current failure")

    writer.dao.fund_manager_current = FailingCurrentDAO()
    changed = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=_source_result(
            [_manager_row(resume="changed")], unit_id="changed"
        ),
    )
    mocker.patch(
        "src.foundation.ingestion.writer.utc_now",
        return_value=datetime(2026, 8, 6, 2, tzinfo=timezone.utc),
    )

    with pytest.raises(IngestionWriteError) as exc_info:
        writer.write(definition=definition, batch=changed)
    assert exc_info.value.structured_error.error_code == "write_failed"
    fund_manager_db_session.rollback()

    current = fund_manager_db_session.scalars(select(FundManagerCurrent)).all()
    observations = fund_manager_db_session.scalars(select(FundManagerObservation)).all()
    assert [(row.ts_code, row.resume) for row in current] == [("000001.OF", "baseline")]
    assert [(row.ts_code, row.resume) for row in observations] == [
        ("000001.OF", "baseline")
    ]


def test_fund_manager_models_and_daos_are_registered(mocker) -> None:  # type: ignore[no-untyped-def]
    table_model_registry.cache_clear()
    registry = table_model_registry()
    factory = DAOFactory(mocker.Mock())

    assert registry["core_serving.fund_manager_current"] is FundManagerCurrent
    assert registry["core_serving.fund_manager_observation"] is FundManagerObservation
    assert isinstance(factory.fund_manager_current, ObservedSnapshotDAO)
    assert factory.fund_manager_current.model is FundManagerCurrent
    assert isinstance(factory.fund_manager_observation, ObservedSnapshotDAO)
    assert factory.fund_manager_observation.model is FundManagerObservation
    for model in (FundManagerCurrent, FundManagerObservation):
        assert set(FUND_MANAGER_SOURCE_FIELDS).issubset(model.__table__.columns.keys())
        assert all(
            isinstance(model.__table__.columns[field].type, Text)
            for field in FUND_MANAGER_SOURCE_FIELDS
        )


def test_fund_manager_current_has_unique_assignment_defense_and_no_workflow() -> None:
    index = next(
        item
        for item in FundManagerCurrent.__table__.indexes
        if item.name == "uq_fund_manager_current_source_entity_key"
    )
    assert index.unique is True
    assert all(
        step.action_key != "fund_manager.maintain"
        for workflow in list_workflow_definitions()
        for step in workflow.steps
    )
