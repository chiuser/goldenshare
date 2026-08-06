from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.foundation.dao.factory import DAOFactory
from src.foundation.dao.observed_snapshot_dao import ObservedSnapshotDAO
from src.foundation.datasets.public_fund_contracts import FUND_BASIC_SOURCE_FIELDS
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion import linter as linter_module
from src.foundation.ingestion.errors import IngestionNormalizeError, IngestionWriteError
from src.foundation.ingestion.linter import lint_all_dataset_definitions
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.source_client import DatasetSourceClient, SourceFetchResult
import src.foundation.ingestion.source_client as source_client_module
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core_serving.fund_basic_current import FundBasicCurrent
from src.foundation.models.core_serving.fund_basic_observation import FundBasicObservation
from src.foundation.models.table_model_registry import table_model_registry
from src.ops.action_catalog import list_workflow_definitions


def _fund_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": "000001.OF",
        "name": "示例基金",
        "management": "示例基金管理有限公司",
        "custodian": "示例银行",
        "fund_type": "混合型",
        "found_date": "20200101",
        "due_date": None,
        "list_date": None,
        "issue_date": "20191201",
        "delist_date": None,
        "issue_amount": 12.3456,
        "m_fee": 1.2,
        "c_fee": 0.2,
        "duration_year": None,
        "p_value": 1.0,
        "min_amount": 0.01,
        "exp_return": None,
        "benchmark": "沪深300指数收益率×60%+中债综合指数收益率×40%",
        "status": "L",
        "invest_type": "主动型",
        "type": "契约型开放式",
        "trustee": None,
        "purc_startdate": "20200102",
        "redm_startdate": "20200102",
        "market": "O",
    }
    row.update(overrides)
    return row


def _source_result(rows: list[dict[str, object]], *, unit_id: str = "fund-basic") -> SourceFetchResult:
    return SourceFetchResult(
        unit_id=unit_id,
        request_count=1,
        retry_count=0,
        latency_ms=0,
        rows_raw=rows,
    )


def test_fund_basic_definition_builds_one_unfiltered_full_snapshot_unit() -> None:
    definition = get_dataset_definition("fund_basic")
    plan = DatasetActionResolver(SimpleNamespace()).build_plan(
        DatasetActionRequest(dataset_key="fund_basic", action="maintain", time_input=DatasetTimeInput(mode="none"))
    )

    assert definition.source.source_fields == FUND_BASIC_SOURCE_FIELDS
    assert len(definition.source.source_fields) == 25
    assert definition.source.base_params == {}
    assert definition.input_model.time_fields == ()
    assert definition.input_model.filters == ()
    assert definition.planning.pagination_policy == "offset_limit"
    assert definition.planning.page_limit == 2_000
    assert definition.planning.enum_fanout_fields == ()
    assert definition.quality.required_distinct_values == {"market": ("E", "O")}
    assert definition.storage.write_path == "serving_observed_snapshot_refresh"
    assert definition.storage.raw_dao_name is None
    assert definition.storage.raw_table is None
    assert definition.capabilities.get_action("maintain").supported_time_modes == ("none",)
    assert len(plan.units) == 1
    assert plan.units[0].trade_date is None
    assert plan.units[0].request_params == {}


def test_fund_basic_source_client_uses_one_unit_explicit_fields_and_short_page(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_basic")
    rows = [
        _fund_row(ts_code=f"{index:06d}.OF", market="O")
        for index in range(4_001)
    ] + [_fund_row(ts_code="510300.SH", market="E")]
    calls: list[tuple[dict, tuple[str, ...]]] = []

    class Connector:
        def call(self, *, api_name: str, params: dict, fields: tuple[str, ...]) -> list[dict]:
            assert api_name == "fund_basic"
            calls.append((dict(params), fields))
            offset = int(params["offset"])
            limit = int(params["limit"])
            return [dict(row) for row in rows[offset : offset + limit]]

    monkeypatch.setattr(source_client_module, "create_source_connector", lambda source_key: Connector())
    plan = DatasetActionResolver(SimpleNamespace()).build_plan(
        DatasetActionRequest(dataset_key="fund_basic", action="maintain", time_input=DatasetTimeInput(mode="none"))
    )

    result = DatasetSourceClient().fetch(definition=definition, unit=plan.units[0])

    assert [params["offset"] for params, _ in calls] == [0, 2_000, 4_000]
    assert all(params["limit"] == 2_000 for params, _ in calls)
    assert all("market" not in params and "status" not in params and "ts_code" not in params for params, _ in calls)
    assert all(fields == FUND_BASIC_SOURCE_FIELDS for _, fields in calls)
    assert result.request_count == 3
    assert result.rows_raw == rows


def test_fund_basic_identity_preserves_source_fields_and_normalizes_only_entity_key() -> None:
    definition = get_dataset_definition("fund_basic")
    source_ts_code = " 000001.of "
    batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=_source_result(
            [
                _fund_row(ts_code=source_ts_code, market="O"),
                _fund_row(ts_code="510300.SH", market="E"),
            ]
        ),
    )

    assert batch.rows_rejected == 0
    assert batch.rows_normalized[0]["ts_code"] == source_ts_code
    assert batch.rows_normalized[0]["source_entity_key"] == "000001.OF"
    assert batch.rows_normalized[0]["identity_basis"] == "ts_code"
    assert batch.rows_normalized[0]["issue_amount"] == Decimal("12.3456")
    assert batch.rows_normalized[0]["benchmark"] == _fund_row()["benchmark"]


@pytest.mark.parametrize(
    ("rows", "missing"),
    (
        ([_fund_row(market="E", ts_code="510300.SH")], ["O"]),
        ([_fund_row(market="O")], ["E"]),
    ),
)
def test_fund_basic_normalizer_rejects_partial_market_snapshot(rows: list[dict[str, object]], missing: list[str]) -> None:
    definition = get_dataset_definition("fund_basic")

    with pytest.raises(IngestionNormalizeError) as exc_info:
        DatasetNormalizer().normalize(definition=definition, fetch_result=_source_result(rows))

    error = exc_info.value.structured_error
    assert error.error_code == "normalize.required_distinct_values_missing"
    assert error.details["field"] == "market"
    assert error.details["missing_values"] == missing


@pytest.mark.parametrize(
    ("required_values", "expected_code"),
    (
        ({"unknown_field": ("X",)}, "required_distinct_field_invalid"),
        ({"market": ()}, "required_distinct_values_empty"),
        ({"market": ("E", "E")}, "required_distinct_values_duplicate"),
    ),
)
def test_definition_linter_rejects_invalid_required_distinct_values(
    monkeypatch,
    required_values: dict[str, tuple[str, ...]],
    expected_code: str,
) -> None:
    definition = get_dataset_definition("fund_basic")
    invalid = replace(definition, quality=replace(definition.quality, required_distinct_values=required_values))
    monkeypatch.setattr(linter_module, "list_dataset_definitions", lambda: (invalid,))
    monkeypatch.setattr(linter_module, "DATASET_RUNTIME_REGISTRY", {invalid.dataset_key: object()})

    report = lint_all_dataset_definitions()

    assert expected_code in {issue.code for issue in report.issues}


@pytest.fixture()
def fund_basic_db_session():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    connection = engine.connect().execution_options(schema_translate_map={"core_serving": None})
    for table in (FundBasicCurrent.__table__, FundBasicObservation.__table__):
        table.create(connection)
    session = Session(connection, future=True)
    try:
        yield session
    finally:
        session.close()
        connection.close()
        engine.dispose()


def _writer(session: Session, mocker) -> DatasetWriter:  # type: ignore[no-untyped-def]
    dao_factory = SimpleNamespace(
        fund_basic_current=ObservedSnapshotDAO(session, FundBasicCurrent),
        fund_basic_observation=ObservedSnapshotDAO(session, FundBasicObservation),
    )
    mocker.patch("src.foundation.ingestion.writer.DAOFactory", return_value=dao_factory)
    return DatasetWriter(session)


def test_fund_basic_writer_preserves_versions_and_replaces_only_complete_snapshot(
    fund_basic_db_session: Session,
    mocker,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_basic")
    writer = _writer(fund_basic_db_session, mocker)
    normalizer = DatasetNormalizer()

    first = normalizer.normalize(
        definition=definition,
        fetch_result=_source_result(
            [
                _fund_row(ts_code="000001.OF", market="O", name="场外基金"),
                _fund_row(ts_code="510300.SH", market="E", name="场内基金"),
            ],
            unit_id="first",
        ),
    )
    mocker.patch("src.foundation.ingestion.writer.utc_now", return_value=datetime(2026, 8, 6, 1, tzinfo=timezone.utc))
    assert writer.write(definition=definition, batch=first).rows_written == 2
    fund_basic_db_session.commit()

    second = normalizer.normalize(
        definition=definition,
        fetch_result=_source_result(
            [
                _fund_row(ts_code="000001.OF", market="O", name="场外基金（更新）"),
                _fund_row(ts_code="510300.SH", market="E", name="场内基金"),
            ],
            unit_id="second",
        ),
    )
    mocker.patch("src.foundation.ingestion.writer.utc_now", return_value=datetime(2026, 8, 6, 2, tzinfo=timezone.utc))
    assert writer.write(definition=definition, batch=second).rows_written == 2
    fund_basic_db_session.commit()

    current = fund_basic_db_session.scalars(select(FundBasicCurrent)).all()
    observations = fund_basic_db_session.scalars(select(FundBasicObservation)).all()
    assert {row.name for row in current} == {"场外基金（更新）", "场内基金"}
    assert len(observations) == 3

    with pytest.raises(IngestionNormalizeError):
        normalizer.normalize(
            definition=definition,
            fetch_result=_source_result([_fund_row(ts_code="510300.SH", market="E")], unit_id="partial"),
        )
    assert {row.name for row in fund_basic_db_session.scalars(select(FundBasicCurrent)).all()} == {
        "场外基金（更新）",
        "场内基金",
    }


def test_fund_basic_writer_rejects_missing_field_partial_reject_and_duplicate_source_record(
    fund_basic_db_session: Session,
    mocker,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_basic")
    writer = _writer(fund_basic_db_session, mocker)
    normalizer = DatasetNormalizer()

    empty_batch = normalizer.normalize(
        definition=definition,
        fetch_result=_source_result([], unit_id="empty"),
    )
    with pytest.raises(IngestionWriteError) as empty_error:
        writer.write(definition=definition, batch=empty_batch)
    assert empty_error.value.structured_error.error_code == "write.snapshot_empty"

    missing_field_rows = [_fund_row(market="O"), _fund_row(ts_code="510300.SH", market="E")]
    missing_field_rows[0].pop("trustee")
    missing_batch = normalizer.normalize(definition=definition, fetch_result=_source_result(missing_field_rows, unit_id="missing"))
    with pytest.raises(IngestionWriteError) as missing_error:
        writer.write(definition=definition, batch=missing_batch)
    assert missing_error.value.structured_error.error_code == "write.source_field_missing"

    rejected_batch = normalizer.normalize(
        definition=definition,
        fetch_result=_source_result(
            [
                _fund_row(market="O"),
                _fund_row(ts_code="510300.SH", market="E"),
                _fund_row(ts_code="   ", market="O"),
            ],
            unit_id="rejected",
        ),
    )
    assert rejected_batch.rows_rejected == 1
    with pytest.raises(IngestionWriteError) as rejected_error:
        writer.write(definition=definition, batch=rejected_batch)
    assert rejected_error.value.structured_error.error_code == "write.snapshot_rows_rejected"

    duplicate_row = _fund_row(market="O")
    duplicate_batch = normalizer.normalize(
        definition=definition,
        fetch_result=_source_result(
            [duplicate_row, dict(duplicate_row), _fund_row(ts_code="510300.SH", market="E")],
            unit_id="duplicate",
        ),
    )
    with pytest.raises(IngestionWriteError) as duplicate_error:
        writer.write(definition=definition, batch=duplicate_batch)
    assert duplicate_error.value.structured_error.error_code == "write.snapshot_duplicate_record"


def test_fund_basic_models_and_daos_are_registered(mocker) -> None:  # type: ignore[no-untyped-def]
    table_model_registry.cache_clear()
    registry = table_model_registry()
    factory = DAOFactory(mocker.Mock())

    assert registry["core_serving.fund_basic_current"] is FundBasicCurrent
    assert registry["core_serving.fund_basic_observation"] is FundBasicObservation
    assert isinstance(factory.fund_basic_current, ObservedSnapshotDAO)
    assert factory.fund_basic_current.model is FundBasicCurrent
    assert isinstance(factory.fund_basic_observation, ObservedSnapshotDAO)
    assert factory.fund_basic_observation.model is FundBasicObservation


def test_fund_basic_is_not_added_to_any_workflow() -> None:
    assert all(
        step.action_key != "fund_basic.maintain"
        for workflow in list_workflow_definitions()
        for step in workflow.steps
    )
