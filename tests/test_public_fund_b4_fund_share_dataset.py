from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.foundation.dao.factory import DAOFactory
from src.foundation.dao.observed_snapshot_dao import ObservedSnapshotDAO
from src.foundation.datasets.public_fund_contracts import FUND_SHARE_SOURCE_FIELDS
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion.errors import IngestionNormalizeError, IngestionValidationError, IngestionWriteError
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.normalizer import DatasetNormalizer, NormalizedBatch
from src.foundation.ingestion.source_client import DatasetSourceClient, SourceFetchResult
import src.foundation.ingestion.source_client as source_client_module
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core_serving.fund_share_current import FundShareCurrent
from src.foundation.models.core_serving.fund_share_observation import FundShareObservation
from src.foundation.models.table_model_registry import table_model_registry
from src.ops.action_catalog import list_workflow_definitions


def _share_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": "000001.OF",
        "trade_date": "20260705",
        "fd_share": "100.5000000000",
        "total_share": "120.0000000000",
        "fund_type": "混合型",
        "market": "O",
    }
    row.update(overrides)
    return row


def _source_result(rows: list[dict[str, object]], *, unit_id: str = "fund-share") -> SourceFetchResult:
    return SourceFetchResult(unit_id=unit_id, request_count=1, retry_count=0, latency_ms=0, rows_raw=rows)


def _unit(trade_date: date, *, unit_id: str = "fund-share") -> PlanUnitSnapshot:
    return PlanUnitSnapshot(
        unit_id=unit_id,
        dataset_key="fund_share",
        source_key="tushare",
        trade_date=trade_date,
        request_params={"trade_date": trade_date.strftime("%Y%m%d")},
        progress_context={},
        pagination_policy="offset_limit",
        page_limit=2_000,
    )


def test_fund_share_definition_and_range_expand_every_natural_day() -> None:
    definition = get_dataset_definition("fund_share")
    plan = DatasetActionResolver(SimpleNamespace()).build_plan(
        DatasetActionRequest(
            dataset_key="fund_share",
            action="maintain",
            time_input=DatasetTimeInput(
                mode="range",
                start_date=date(2026, 7, 4),
                end_date=date(2026, 7, 6),
            ),
        )
    )

    assert definition.source.source_fields == FUND_SHARE_SOURCE_FIELDS
    assert definition.input_model.filters == ()
    assert definition.date_model.date_axis == "natural_day"
    assert definition.date_model.bucket_rule == "not_applicable"
    assert definition.date_model.audit_applicable is False
    assert definition.planning.page_limit == 2_000
    assert definition.planning.fetch_concurrency == 1
    assert definition.storage.write_path == "serving_observed_fact_scope_refresh"
    assert definition.quality.unit_date_field == "trade_date"
    assert definition.quality.batch_unique_key_fields == ("source_entity_key",)
    assert [unit.trade_date for unit in plan.units] == [
        date(2026, 7, 4),
        date(2026, 7, 5),
        date(2026, 7, 6),
    ]
    assert [unit.request_params for unit in plan.units] == [
        {"trade_date": "20260704"},
        {"trade_date": "20260705"},
        {"trade_date": "20260706"},
    ]


@pytest.mark.parametrize("filters", ({"market": "O"}, {"ts_code": "000001.OF"}))
def test_fund_share_rejects_partial_market_or_object_filters(filters: dict[str, object]) -> None:
    with pytest.raises(IngestionValidationError) as exc_info:
        DatasetActionResolver(SimpleNamespace()).build_plan(
            DatasetActionRequest(
                dataset_key="fund_share",
                action="maintain",
                time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 7, 5)),
                filters=filters,
            )
        )
    assert exc_info.value.structured_error.error_code == "unknown_params"


def test_fund_share_source_client_requests_all_fields_on_every_page(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_share")
    calls: list[tuple[dict, tuple[str, ...]]] = []
    total_rows = 4_017

    class Connector:
        def call(self, *, api_name: str, params: dict, fields: tuple[str, ...]) -> list[dict]:
            assert api_name == "fund_share"
            calls.append((dict(params), fields))
            offset = int(params["offset"])
            limit = int(params["limit"])
            return [
                _share_row(ts_code=f"{offset + index:06d}.OF")
                for index in range(max(min(limit, total_rows - offset), 0))
            ]

    monkeypatch.setattr(source_client_module, "create_source_connector", lambda _source_key: Connector())
    result = DatasetSourceClient().fetch(definition=definition, unit=_unit(date(2026, 7, 5)))

    assert [params["offset"] for params, _fields in calls] == [0, 2_000, 4_000]
    assert all(params == {"trade_date": "20260705", "offset": params["offset"], "limit": 2_000} for params, _ in calls)
    assert all(fields == FUND_SHARE_SOURCE_FIELDS for _params, fields in calls)
    assert result.request_count == 3
    assert len(result.rows_raw) == total_rows


def test_fund_share_normalization_preserves_fields_and_enforces_date_and_identity() -> None:
    definition = get_dataset_definition("fund_share")
    source = _share_row(ts_code=" 000001.of ")
    batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=_source_result([source]),
        expected_unit_date=date(2026, 7, 5),
    )

    normalized = batch.rows_normalized[0]
    assert batch.rows_rejected == 0
    assert normalized["ts_code"] == source["ts_code"]
    assert normalized["trade_date"] == date(2026, 7, 5)
    assert normalized["fd_share"] == Decimal("100.5000000000")
    assert normalized["total_share"] == Decimal("120.0000000000")
    assert normalized["source_entity_key"].startswith("share:")
    assert normalized["identity_basis"] == "ts_code_trade_date"

    canonical = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=_source_result([_share_row(ts_code="000001.OF")]),
        expected_unit_date=date(2026, 7, 5),
    ).rows_normalized[0]
    assert normalized["source_entity_key"] == canonical["source_entity_key"]

    with pytest.raises(IngestionNormalizeError) as mismatch:
        DatasetNormalizer().normalize(
            definition=definition,
            fetch_result=_source_result([_share_row(trade_date="20260706")]),
            expected_unit_date=date(2026, 7, 5),
        )
    assert mismatch.value.structured_error.error_code == "normalize.unit_date_mismatch"


@pytest.mark.parametrize(
    ("second_row", "expected_code"),
    (
        (_share_row(), "normalize.batch_unique_key_duplicate"),
        (_share_row(fd_share="101"), "normalize.batch_unique_key_conflicting"),
    ),
)
def test_fund_share_rejects_duplicate_or_conflicting_entity(
    second_row: dict[str, object],
    expected_code: str,
) -> None:
    definition = get_dataset_definition("fund_share")
    with pytest.raises(IngestionNormalizeError) as exc_info:
        DatasetNormalizer().normalize(
            definition=definition,
            fetch_result=_source_result([_share_row(), second_row]),
            expected_unit_date=date(2026, 7, 5),
        )
    assert exc_info.value.structured_error.error_code == expected_code


@pytest.fixture()
def fund_share_db_session():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    connection = engine.connect().execution_options(schema_translate_map={"core_serving": None})
    FundShareCurrent.__table__.create(connection)
    FundShareObservation.__table__.create(connection)
    connection.commit()
    session = Session(connection, future=True)
    try:
        yield session
    finally:
        session.close()
        connection.close()
        engine.dispose()


def _writer(session: Session, mocker) -> DatasetWriter:  # type: ignore[no-untyped-def]
    factory = SimpleNamespace(
        fund_share_current=ObservedSnapshotDAO(session, FundShareCurrent),
        fund_share_observation=ObservedSnapshotDAO(session, FundShareObservation),
    )
    mocker.patch("src.foundation.ingestion.writer.DAOFactory", return_value=factory)
    return DatasetWriter(session)


def _normalized(rows: list[dict[str, object]], *, unit_date: date, unit_id: str) -> NormalizedBatch:
    return DatasetNormalizer().normalize(
        definition=get_dataset_definition("fund_share"),
        fetch_result=_source_result(rows, unit_id=unit_id),
        expected_unit_date=unit_date,
    )


def test_fund_share_writer_replaces_only_one_day_and_preserves_observation_versions(
    fund_share_db_session: Session,
    mocker,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_share")
    writer = _writer(fund_share_db_session, mocker)
    day_one = date(2026, 7, 5)
    day_two = date(2026, 7, 6)
    times = [datetime(2026, 8, 7, hour, tzinfo=timezone.utc) for hour in (1, 2, 3)]

    first = _normalized([_share_row(), _share_row(ts_code="000002.OF")], unit_date=day_one, unit_id="first")
    mocker.patch("src.foundation.ingestion.writer.utc_now", return_value=times[0])
    writer.write(definition=definition, batch=first, plan_unit=_unit(day_one, unit_id="first"))
    fund_share_db_session.commit()

    other_day = _normalized(
        [_share_row(trade_date="20260706", fd_share="200")],
        unit_date=day_two,
        unit_id="other-day",
    )
    mocker.patch("src.foundation.ingestion.writer.utc_now", return_value=times[1])
    writer.write(definition=definition, batch=other_day, plan_unit=_unit(day_two, unit_id="other-day"))
    fund_share_db_session.commit()

    changed = _normalized([_share_row(fd_share="101")], unit_date=day_one, unit_id="changed")
    mocker.patch("src.foundation.ingestion.writer.utc_now", return_value=times[2])
    result = writer.write(definition=definition, batch=changed, plan_unit=_unit(day_one, unit_id="changed"))
    fund_share_db_session.commit()

    current = fund_share_db_session.scalars(select(FundShareCurrent).order_by(FundShareCurrent.trade_date)).all()
    observations = fund_share_db_session.scalars(select(FundShareObservation)).all()
    assert result.rows_written == 1
    assert [(row.trade_date, row.ts_code, row.fd_share) for row in current] == [
        (day_one, "000001.OF", Decimal("101.0000000000")),
        (day_two, "000001.OF", Decimal("200.0000000000")),
    ]
    assert len(observations) == 4
    assert {row.fd_share for row in observations if row.trade_date == day_one and row.ts_code == "000001.OF"} == {
        Decimal("100.5000000000"),
        Decimal("101.0000000000"),
    }


def test_fund_share_empty_day_is_noop_and_rejected_rows_fail_closed(
    fund_share_db_session: Session,
    mocker,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_share")
    writer = _writer(fund_share_db_session, mocker)
    day = date(2026, 7, 5)
    first = _normalized([_share_row()], unit_date=day, unit_id="first")
    writer.write(definition=definition, batch=first, plan_unit=_unit(day, unit_id="first"))
    fund_share_db_session.commit()

    empty = NormalizedBatch(unit_id="empty", rows_normalized=[], rows_rejected=0, rejected_reasons={})
    assert writer.write(definition=definition, batch=empty, plan_unit=_unit(day, unit_id="empty")).rows_written == 0
    fund_share_db_session.commit()
    assert fund_share_db_session.scalar(select(FundShareCurrent.fd_share)) == Decimal("100.5000000000")

    rejected = NormalizedBatch(
        unit_id="rejected",
        rows_normalized=[],
        rows_rejected=1,
        rejected_reasons={"normalize.empty_not_allowed:market": 1},
    )
    with pytest.raises(IngestionWriteError) as exc_info:
        writer.write(definition=definition, batch=rejected, plan_unit=_unit(day, unit_id="rejected"))
    assert exc_info.value.structured_error.error_code == "write.fact_rows_rejected"

    missing_optional_source_field = _normalized(
        [{key: value for key, value in _share_row().items() if key != "total_share"}],
        unit_date=day,
        unit_id="missing-source-field",
    )
    with pytest.raises(IngestionWriteError) as missing_exc:
        writer.write(
            definition=definition,
            batch=missing_optional_source_field,
            plan_unit=_unit(day, unit_id="missing-source-field"),
        )
    assert missing_exc.value.structured_error.error_code == "write.source_field_missing"


def test_fund_share_identical_rerun_advances_observation_without_adding_a_version(
    fund_share_db_session: Session,
    mocker,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_share")
    writer = _writer(fund_share_db_session, mocker)
    day = date(2026, 7, 5)
    first_at = datetime(2026, 8, 7, 1, tzinfo=timezone.utc)
    second_at = datetime(2026, 8, 7, 2, tzinfo=timezone.utc)

    mocker.patch("src.foundation.ingestion.writer.utc_now", return_value=first_at)
    writer.write(
        definition=definition,
        batch=_normalized([_share_row()], unit_date=day, unit_id="first"),
        plan_unit=_unit(day, unit_id="first"),
    )
    fund_share_db_session.commit()
    mocker.patch("src.foundation.ingestion.writer.utc_now", return_value=second_at)
    writer.write(
        definition=definition,
        batch=_normalized([_share_row()], unit_date=day, unit_id="second"),
        plan_unit=_unit(day, unit_id="second"),
    )
    fund_share_db_session.commit()

    current = fund_share_db_session.scalars(select(FundShareCurrent)).one()
    observation = fund_share_db_session.scalars(select(FundShareObservation)).one()
    assert current.observed_at.replace(tzinfo=timezone.utc) == second_at
    assert observation.first_observed_at.replace(tzinfo=timezone.utc) == first_at
    assert observation.last_observed_at.replace(tzinfo=timezone.utc) == second_at


def test_fund_share_scope_replace_rolls_back_current_and_observation_together(
    fund_share_db_session: Session,
    mocker,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_share")
    writer = _writer(fund_share_db_session, mocker)
    day = date(2026, 7, 5)
    writer.write(
        definition=definition,
        batch=_normalized([_share_row()], unit_date=day, unit_id="seed"),
        plan_unit=_unit(day, unit_id="seed"),
    )
    fund_share_db_session.commit()

    current_dao = writer.dao.fund_share_current

    class FailingCurrentDao:
        model = FundShareCurrent

        def acquire_scope_lock(self, *, scope_field, scope_value):  # type: ignore[no-untyped-def]
            return current_dao.acquire_scope_lock(scope_field=scope_field, scope_value=scope_value)

        def replace_current_scope(self, rows, **kwargs):  # type: ignore[no-untyped-def]
            current_dao.replace_current_scope(rows, **kwargs)
            raise RuntimeError("injected scope replace failure")

    writer.dao.fund_share_current = FailingCurrentDao()
    with pytest.raises(IngestionWriteError) as exc_info:
        writer.write(
            definition=definition,
            batch=_normalized([_share_row(fd_share="101")], unit_date=day, unit_id="changed"),
            plan_unit=_unit(day, unit_id="changed"),
        )
    assert exc_info.value.structured_error.error_code == "write_failed"
    fund_share_db_session.rollback()

    current = fund_share_db_session.scalars(select(FundShareCurrent)).all()
    observations = fund_share_db_session.scalars(select(FundShareObservation)).all()
    assert [(row.fd_share, row.trade_date) for row in current] == [(Decimal("100.5000000000"), day)]
    assert [(row.fd_share, row.trade_date) for row in observations] == [(Decimal("100.5000000000"), day)]


def test_fund_share_dao_factory_models_catalog_and_workflow_boundaries(fund_share_db_session: Session) -> None:
    factory = DAOFactory(fund_share_db_session)
    definition = get_dataset_definition("fund_share")
    assert factory.fund_share_current.model is FundShareCurrent
    assert factory.fund_share_observation.model is FundShareObservation
    assert table_model_registry().get("core_serving.fund_share_current") is FundShareCurrent
    assert definition.action_key("maintain") not in {
        step.action_key for workflow in list_workflow_definitions() for step in workflow.steps
    }
    assert definition.capabilities.get_action("maintain").schedule_time_policy.policy == "trigger_day_point"
