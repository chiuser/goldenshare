from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion import request_builders
from src.foundation.ingestion.errors import IngestionError, IngestionNormalizeError, IngestionWriteError
from src.foundation.ingestion.etf_basic_snapshot import (
    ETF_BASIC_BUSINESS_FIELDS,
    compute_etf_basic_snapshot_hash,
    diff_etf_basic_snapshots,
    validate_etf_basic_snapshot,
)
from src.foundation.ingestion.execution_plan import (
    PlanUnitSnapshot,
    ValidatedDatasetActionRequest,
)
from src.foundation.ingestion.executor import IngestionExecutor, _RunState
from src.foundation.ingestion.normalizer import DatasetNormalizer, NormalizedBatch
from src.foundation.ingestion.source_client import SourceFetchResult
from src.foundation.ingestion.writer import (
    ETF_BASIC_SNAPSHOT_ADVISORY_LOCK_KEY,
    DatasetWriter,
)
from src.foundation.models.core.etf_basic import EtfBasic
from src.foundation.models.raw.raw_etf_basic import RawEtfBasic
from src.ops.services.task_run_ingestion_context import TaskRunIngestionContext


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def register_sqlite_now(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        dbapi_connection.create_function(
            "now",
            0,
            lambda: datetime.now().isoformat(sep=" "),
        )

    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS raw_tushare")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        RawEtfBasic.__table__.create(connection)
        EtfBasic.__table__.create(connection)
    session = Session(engine, future=True)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _row(
    ts_code: str,
    *,
    list_status: str = "L",
    exchange: str | None = None,
    list_date: date | None = date(2024, 1, 2),
    mgt_fee: Decimal = Decimal("0.150000"),
) -> dict:
    suffix = ts_code.rsplit(".", 1)[-1] if "." in ts_code else None
    return {
        "ts_code": ts_code,
        "csname": f"{ts_code} 简称",
        "extname": f"{ts_code} 扩位简称",
        "cname": f"{ts_code} 全称",
        "index_code": "000300.SH",
        "index_name": "沪深300指数",
        "setup_date": date(2023, 12, 1),
        "list_date": list_date,
        "list_status": list_status,
        "exchange": exchange if exchange is not None else suffix,
        "mgr_name": "测试基金",
        "custod_name": "测试托管人",
        "mgt_fee": mgt_fee,
        "etf_type": "境内",
    }


def _valid_rows() -> list[dict]:
    return [
        _row("510300.SH", list_status="L"),
        _row("159919.SZ", list_status="P", list_date=None),
        _row("100000.OF", list_status="D", exchange="OF"),
    ]


def _batch(rows: list[dict], *, rows_rejected: int = 0) -> NormalizedBatch:
    return NormalizedBatch(
        unit_id="etf-basic-snapshot",
        rows_normalized=rows,
        rows_rejected=rows_rejected,
        rejected_reasons={"normalize.invalid_date": rows_rejected} if rows_rejected else {},
    )


def _unit() -> PlanUnitSnapshot:
    return PlanUnitSnapshot(
        unit_id="etf-basic-snapshot",
        dataset_key="etf_basic",
        source_key="tushare",
        trade_date=None,
        request_params={},
        progress_context={},
        pagination_policy="offset_limit",
        page_limit=5000,
    )


def _seed_old_snapshot(session: Session) -> None:
    raw_row = _row("510050.SH")
    serving_row = _row("510050.SH")
    session.add(RawEtfBasic(**raw_row))
    session.add(EtfBasic(**serving_row))
    session.commit()


def _codes(session: Session, model) -> set[str]:  # type: ignore[no-untyped-def]
    return set(session.scalars(select(model.ts_code)))


def test_etf_basic_definition_and_plan_are_complete_snapshot_only(db_session: Session) -> None:
    definition = get_dataset_definition("etf_basic")

    assert definition.input_model.filters == ()
    assert definition.source.source_fields == ETF_BASIC_BUSINESS_FIELDS
    assert definition.source.request_builder_key == "_etf_basic_snapshot_params"
    assert definition.storage.write_path == "raw_etf_basic_snapshot_replace"
    assert definition.planning.page_processing_mode == "buffer_all"
    assert definition.planning.fetch_concurrency == 1
    assert definition.quality.reject_policy == "fail_unit_on_any_rejection"
    assert definition.quality.batch_unique_key_fields == ("ts_code",)
    assert definition.quality.source_multiplicity_policy == "reject"
    assert definition.quality.empty_result_policy == "fail_unit"
    assert definition.quality.pre_write_validator_key == "etf_basic_snapshot"
    assert definition.transaction.commit_policy == "unit"
    assert definition.transaction.idempotent_write_required is True

    plan = DatasetActionResolver(db_session).build_plan(
        DatasetActionRequest(
            dataset_key="etf_basic",
            action="maintain",
            time_input=DatasetTimeInput(mode="none"),
        )
    )
    assert len(plan.units) == 1
    assert plan.units[0].request_params == {}

    with pytest.raises(IngestionError) as error:
        DatasetActionResolver(db_session).build_plan(
            DatasetActionRequest(
                dataset_key="etf_basic",
                action="maintain",
                time_input=DatasetTimeInput(mode="none"),
                filters={"list_status": "L"},
            )
        )
    assert error.value.structured_error.error_code == "unknown_params"


def test_etf_basic_request_builder_defensively_rejects_residual_source_filters() -> None:
    request = ValidatedDatasetActionRequest(
        request_id="etf-basic-request",
        dataset_key="etf_basic",
        action="maintain",
        run_profile="snapshot_refresh",
        trigger_source="manual",
        params={"list_status": "L"},
    )

    with pytest.raises(ValueError, match="不允许源端筛选参数"):
        request_builders._etf_basic_snapshot_params(request, None, {})

    request = ValidatedDatasetActionRequest(
        request_id="etf-basic-request",
        dataset_key="etf_basic",
        action="maintain",
        run_profile="incremental",
        trigger_source="manual",
    )
    with pytest.raises(ValueError, match="只支持不填写日期的完整快照维护"):
        request_builders._etf_basic_snapshot_params(request, None, {})


def test_etf_basic_snapshot_hash_validation_and_diff_are_deterministic() -> None:
    rows = _valid_rows()
    summary = validate_etf_basic_snapshot(
        rows,
        source_row_count=3,
        normalized_row_count=3,
    )
    reordered = [deepcopy(rows[2]), deepcopy(rows[0]), deepcopy(rows[1])]
    reordered[1]["mgt_fee"] = Decimal("0.15")
    reordered[1]["fetched_at"] = "ignored metadata"

    assert summary.status_counts == {"D": 1, "L": 1, "P": 1}
    assert summary.list_date_null_counts == {"D": 0, "L": 0, "P": 1}
    assert compute_etf_basic_snapshot_hash(reordered) == summary.snapshot_hash

    after = deepcopy(rows)
    after.pop(2)
    after[0]["list_status"] = "D"
    after[0]["list_date"] = date(2024, 2, 1)
    after.append(_row("588000.SH"))
    diff = diff_etf_basic_snapshots(rows, after)

    assert diff.added_codes == ("588000.SH",)
    assert diff.removed_codes == ("100000.OF",)
    assert diff.changed_codes == ("510300.SH",)
    assert diff.status_changed_codes == ("510300.SH",)
    assert diff.list_date_changed_codes == ("510300.SH",)

    with pytest.raises(ValueError, match="源端行数"):
        validate_etf_basic_snapshot(
            rows,
            source_row_count=4,
            normalized_row_count=3,
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda rows: rows[0].__setitem__("list_status", "X"), "未知上市状态"),
        (lambda rows: rows[0].__setitem__("ts_code", "510300.BJ"), "未知代码后缀"),
        (lambda rows: rows[0].__setitem__("exchange", "SZ"), "交易所与代码后缀"),
        (lambda rows: rows.append(deepcopy(rows[0])), "重复代码"),
    ),
)
def test_etf_basic_snapshot_rejects_invalid_business_contract(mutate, message: str) -> None:  # type: ignore[no-untyped-def]
    rows = _valid_rows()
    mutate(rows)

    with pytest.raises(ValueError, match=message):
        validate_etf_basic_snapshot(
            rows,
            source_row_count=len(rows),
            normalized_row_count=len(rows),
        )


def test_etf_basic_normalizer_rejects_duplicate_primary_key() -> None:
    rows = [_row("510300.SH"), _row("510300.SH")]
    fetch = SourceFetchResult(
        unit_id="etf-basic-snapshot",
        request_count=1,
        retry_count=0,
        latency_ms=1,
        rows_raw=rows,
    )

    with pytest.raises(IngestionNormalizeError) as error:
        DatasetNormalizer().normalize(
            definition=get_dataset_definition("etf_basic"),
            fetch_result=fetch,
        )
    assert error.value.structured_error.error_code.startswith(
        "normalize.batch_unique_key_"
    )


def test_etf_basic_writer_rebuilds_raw_and_exchange_serving_idempotently(
    db_session: Session,
) -> None:
    _seed_old_snapshot(db_session)
    writer = DatasetWriter(db_session)
    definition = get_dataset_definition("etf_basic")
    rows = _valid_rows()

    result = writer.write(
        definition=definition,
        batch=_batch(rows),
        plan_unit=_unit(),
        run_profile="snapshot_refresh",
    )
    db_session.commit()

    assert _codes(db_session, RawEtfBasic) == {"510300.SH", "159919.SZ", "100000.OF"}
    assert _codes(db_session, EtfBasic) == {"510300.SH", "159919.SZ"}
    assert result.rows_written == 2
    diagnostics = result.persistence_diagnostics["etf_basic_snapshot"]
    assert diagnostics["raw_before_count"] == 1
    assert diagnostics["raw_after_count"] == 3
    assert diagnostics["serving_after_count"] == 2
    assert diagnostics["added_count"] == 3
    assert diagnostics["removed_count"] == 1
    assert diagnostics["source_snapshot_hash"] == diagnostics["raw_business_hash"]

    second = writer.write(
        definition=definition,
        batch=_batch(deepcopy(rows)),
        plan_unit=_unit(),
        run_profile="snapshot_refresh",
    )
    db_session.commit()
    second_diagnostics = second.persistence_diagnostics["etf_basic_snapshot"]
    assert second_diagnostics["added_count"] == 0
    assert second_diagnostics["removed_count"] == 0
    assert second_diagnostics["changed_count"] == 0
    assert second_diagnostics["source_snapshot_hash"] == diagnostics["source_snapshot_hash"]


def test_etf_basic_executor_commits_snapshot_once_and_reports_pagination(
    db_session: Session,
    mocker,
) -> None:  # type: ignore[no-untyped-def]
    _seed_old_snapshot(db_session)
    commit_spy = mocker.spy(db_session, "commit")
    executor = IngestionExecutor(db_session)
    executor.source_client = SimpleNamespace(
        fetch=lambda **_kwargs: SourceFetchResult(
            unit_id="etf-basic-snapshot",
            request_count=2,
            retry_count=0,
            latency_ms=1,
            rows_raw=_valid_rows(),
            pagination_diagnostics={
                "policy": "offset_limit",
                "page_limit": 5000,
                "page_count": 2,
                "total_rows_merged": 3,
                "terminal_offset": 5000,
                "terminal_page_rows": 3,
                "observed_short_page": True,
            },
        )
    )
    request = ValidatedDatasetActionRequest(
        request_id="etf-basic-request",
        dataset_key="etf_basic",
        action="maintain",
        run_profile="snapshot_refresh",
        trigger_source="test",
    )

    summary = executor.run(
        request=request,
        definition=get_dataset_definition("etf_basic"),
        units=(_unit(),),
    )

    assert commit_spy.call_count == 1
    assert summary.unit_done == 1
    assert summary.rows_fetched == 3
    assert summary.rows_written == 2
    assert summary.rows_committed == 2
    snapshot = summary.ingestion_diagnostics["persistence"]["etf_basic_snapshot"]
    assert snapshot["pagination"] == {
        "page_count": 2,
        "terminal_offset": 5000,
        "terminal_page_rows": 3,
        "observed_short_page": True,
    }
    assert _codes(db_session, RawEtfBasic) == {"510300.SH", "159919.SZ", "100000.OF"}
    assert _codes(db_session, EtfBasic) == {"510300.SH", "159919.SZ"}


@pytest.mark.parametrize("rows_rejected", (0, 1))
def test_etf_basic_writer_empty_or_rejected_snapshot_cannot_change_old_rows(
    db_session: Session,
    rows_rejected: int,
) -> None:
    _seed_old_snapshot(db_session)
    rows = [] if rows_rejected == 0 else [_row("510300.SH")]

    with pytest.raises(IngestionWriteError) as error:
        DatasetWriter(db_session).write(
            definition=get_dataset_definition("etf_basic"),
            batch=_batch(rows, rows_rejected=rows_rejected),
            plan_unit=_unit(),
            run_profile="snapshot_refresh",
        )

    assert error.value.structured_error.error_code == "etf_basic_snapshot_invalid"
    assert _codes(db_session, RawEtfBasic) == {"510050.SH"}
    assert _codes(db_session, EtfBasic) == {"510050.SH"}


def test_etf_basic_writer_mid_transaction_failure_rolls_back_both_tables(
    db_session: Session,
    mocker,
) -> None:  # type: ignore[no-untyped-def]
    _seed_old_snapshot(db_session)
    writer = DatasetWriter(db_session)
    mocker.patch.object(
        writer.dao.etf_basic,
        "bulk_insert",
        side_effect=RuntimeError("serving insert failed"),
    )

    with pytest.raises(IngestionWriteError) as error:
        writer.write(
            definition=get_dataset_definition("etf_basic"),
            batch=_batch(_valid_rows()),
            plan_unit=_unit(),
            run_profile="snapshot_refresh",
        )
    assert error.value.structured_error.error_code == "write_failed"

    db_session.rollback()
    assert _codes(db_session, RawEtfBasic) == {"510050.SH"}
    assert _codes(db_session, EtfBasic) == {"510050.SH"}


def test_etf_basic_writer_reconciliation_failure_uses_structured_error_and_rolls_back(
    db_session: Session,
    mocker,
) -> None:  # type: ignore[no-untyped-def]
    _seed_old_snapshot(db_session)
    writer = DatasetWriter(db_session)
    real_bulk_insert = writer.dao.raw_etf_basic.bulk_insert

    def wrong_insert_count(rows):  # type: ignore[no-untyped-def]
        real_bulk_insert(rows)
        return 0

    mocker.patch.object(writer.dao.raw_etf_basic, "bulk_insert", side_effect=wrong_insert_count)

    with pytest.raises(IngestionWriteError) as error:
        writer.write(
            definition=get_dataset_definition("etf_basic"),
            batch=_batch(_valid_rows()),
            plan_unit=_unit(),
            run_profile="snapshot_refresh",
        )
    assert error.value.structured_error.error_code == "etf_basic_snapshot_invalid"

    db_session.rollback()
    assert _codes(db_session, RawEtfBasic) == {"510050.SH"}
    assert _codes(db_session, EtfBasic) == {"510050.SH"}


def test_etf_basic_writer_uses_postgresql_transaction_advisory_lock(mocker) -> None:  # type: ignore[no-untyped-def]
    session = mocker.Mock()
    session.get_bind.return_value = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql")
    )
    writer = DatasetWriter(session)

    writer._lock_etf_basic_snapshot()

    statement, params = session.execute.call_args.args
    assert "pg_advisory_xact_lock" in str(statement)
    assert params == {"lock_key": ETF_BASIC_SNAPSHOT_ADVISORY_LOCK_KEY}


def test_etf_basic_snapshot_diagnostics_flow_and_samples_are_bounded() -> None:
    state = _RunState()
    samples = [f"{index:06d}.SH" for index in range(25)]
    IngestionExecutor._merge_persistence_diagnostics(
        state,
        persistence_diagnostics={
            "etf_basic_snapshot": {
                "source_rows": 25,
                "normalized_rows": 25,
                "source_snapshot_hash": "a" * 64,
                "added_count": 25,
                "added_samples": samples,
            }
        },
        pagination_diagnostics={
            "page_count": 2,
            "terminal_offset": 5000,
            "terminal_page_rows": 12,
            "observed_short_page": True,
        },
    )
    diagnostics = IngestionExecutor._build_ingestion_diagnostics(state)
    sanitized = TaskRunIngestionContext._sanitize_ingestion_diagnostics(diagnostics)
    snapshot = sanitized["persistence"]["etf_basic_snapshot"]

    assert len(snapshot["added_samples"]) == 20
    assert snapshot["samples_truncated"] is True
    assert snapshot["pagination"] == {
        "page_count": 2,
        "terminal_offset": 5000,
        "terminal_page_rows": 12,
        "observed_short_page": True,
    }
