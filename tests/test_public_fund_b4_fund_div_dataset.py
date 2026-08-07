from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.exceptions import WebAppError
from src.foundation.dao.factory import DAOFactory
from src.foundation.dao.immutable_fact_dao import ImmutableFactDAO
from src.foundation.datasets.public_fund_contracts import FUND_DIV_SOURCE_FIELDS
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion.errors import IngestionNormalizeError, IngestionValidationError, IngestionWriteError
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.normalizer import DatasetNormalizer, NormalizedBatch
from src.foundation.ingestion.source_client import DatasetSourceClient, SourceFetchResult
import src.foundation.ingestion.source_client as source_client_module
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core_serving.fund_div import FundDiv
from src.foundation.models.table_model_registry import table_model_registry
from src.ops.action_catalog import list_workflow_definitions
from src.ops.catalog.dataset_catalog_views import OPS_DATASET_DEFAULT_VIEW
from src.ops.services.dataset_schedule_time_policy_resolver import DatasetScheduleTimePolicyResolver
from src.ops.services.task_run_service import TaskRunCommandService


def _div_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": "000001.OF",
        "ann_date": "20201215",
        "imp_anndate": "20201215",
        "base_date": "20201210",
        "div_proc": "实施",
        "record_date": "20201216",
        "ex_date": "20201217",
        "pay_date": "20201218",
        "earpay_date": None,
        "net_ex_date": None,
        "div_cash": "0.1234000000",
        "base_unit": "1.0000000000",
        "ear_distr": None,
        "ear_amount": None,
        "account_date": "20201218",
        "base_year": "2020",
    }
    row.update(overrides)
    return row


def _source_result(rows: list[dict[str, object]], *, unit_id: str = "fund-div") -> SourceFetchResult:
    return SourceFetchResult(unit_id=unit_id, request_count=1, retry_count=0, latency_ms=0, rows_raw=rows)


def _unit(unit_date: date, *, unit_id: str = "fund-div") -> PlanUnitSnapshot:
    return PlanUnitSnapshot(
        unit_id=unit_id,
        dataset_key="fund_div",
        source_key="tushare",
        trade_date=unit_date,
        request_params={"ann_date": unit_date.strftime("%Y%m%d")},
        progress_context={"ann_date": unit_date.isoformat(), "date_field": "ann_date"},
        pagination_policy="offset_limit",
        page_limit=2_000,
    )


def _normalized(rows: list[dict[str, object]], *, unit_date: date, unit_id: str = "fund-div") -> NormalizedBatch:
    return DatasetNormalizer().normalize(
        definition=get_dataset_definition("fund_div"),
        fetch_result=_source_result(rows, unit_id=unit_id),
        expected_unit_date=unit_date,
    )


def test_fund_div_definition_and_point_range_contract() -> None:
    definition = get_dataset_definition("fund_div")
    point_plan = DatasetActionResolver(SimpleNamespace()).build_plan(
        DatasetActionRequest(
            dataset_key="fund_div",
            action="maintain",
            time_input=DatasetTimeInput(mode="point", ann_date=date(2020, 12, 15)),
        )
    )
    range_plan = DatasetActionResolver(SimpleNamespace()).build_plan(
        DatasetActionRequest(
            dataset_key="fund_div",
            action="maintain",
            time_input=DatasetTimeInput(mode="range", start_date=date(2020, 12, 15), end_date=date(2020, 12, 16)),
        )
    )

    assert definition.source.source_fields == FUND_DIV_SOURCE_FIELDS
    assert definition.input_model.filters == ()
    assert definition.date_model.input_shape == "ann_date_or_start_end"
    assert definition.date_model.bucket_rule == "not_applicable"
    assert definition.date_model.audit_applicable is False
    assert definition.planning.page_limit == 2_000
    assert definition.planning.max_units_per_execution == 366
    assert definition.planning.fetch_concurrency == 1
    assert definition.storage.write_path == "serving_immutable_fact_insert"
    assert definition.storage.raw_table is None
    assert definition.storage.observation_table is None
    assert definition.quality.source_multiplicity_policy == "deduplicate_identical"
    assert point_plan.units[0].request_params == {"ann_date": "20201215"}
    assert point_plan.units[0].progress_context["date_field"] == "ann_date"
    assert [unit.request_params for unit in range_plan.units] == [
        {"ann_date": "20201215"},
        {"ann_date": "20201216"},
    ]


@pytest.mark.parametrize("filters", ({"ts_code": "000001.OF"}, {"div_proc": "实施"}))
def test_fund_div_rejects_operational_filters(filters: dict[str, object]) -> None:
    with pytest.raises(IngestionValidationError) as exc_info:
        DatasetActionResolver(SimpleNamespace()).build_plan(
            DatasetActionRequest(
                dataset_key="fund_div",
                action="maintain",
                time_input=DatasetTimeInput(mode="point", ann_date=date(2020, 12, 15)),
                filters=filters,
            )
        )
    assert exc_info.value.structured_error.error_code == "unknown_params"


def test_fund_div_source_client_uses_explicit_fields_and_short_page_termination(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_div")
    calls: list[tuple[dict, tuple[str, ...]]] = []
    total_rows = 4_017

    class Connector:
        def call(self, *, api_name: str, params: dict, fields: tuple[str, ...]) -> list[dict]:
            calls.append((dict(params), fields))
            assert api_name == "fund_div"
            offset = int(params["offset"])
            limit = int(params["limit"])
            return [
                _div_row(ts_code=f"{offset + index:06d}.OF", record_date=f"2020{(index % 12) + 1:02d}16")
                for index in range(max(min(limit, total_rows - offset), 0))
            ]

    monkeypatch.setattr(source_client_module, "create_source_connector", lambda _source_key: Connector())
    result = DatasetSourceClient().fetch(definition=definition, unit=_unit(date(2020, 12, 15)))

    assert [params["offset"] for params, _fields in calls] == [0, 2_000, 4_000]
    assert all(params["ann_date"] == "20201215" and params["limit"] == 2_000 for params, _fields in calls)
    assert all(fields == FUND_DIV_SOURCE_FIELDS for _params, fields in calls)
    assert len(result.rows_raw) == total_rows
    assert result.pagination_diagnostics == {
        "policy": "offset_limit",
        "page_limit": 2_000,
        "page_count": 3,
        "total_rows_merged": 4_017,
        "terminal_offset": 4_000,
        "terminal_page_rows": 17,
        "observed_short_page": True,
    }


def test_fund_div_exact_duplicate_is_deduplicated_but_identity_content_conflict_fails() -> None:
    day = date(2020, 12, 15)
    exact = _normalized([_div_row(), _div_row()], unit_date=day)
    assert exact.rows_rejected == 0
    assert exact.rows_deduplicated == 1
    assert len(exact.rows_normalized) == 1
    assert exact.rows_normalized[0]["div_cash"] == Decimal("0.1234000000")

    with pytest.raises(IngestionNormalizeError) as exc_info:
        _normalized([_div_row(), _div_row(div_cash="0.999")], unit_date=day)
    assert exc_info.value.structured_error.error_code == "normalize.batch_unique_key_conflicting"

    missing_source_field = _div_row()
    missing_source_field.pop("base_year")
    with pytest.raises(IngestionNormalizeError) as missing:
        _normalized([missing_source_field], unit_date=day)
    assert missing.value.structured_error.error_code == "normalize.source_content_hash_invalid"


def test_fund_div_numeric_capacity_and_unit_date_are_fail_closed() -> None:
    with pytest.raises(IngestionNormalizeError) as mismatch:
        _normalized([_div_row(ann_date="20201216")], unit_date=date(2020, 12, 15))
    assert mismatch.value.structured_error.error_code == "normalize.unit_date_mismatch"

    batch = _normalized([_div_row(div_cash="123456789012345678901.1")], unit_date=date(2020, 12, 15))
    assert batch.rows_rejected == 1
    assert batch.rejected_reasons == {"normalize.numeric_precision_overflow:div_cash": 1}

    non_finite = _normalized([_div_row(div_cash="NaN")], unit_date=date(2020, 12, 15))
    assert non_finite.rows_rejected == 1
    assert non_finite.rejected_reasons == {"normalize.numeric_precision_overflow:div_cash": 1}


@pytest.fixture()
def fund_div_db_session():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    connection = engine.connect().execution_options(schema_translate_map={"core_serving": None})
    FundDiv.__table__.create(connection)
    connection.commit()
    session = Session(connection, future=True)
    try:
        yield session
    finally:
        session.close()
        connection.close()
        engine.dispose()


def _writer(session: Session, mocker) -> DatasetWriter:  # type: ignore[no-untyped-def]
    mocker.patch(
        "src.foundation.ingestion.writer.DAOFactory",
        return_value=SimpleNamespace(fund_div=ImmutableFactDAO(session, FundDiv)),
    )
    return DatasetWriter(session)


def test_fund_div_writer_inserts_then_matches_without_mutation(fund_div_db_session: Session, mocker) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_div")
    writer = _writer(fund_div_db_session, mocker)
    day = date(2020, 12, 15)
    batch = _normalized([_div_row(), _div_row(ts_code="000002.OF")], unit_date=day)

    first = writer.write(definition=definition, batch=batch, plan_unit=_unit(day))
    fund_div_db_session.commit()
    second = writer.write(definition=definition, batch=batch, plan_unit=_unit(day, unit_id="rerun"))
    fund_div_db_session.commit()

    assert (first.rows_written, first.rows_inserted, first.rows_matched) == (2, 2, 0)
    assert (second.rows_written, second.rows_inserted, second.rows_matched) == (2, 0, 2)
    rows = fund_div_db_session.scalars(select(FundDiv).order_by(FundDiv.ts_code)).all()
    assert len(rows) == 2
    assert rows[0].div_cash == Decimal("0.1234000000")


def test_fund_div_writer_rejects_regression_existing_conflict_and_partial_reject(
    fund_div_db_session: Session,
    mocker,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_div")
    writer = _writer(fund_div_db_session, mocker)
    day = date(2020, 12, 15)
    seed = _normalized([_div_row(), _div_row(ts_code="000002.OF")], unit_date=day)
    writer.write(definition=definition, batch=seed, plan_unit=_unit(day))
    fund_div_db_session.commit()

    with pytest.raises(IngestionWriteError) as regression:
        writer.write(
            definition=definition,
            batch=_normalized([_div_row()], unit_date=day, unit_id="regression"),
            plan_unit=_unit(day, unit_id="regression"),
        )
    assert regression.value.structured_error.error_code == "write.immutable_scope_regression"
    fund_div_db_session.rollback()

    changed = _normalized([_div_row(div_cash="0.999"), _div_row(ts_code="000002.OF")], unit_date=day)
    with pytest.raises(IngestionWriteError) as conflict:
        writer.write(definition=definition, batch=changed, plan_unit=_unit(day, unit_id="conflict"))
    assert conflict.value.structured_error.error_code == "write.immutable_fact_conflict"
    fund_div_db_session.rollback()

    partial = NormalizedBatch(
        unit_id="partial",
        rows_normalized=seed.rows_normalized,
        rows_rejected=1,
        rejected_reasons={"normalize.invalid_date:pay_date": 1},
    )
    with pytest.raises(IngestionWriteError) as rejected:
        writer.write(definition=definition, batch=partial, plan_unit=_unit(day, unit_id="partial"))
    assert rejected.value.structured_error.error_code == "write.immutable_rows_rejected"
    fund_div_db_session.rollback()

    missing_identity_basis = _normalized([_div_row(), _div_row(ts_code="000002.OF")], unit_date=day)
    missing_identity_basis.rows_normalized[0].pop("identity_basis")
    with pytest.raises(IngestionWriteError) as invalid_identity:
        writer.write(definition=definition, batch=missing_identity_basis, plan_unit=_unit(day, unit_id="identity"))
    assert invalid_identity.value.structured_error.error_code == "write.immutable_identity_invalid"
    fund_div_db_session.rollback()
    assert len(fund_div_db_session.scalars(select(FundDiv)).all()) == 2


def test_fund_div_empty_scope_only_succeeds_before_any_fact_exists(fund_div_db_session: Session, mocker) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_div")
    writer = _writer(fund_div_db_session, mocker)
    day = date(2020, 12, 15)
    empty = NormalizedBatch(unit_id="empty", rows_normalized=[], rows_rejected=0, rejected_reasons={})
    assert writer.write(definition=definition, batch=empty, plan_unit=_unit(day)).rows_written == 0
    writer.write(definition=definition, batch=_normalized([_div_row()], unit_date=day), plan_unit=_unit(day))
    fund_div_db_session.commit()
    with pytest.raises(IngestionWriteError) as exc_info:
        writer.write(definition=definition, batch=empty, plan_unit=_unit(day))
    assert exc_info.value.structured_error.error_code == "write.immutable_scope_regression"


def test_fund_div_registry_dao_catalog_and_workflow_boundaries() -> None:
    table_model_registry.cache_clear()
    assert table_model_registry()["core_serving.fund_div"] is FundDiv
    factory = DAOFactory(SimpleNamespace())
    assert isinstance(factory.fund_div, ImmutableFactDAO)
    assert factory.fund_div.model is FundDiv
    assert set(FundDiv.__table__.columns.keys()) == {
        "source_entity_key",
        "source_content_hash",
        "identity_basis",
        *FUND_DIV_SOURCE_FIELDS,
        "ingested_at",
    }
    item = next(item for item in OPS_DATASET_DEFAULT_VIEW.items if item.dataset_key == "fund_div")
    assert (item.group_key, item.item_order) == ("public_fund", 60)
    assert all(
        all(step.dataset_key != "fund_div" for step in workflow.steps)
        for workflow in list_workflow_definitions()
    )


def test_fund_div_schedule_contract_generates_ann_date_without_dataset_key_branch() -> None:
    definition = get_dataset_definition("fund_div")
    capability = DatasetScheduleTimePolicyResolver().resolve(definition=definition, action="maintain")[0]
    assert capability.generated_time_field == "ann_date"
    time_input = TaskRunCommandService()._resolve_dataset_action_schedule_time_input(
        session=None,
        definition=definition,
        target_key=definition.action_key("maintain"),
        params_json={},
        calendar_policy="trigger_day_point",
        scheduled_at=datetime(2026, 8, 7, 1, tzinfo=timezone.utc),
        timezone_name="Asia/Shanghai",
    )
    assert time_input == {
        "mode": "point",
        "ann_date": "2026-08-07",
        "date_field": "ann_date",
    }

    service = TaskRunCommandService()
    with pytest.raises(WebAppError, match="不能与固定维护日期或窗口混用"):
        service._resolve_dataset_action_schedule_time_input(
            session=None,
            definition=definition,
            target_key="fund_div.maintain",
            params_json={"time_input": {"mode": "point", "trade_date": "2026-08-07"}},
            calendar_policy="trigger_day_point",
            scheduled_at=datetime(2026, 8, 7, 1, tzinfo=timezone.utc),
            timezone_name="Asia/Shanghai",
        )

    with pytest.raises(WebAppError, match="不支持时间字段：trade_date"):
        service.validate_schedule_target(
            target_type="dataset_action",
            target_key="fund_div.maintain",
            params_json={"time_input": {"mode": "point", "trade_date": "2026-08-07"}},
        )
    service.validate_schedule_target(
        target_type="dataset_action",
        target_key="fund_div.maintain",
        params_json={"ann_date": "2026-08-07"},
    )


def test_fund_div_migrations_are_linear_and_force_hdd() -> None:
    root = Path(__file__).resolve().parents[1]
    diagnostics = (root / "alembic/versions/20260807_000129_add_ingestion_diagnostics.py").read_text()
    fund_div = (root / "alembic/versions/20260807_000130_add_public_fund_b4_fund_div_table.py").read_text()
    assert 'down_revision = "20260807_000128"' in diagnostics
    assert 'down_revision = "20260807_000129"' in fund_div
    assert "gs_raw_cold_hdd" in fund_div
    assert "postgresql_tablespace=_TABLESPACE" in fund_div
    assert "ALTER INDEX core_serving.pk_core_serving_fund_div SET TABLESPACE gs_raw_cold_hdd" in fund_div
    assert 'sa.Column("created_at"' not in fund_div
    assert 'sa.Column("updated_at"' not in fund_div
    assert "op.drop_table" not in fund_div
