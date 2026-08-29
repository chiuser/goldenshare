from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.foundation.dao.factory import DAOFactory
from src.foundation.dao.generic import GenericDAO
from src.foundation.datasets.definitions.low_frequency import EXPRESS_SOURCE_FIELDS
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion.errors import IngestionNormalizeError, IngestionPlanningError, IngestionValidationError, IngestionWriteError
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.normalizer import DatasetNormalizer, NormalizedBatch
from src.foundation.ingestion.source_client import DatasetSourceClient, SourceFetchResult
import src.foundation.ingestion.source_client as source_client_module
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core_serving.equity_express import EquityExpress
from src.foundation.models.table_model_registry import table_model_registry
from src.ops.action_catalog import list_workflow_definitions
from src.ops.catalog.dataset_catalog_views import OPS_DATASET_DEFAULT_VIEW


def _express_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": "000001.SZ",
        "ann_date": "20250408",
        "end_date": "20241231",
        **{field: "1.25" for field in EXPRESS_SOURCE_FIELDS[3:29]},
        "perf_summary": "业绩稳定增长",
        "is_audit": 2,
        "remark": "示例",
        "update_flag": "0",
    }
    row.update(overrides)
    return row


def _source_result(rows: list[dict[str, object]], *, unit_id: str = "express") -> SourceFetchResult:
    return SourceFetchResult(unit_id=unit_id, request_count=1, retry_count=0, latency_ms=0, rows_raw=rows)


def _unit(unit_date: date, *, unit_id: str = "express") -> PlanUnitSnapshot:
    return PlanUnitSnapshot(
        unit_id=unit_id,
        dataset_key="express",
        source_key="tushare",
        trade_date=unit_date,
        request_params={"ann_date": unit_date.strftime("%Y%m%d")},
        progress_context={"ann_date": unit_date.isoformat(), "date_field": "ann_date"},
        pagination_policy="offset_limit",
        page_limit=5_000,
    )


def _normalized(rows: list[dict[str, object]], *, unit_date: date, unit_id: str = "express") -> NormalizedBatch:
    return DatasetNormalizer().normalize(
        definition=get_dataset_definition("express"),
        fetch_result=_source_result(rows, unit_id=unit_id),
        expected_unit_date=unit_date,
    )


def test_express_definition_freezes_full_fields_daily_units_and_storage_contract() -> None:
    definition = get_dataset_definition("express")
    point_plan = DatasetActionResolver(SimpleNamespace()).build_plan(
        DatasetActionRequest(
            dataset_key="express",
            action="maintain",
            time_input=DatasetTimeInput(mode="point", ann_date=date(2025, 4, 8)),
        )
    )
    range_plan = DatasetActionResolver(SimpleNamespace()).build_plan(
        DatasetActionRequest(
            dataset_key="express",
            action="maintain",
            time_input=DatasetTimeInput(mode="range", start_date=date(2025, 4, 8), end_date=date(2025, 4, 10)),
        )
    )

    assert len(EXPRESS_SOURCE_FIELDS) == 33
    assert definition.source.api_name == "express_vip"
    assert definition.source.source_fields == EXPRESS_SOURCE_FIELDS
    assert definition.input_model.filters == ()
    assert definition.date_model.input_shape == "ann_date_or_start_end"
    assert definition.date_model.bucket_rule == "not_applicable"
    assert definition.date_model.audit_applicable is False
    assert definition.planning.page_limit == 5_000
    assert definition.planning.max_units_per_execution == 366
    assert definition.planning.fetch_concurrency == 1
    assert definition.storage.write_path == "serving_revisable_fact_scope_upsert"
    assert definition.storage.raw_table is None
    assert definition.storage.observation_table is None
    assert definition.quality.source_multiplicity_policy == "deduplicate_identical"
    assert point_plan.units[0].request_params == {"ann_date": "20250408"}
    assert [unit.request_params for unit in range_plan.units] == [
        {"ann_date": "20250408"},
        {"ann_date": "20250409"},
        {"ann_date": "20250410"},
    ]

    with pytest.raises(IngestionPlanningError) as too_many:
        DatasetActionResolver(SimpleNamespace()).build_plan(
            DatasetActionRequest(
                dataset_key="express",
                action="maintain",
                time_input=DatasetTimeInput(mode="range", start_date=date(2024, 1, 1), end_date=date(2025, 1, 1)),
            )
        )
    assert too_many.value.structured_error.error_code == "units_exceeded"


@pytest.mark.parametrize("filters", ({"ts_code": "000001.SZ"}, {"period": "20241231"}))
def test_express_rejects_operational_filters(filters: dict[str, object]) -> None:
    with pytest.raises(IngestionValidationError) as exc_info:
        DatasetActionResolver(SimpleNamespace()).build_plan(
            DatasetActionRequest(
                dataset_key="express",
                action="maintain",
                time_input=DatasetTimeInput(mode="point", ann_date=date(2025, 4, 8)),
                filters=filters,
            )
        )
    assert exc_info.value.structured_error.error_code == "unknown_params"


def test_express_source_client_repeats_all_fields_until_short_page(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("express")
    calls: list[tuple[dict, tuple[str, ...]]] = []
    total_rows = 10_001

    class Connector:
        def call(self, *, api_name: str, params: dict, fields: tuple[str, ...]) -> list[dict]:
            calls.append((dict(params), fields))
            assert api_name == "express_vip"
            offset = int(params["offset"])
            limit = int(params["limit"])
            return [
                _express_row(ts_code=f"{offset + index:06d}.SZ")
                for index in range(max(min(limit, total_rows - offset), 0))
            ]

    monkeypatch.setattr(source_client_module, "create_source_connector", lambda _source_key: Connector())
    result = DatasetSourceClient().fetch(definition=definition, unit=_unit(date(2025, 4, 8)))

    assert [params["offset"] for params, _fields in calls] == [0, 5_000, 10_000]
    assert all(params["ann_date"] == "20250408" and params["limit"] == 5_000 for params, _fields in calls)
    assert all(fields == EXPRESS_SOURCE_FIELDS for _params, fields in calls)
    assert len(result.rows_raw) == total_rows
    assert result.pagination_diagnostics["observed_short_page"] is True


def test_express_source_client_does_not_publish_partial_unit_when_later_page_fails(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("express")
    calls: list[int] = []

    class Connector:
        def call(self, *, api_name: str, params: dict, fields: tuple[str, ...]) -> list[dict]:
            assert api_name == "express_vip"
            assert fields == EXPRESS_SOURCE_FIELDS
            offset = int(params["offset"])
            calls.append(offset)
            if offset == 5_000:
                raise RuntimeError("source page failed")
            return [_express_row(ts_code=f"{index:06d}.SZ") for index in range(5_000)]

    monkeypatch.setattr(source_client_module, "create_source_connector", lambda _source_key: Connector())
    with pytest.raises(RuntimeError, match="source page failed"):
        DatasetSourceClient().fetch(definition=definition, unit=_unit(date(2025, 4, 8)))

    assert calls == [0, 5_000]


def test_express_identity_exact_duplicate_conflict_missing_field_and_unit_date_are_fail_closed() -> None:
    day = date(2025, 4, 8)
    exact = _normalized([_express_row(), _express_row()], unit_date=day)
    assert exact.rows_deduplicated == 1
    assert len(exact.rows_normalized) == 1
    assert exact.rows_normalized[0]["identity_basis"] == "ts_code_ann_date_end_date"
    expected_identity = json.dumps(
        ["000001.SZ", "2025-04-08", "2024-12-31"],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert exact.rows_normalized[0]["source_entity_key"] == (
        f"express:{hashlib.sha256(expected_identity.encode('utf-8')).hexdigest()}"
    )
    source_spelling = _normalized([_express_row(ts_code=" 000001.sz ")], unit_date=day)
    assert source_spelling.rows_normalized[0]["ts_code"] == " 000001.sz "
    assert source_spelling.rows_normalized[0]["source_entity_key"] == exact.rows_normalized[0]["source_entity_key"]

    with pytest.raises(IngestionNormalizeError) as conflict:
        _normalized([_express_row(), _express_row(revenue="9.99")], unit_date=day)
    assert conflict.value.structured_error.error_code == "normalize.batch_unique_key_conflicting"

    missing = _express_row()
    missing.pop("update_flag")
    with pytest.raises(IngestionNormalizeError) as missing_field:
        _normalized([missing], unit_date=day)
    assert missing_field.value.structured_error.error_code == "normalize.source_content_hash_invalid"

    with pytest.raises(IngestionNormalizeError) as mismatch:
        _normalized([_express_row(ann_date="20250409")], unit_date=day)
    assert mismatch.value.structured_error.error_code == "normalize.unit_date_mismatch"


@pytest.fixture()
def express_db_session():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    connection = engine.connect().execution_options(schema_translate_map={"core_serving": None})
    EquityExpress.__table__.create(connection)
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
        return_value=SimpleNamespace(equity_express=GenericDAO(session, EquityExpress)),
    )
    return DatasetWriter(session)


def test_express_writer_is_idempotent_updates_source_revisions_and_rejects_scope_regression(
    express_db_session: Session,
    mocker,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("express")
    writer = _writer(express_db_session, mocker)
    day = date(2025, 4, 8)
    batch = _normalized([_express_row(), _express_row(ts_code="000002.SZ")], unit_date=day)
    first = writer.write(definition=definition, batch=batch, plan_unit=_unit(day))
    express_db_session.commit()
    second = writer.write(definition=definition, batch=batch, plan_unit=_unit(day, unit_id="rerun"))
    express_db_session.commit()
    assert (first.rows_inserted, first.rows_matched) == (2, 0)
    assert (second.rows_inserted, second.rows_matched) == (0, 2)
    stored = express_db_session.scalar(
        select(EquityExpress).where(EquityExpress.ts_code == "000001.SZ")
    )
    assert stored is not None
    assert (stored.ann_date, stored.end_date) == (date(2025, 4, 8), date(2024, 12, 31))
    assert all(getattr(stored, field) == pytest.approx(1.25) for field in EXPRESS_SOURCE_FIELDS[3:29])
    assert (stored.perf_summary, stored.is_audit, stored.remark, stored.update_flag) == (
        "业绩稳定增长",
        2,
        "示例",
        "0",
    )

    first_ingested_at = stored.ingested_at

    with pytest.raises(IngestionWriteError) as regression:
        writer.write(
            definition=definition,
            batch=_normalized([_express_row()], unit_date=day, unit_id="regression"),
            plan_unit=_unit(day, unit_id="regression"),
        )
    assert regression.value.structured_error.error_code == "write.revisable_fact_scope_regression"
    express_db_session.rollback()

    revised = writer.write(
        definition=definition,
        batch=_normalized(
            [_express_row(is_audit=0), _express_row(ts_code="000002.SZ")],
            unit_date=day,
            unit_id="revised",
        ),
        plan_unit=_unit(day, unit_id="revised"),
    )
    express_db_session.commit()
    assert (revised.rows_inserted, revised.rows_upserted, revised.rows_matched) == (0, 1, 1)
    express_db_session.expire_all()
    revised_stored = express_db_session.scalar(
        select(EquityExpress).where(EquityExpress.ts_code == "000001.SZ")
    )
    assert revised_stored is not None
    assert revised_stored.is_audit == 0
    assert revised_stored.ingested_at != first_ingested_at

    after_revision = writer.write(
        definition=definition,
        batch=_normalized(
            [_express_row(is_audit=0), _express_row(ts_code="000002.SZ")],
            unit_date=day,
            unit_id="after-revision",
        ),
        plan_unit=_unit(day, unit_id="after-revision"),
    )
    express_db_session.commit()
    assert (after_revision.rows_inserted, after_revision.rows_upserted, after_revision.rows_matched) == (0, 0, 2)

    partial = NormalizedBatch(
        unit_id="partial",
        rows_normalized=batch.rows_normalized,
        rows_rejected=1,
        rejected_reasons={"normalize.invalid_date:end_date": 1},
    )
    with pytest.raises(IngestionWriteError) as rejected:
        writer.write(definition=definition, batch=partial, plan_unit=_unit(day, unit_id="partial"))
    assert rejected.value.structured_error.error_code == "write.revisable_fact_rows_rejected"
    express_db_session.rollback()
    assert len(express_db_session.scalars(select(EquityExpress)).all()) == 2


def test_express_ten_thousand_row_unit_is_deduplicated_and_updates_current_facts_atomically(
    express_db_session: Session,
    mocker,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("express")
    writer = _writer(express_db_session, mocker)
    day = date(2025, 4, 8)
    rows = [_express_row(ts_code=f"{index:06d}.SZ") for index in range(10_000)]
    batch = _normalized([*rows, dict(rows[0])], unit_date=day, unit_id="capacity")

    assert len(batch.rows_normalized) == 10_000
    assert batch.rows_deduplicated == 1
    outcome = writer.write(definition=definition, batch=batch, plan_unit=_unit(day, unit_id="capacity"))
    express_db_session.commit()
    assert outcome.rows_inserted == 10_000

    changed_rows = list(rows)
    changed_rows[0] = _express_row(ts_code="000000.SZ", revenue="9.99")
    changed = _normalized(changed_rows, unit_date=day, unit_id="capacity-conflict")
    revised = writer.write(
        definition=definition,
        batch=changed,
        plan_unit=_unit(day, unit_id="capacity-revision"),
    )
    express_db_session.commit()
    assert (revised.rows_inserted, revised.rows_upserted, revised.rows_matched) == (0, 1, 9_999)
    stored = express_db_session.scalar(select(EquityExpress).where(EquityExpress.ts_code == "000000.SZ"))
    assert stored is not None
    assert stored.revenue == pytest.approx(9.99)
    assert len(express_db_session.scalars(select(EquityExpress)).all()) == 10_000


def test_express_registry_dao_catalog_workflow_and_migration_contracts() -> None:
    table_model_registry.cache_clear()
    assert table_model_registry()["core_serving.equity_express"] is EquityExpress
    factory = DAOFactory(SimpleNamespace())
    assert isinstance(factory.equity_express, GenericDAO)
    assert factory.equity_express.model is EquityExpress
    assert set(EquityExpress.__table__.columns.keys()) == {
        "source_entity_key",
        "source_content_hash",
        "identity_basis",
        *EXPRESS_SOURCE_FIELDS,
        "ingested_at",
    }
    group = next(group for group in OPS_DATASET_DEFAULT_VIEW.groups if group.group_key == "equity_financial")
    item = next(item for item in OPS_DATASET_DEFAULT_VIEW.items if item.dataset_key == "express")
    assert (group.group_label, group.group_order) == ("A股财务数据", 3)
    assert (item.group_key, item.item_order) == ("equity_financial", 10)
    assert [group.group_order for group in OPS_DATASET_DEFAULT_VIEW.groups] == list(range(1, 16))
    assert len({group.group_key for group in OPS_DATASET_DEFAULT_VIEW.groups}) == 15
    assert [item.group_key for item in OPS_DATASET_DEFAULT_VIEW.items if item.dataset_key == "express"] == [
        "equity_financial"
    ]
    assert all(all(step.dataset_key != "express" for step in workflow.steps) for workflow in list_workflow_definitions())

    root = Path(__file__).resolve().parents[1]
    migration = (root / "alembic/versions/20260811_000132_add_equity_express_table.py").read_text()
    assert 'down_revision = "20260810_000131"' in migration
    assert migration.index("_assert_hdd_tablespace()") < migration.index('CREATE SCHEMA IF NOT EXISTS')
    assert "postgresql_tablespace=_TABLESPACE" in migration
    assert "ALTER INDEX core_serving.pk_core_serving_equity_express SET TABLESPACE gs_raw_cold_hdd" in migration
    assert "CREATE INDEX idx_equity_express_ts_code_end_ann " in migration
    assert migration.count("TABLESPACE gs_raw_cold_hdd") >= 4
    assert "op.drop_table" not in migration
