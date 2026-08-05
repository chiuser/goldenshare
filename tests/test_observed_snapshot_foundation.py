from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import DateTime, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from src.foundation.dao.observed_snapshot_dao import ObservedSnapshotDAO
from src.foundation.datasets.definitions import ALL_DATASET_ROWS
from src.foundation.datasets.definitions._builder import build_definition
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion.errors import IngestionWriteError
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot, ValidatedDatasetActionRequest
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.observed_snapshot import SourceFieldMissingError, compute_source_content_hash
from src.foundation.ingestion.source_client import SourceFetchResult
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.ingestion import linter as linter_module
from src.foundation.ingestion.linter import lint_all_dataset_definitions
from src.foundation.ingestion.unit_planner import DatasetUnitPlanner


class SnapshotTestBase(DeclarativeBase):
    pass


class SnapshotCurrent(SnapshotTestBase):
    __tablename__ = "snapshot_current"

    source_entity_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    nullable_text: Mapped[str | None] = mapped_column(String(128))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SnapshotObservation(SnapshotTestBase):
    __tablename__ = "snapshot_observation"

    source_entity_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    nullable_text: Mapped[str | None] = mapped_column(String(128))
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@pytest.fixture()
def db_session():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    SnapshotTestBase.metadata.create_all(engine)
    session = Session(engine, future=True)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _definition_row() -> dict:
    row = deepcopy(next(item for item in ALL_DATASET_ROWS if item["identity"]["dataset_key"] == "etf_basic"))
    row["source"]["api_name"] = "observed_snapshot_test"
    row["source"]["source_fields"] = ("source_code", "name", "nullable_text")
    row["input_model"] = {
        "time_fields": (),
        "filters": (),
        "required_groups": (),
        "mutually_exclusive_groups": (),
        "dependencies": (),
    }
    row["storage"] = {
        "raw_dao_name": None,
        "core_dao_name": "snapshot_current",
        "target_table": "snapshot_current",
        "delivery_mode": "single_source_serving",
        "layer_plan": "source->serving",
        "std_table": None,
        "serving_table": "snapshot_current",
        "raw_table": None,
        "observation_dao_name": "snapshot_observation",
        "observation_table": "snapshot_observation",
        "raw_conflict_columns": None,
        "conflict_columns": ("source_entity_key", "source_content_hash"),
        "write_path": "serving_observed_snapshot_refresh",
    }
    row["planning"] = {
        "universe_policy": "no_pool",
        "enum_fanout_fields": (),
        "enum_fanout_defaults": {},
        "pagination_policy": "none",
        "page_limit": None,
        "chunk_size": None,
        "max_units_per_execution": None,
        "unit_builder_key": "generic",
        "fetch_concurrency": 1,
    }
    row["normalization"] = {
        "date_fields": (),
        "decimal_fields": (),
        "required_fields": ("source_entity_key",),
        "row_transform_name": None,
    }
    row["quality"] = {
        "reject_policy": "record_rejections",
        "required_fields": ("source_entity_key",),
        "unit_date_field": None,
        "duplicate_key_policy": "allow",
    }
    return row


def _definition():
    return build_definition(_definition_row())


def _row(entity: str, code: str, name: str | None, nullable_text: str | None = None) -> dict:
    return {
        "source_entity_key": entity,
        "source_code": code,
        "name": name,
        "nullable_text": nullable_text,
    }


def _batch(rows: list[dict], *, rows_rejected: int = 0) -> NormalizedBatch:
    return NormalizedBatch(
        unit_id="observed-snapshot-unit",
        rows_normalized=rows,
        rows_rejected=rows_rejected,
        rejected_reasons={"normalize.required_field_missing": rows_rejected} if rows_rejected else {},
    )


def _writer(session: Session, mocker) -> DatasetWriter:  # type: ignore[no-untyped-def]
    dao_factory = SimpleNamespace(
        snapshot_current=ObservedSnapshotDAO(session, SnapshotCurrent),
        snapshot_observation=ObservedSnapshotDAO(session, SnapshotObservation),
    )
    mocker.patch("src.foundation.ingestion.writer.DAOFactory", return_value=dao_factory)
    return DatasetWriter(session)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def test_observed_snapshot_definition_and_plan_project_both_targets(mocker) -> None:  # type: ignore[no-untyped-def]
    definition = _definition()
    unit = PlanUnitSnapshot(
        unit_id="observed-snapshot-unit",
        dataset_key=definition.dataset_key,
        source_key="tushare",
        trade_date=None,
        request_params={},
        progress_context={},
    )
    mocker.patch("src.foundation.ingestion.resolver.get_dataset_definition", return_value=definition)
    mocker.patch.object(DatasetUnitPlanner, "plan", return_value=(unit,))

    plan = DatasetActionResolver(mocker.Mock()).build_plan(
        DatasetActionRequest(
            dataset_key=definition.dataset_key,
            action="maintain",
            time_input=DatasetTimeInput(mode="none"),
        )
    )

    assert plan.writing.write_path == "serving_observed_snapshot_refresh"
    assert plan.writing.core_dao_name == "snapshot_current"
    assert plan.writing.observation_dao_name == "snapshot_observation"
    assert plan.writing.target_table == "snapshot_current"
    assert plan.writing.observation_table == "snapshot_observation"


@pytest.mark.parametrize(
    ("mutate", "match"),
    (
        (lambda row: row["storage"].pop("observation_dao_name"), "current 与 observation DAO/表"),
        (lambda row: row["storage"].__setitem__("raw_table", "raw_tushare.forbidden"), "不得配置 raw/std 存储"),
        (lambda row: row["storage"].__setitem__("observation_table", "snapshot_current"), "必须与 current target_table 不同"),
        (lambda row: row["storage"].__setitem__("conflict_columns", ("source_entity_key",)), "conflict_columns"),
        (lambda row: row["input_model"].__setitem__("filters", ({"name": "code", "field_type": "string"},)), "不得暴露时间或业务筛选输入"),
        (lambda row: row["source"].__setitem__("source_fields", ("source_code", "source_content_hash")), "不得占用协议元数据列"),
    ),
)
def test_observed_snapshot_definition_rejects_partial_snapshot_contract(mutate, match: str) -> None:  # type: ignore[no-untyped-def]
    row = _definition_row()
    mutate(row)

    with pytest.raises(ValueError, match=match):
        build_definition(row)


def test_observed_snapshot_linter_rejects_invalid_conflict_contract(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    definition = _definition()
    definition = replace(
        definition,
        storage=replace(definition.storage, conflict_columns=("source_entity_key",)),
    )
    monkeypatch.setattr(linter_module, "list_dataset_definitions", lambda: (definition,))
    monkeypatch.setattr(linter_module, "DATASET_RUNTIME_REGISTRY", {definition.dataset_key: object()})

    report = lint_all_dataset_definitions()

    assert [(issue.dataset_key, issue.code) for issue in report.issues] == [
        (definition.dataset_key, "observed_snapshot_conflict_columns_invalid"),
    ]


def test_content_hash_is_field_ordered_type_stable_and_requires_every_source_field() -> None:
    fields = ("first", "second")

    assert compute_source_content_hash(row={"first": Decimal("1.0"), "second": None}, source_fields=fields) == compute_source_content_hash(
        row={"first": Decimal("1.00"), "second": None},
        source_fields=fields,
    )
    assert compute_source_content_hash(row={"first": 1, "second": None}, source_fields=fields) != compute_source_content_hash(
        row={"first": "1", "second": None},
        source_fields=fields,
    )
    with pytest.raises(SourceFieldMissingError, match="second"):
        compute_source_content_hash(row={"first": 1}, source_fields=fields)


def test_writer_preserves_versions_refreshes_current_and_counts_source_rows(db_session: Session, mocker) -> None:  # type: ignore[no-untyped-def]
    definition = _definition()
    writer = _writer(db_session, mocker)
    t1 = datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 5, 2, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 8, 5, 3, 0, tzinfo=timezone.utc)
    first_snapshot = [_row("company:1", "C1", "Alpha"), _row("company:2", "C2", "Beta", None)]
    second_snapshot = [_row("company:1", "C1", "Alpha renamed"), _row("company:3", "C3", "Gamma", "new")]

    mocker.patch("src.foundation.ingestion.writer.utc_now", return_value=t1)
    first_result = writer.write(definition=definition, batch=_batch(first_snapshot))
    db_session.commit()

    mocker.patch("src.foundation.ingestion.writer.utc_now", return_value=t2)
    second_result = writer.write(definition=definition, batch=_batch(second_snapshot))
    db_session.commit()

    mocker.patch("src.foundation.ingestion.writer.utc_now", return_value=t3)
    third_result = writer.write(definition=definition, batch=_batch(second_snapshot))
    db_session.commit()

    current_rows = db_session.scalars(select(SnapshotCurrent).order_by(SnapshotCurrent.source_code)).all()
    observation_rows = db_session.scalars(select(SnapshotObservation).order_by(SnapshotObservation.source_code, SnapshotObservation.name)).all()
    alpha_old = next(row for row in observation_rows if row.source_code == "C1" and row.name == "Alpha")
    alpha_new = next(row for row in observation_rows if row.source_code == "C1" and row.name == "Alpha renamed")

    assert [result.rows_written for result in (first_result, second_result, third_result)] == [2, 2, 2]
    assert all(result.conflict_strategy == "serving_observed_snapshot_refresh" for result in (first_result, second_result, third_result))
    assert [(row.source_code, row.name, row.nullable_text) for row in current_rows] == [
        ("C1", "Alpha renamed", None),
        ("C3", "Gamma", "new"),
    ]
    assert len(observation_rows) == 4
    assert _utc(alpha_old.first_observed_at) == t1
    assert _utc(alpha_old.last_observed_at) == t1
    assert _utc(alpha_new.first_observed_at) == t2
    assert _utc(alpha_new.last_observed_at) == t3


def test_observation_dao_rollback_restores_old_current_and_history(db_session: Session) -> None:
    current_dao = ObservedSnapshotDAO(db_session, SnapshotCurrent)
    observation_dao = ObservedSnapshotDAO(db_session, SnapshotObservation)
    t1 = datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 5, 2, 0, tzinfo=timezone.utc)
    old_row = _row("company:1", "C1", "Alpha")
    old_row["source_content_hash"] = compute_source_content_hash(
        row=old_row,
        source_fields=("source_code", "name", "nullable_text"),
    )
    new_row = _row("company:1", "C1", "Alpha renamed")
    new_row["source_content_hash"] = compute_source_content_hash(
        row=new_row,
        source_fields=("source_code", "name", "nullable_text"),
    )

    observation_dao.record_observations([old_row], observed_at=t1)
    current_dao.replace_current_snapshot([old_row], observed_at=t1)
    db_session.commit()

    with pytest.raises(RuntimeError, match="inject current replace failure"):
        observation_dao.record_observations([new_row], observed_at=t2)
        current_dao.replace_current_snapshot([new_row], observed_at=t2)
        raise RuntimeError("inject current replace failure")
    db_session.rollback()

    current_rows = db_session.scalars(select(SnapshotCurrent)).all()
    observation_rows = db_session.scalars(select(SnapshotObservation)).all()
    assert [(row.source_code, row.name) for row in current_rows] == [("C1", "Alpha")]
    assert [(row.source_code, row.name) for row in observation_rows] == [("C1", "Alpha")]


def test_executor_rolls_back_observation_and_current_when_replace_fails(db_session: Session, mocker) -> None:  # type: ignore[no-untyped-def]
    definition = _definition()
    current_dao = ObservedSnapshotDAO(db_session, SnapshotCurrent)
    observation_dao = ObservedSnapshotDAO(db_session, SnapshotObservation)
    t1 = datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
    old_row = _row("company:1", "C1", "Alpha")
    old_row["source_content_hash"] = compute_source_content_hash(
        row=old_row,
        source_fields=definition.source.source_fields,
    )
    observation_dao.record_observations([old_row], observed_at=t1)
    current_dao.replace_current_snapshot([old_row], observed_at=t1)
    db_session.commit()

    class FailingCurrentDao:
        model = SnapshotCurrent

        def replace_current_snapshot(self, rows, *, observed_at):  # type: ignore[no-untyped-def]
            current_dao.replace_current_snapshot(rows, observed_at=observed_at)
            raise RuntimeError("injected current replace failure")

    writer = _writer(db_session, mocker)
    writer.dao.snapshot_current = FailingCurrentDao()

    class StaticSourceClient:
        def fetch(self, *, definition, unit):  # type: ignore[no-untyped-def]
            return SourceFetchResult(
                unit_id=unit.unit_id,
                request_count=1,
                retry_count=0,
                latency_ms=0,
                rows_raw=[_row("company:1", "C1", "Alpha renamed")],
            )

    unit = PlanUnitSnapshot("observed-snapshot-unit", definition.dataset_key, "tushare", None, {}, {})
    request = ValidatedDatasetActionRequest(
        request_id="snapshot-run",
        dataset_key=definition.dataset_key,
        action="maintain",
        run_profile="snapshot_refresh",
        trigger_source="test",
    )
    executor = IngestionExecutor(db_session)
    executor.source_client = StaticSourceClient()  # type: ignore[assignment]
    executor.writer = writer

    with pytest.raises(IngestionWriteError) as exc_info:
        executor.run(request=request, definition=definition, units=(unit,))

    assert exc_info.value.structured_error.error_code == "write_failed"
    assert [(row.source_code, row.name) for row in db_session.scalars(select(SnapshotCurrent)).all()] == [("C1", "Alpha")]
    assert [(row.source_code, row.name) for row in db_session.scalars(select(SnapshotObservation)).all()] == [("C1", "Alpha")]


@pytest.mark.parametrize(
    ("batch", "error_code"),
    (
        (_batch([], rows_rejected=1), "write.snapshot_rows_rejected"),
        (_batch([]), "write.snapshot_empty"),
        (_batch([{"source_entity_key": "company:1", "source_code": "C1", "name": "Alpha"}]), "write.source_field_missing"),
        (_batch([{"source_code": "C1", "name": "Alpha", "nullable_text": None}]), "write.source_entity_key_missing"),
        (_batch([_row("company:1", "C1", "Alpha"), _row("company:1", "C1", "Alpha")]), "write.snapshot_duplicate_record"),
    ),
)
def test_writer_rejects_any_non_complete_snapshot_before_business_writes(
    db_session: Session,
    mocker,
    batch: NormalizedBatch,
    error_code: str,
) -> None:  # type: ignore[no-untyped-def]
    writer = _writer(db_session, mocker)

    with pytest.raises(IngestionWriteError) as exc_info:
        writer.write(definition=_definition(), batch=batch)

    assert exc_info.value.structured_error.error_code == error_code
    assert db_session.scalars(select(SnapshotCurrent)).all() == []
    assert db_session.scalars(select(SnapshotObservation)).all() == []
