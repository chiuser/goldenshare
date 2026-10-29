"""Pre-listing rules use real source identity and independently specified boundaries.

The checked-in balancesheet fixture was returned by tushareMcp on 2026-10-29.
Other statement rows are synthetic, using their complete source contracts;
SQLite tests exercise real DAO SQL/writer calls, not PostgreSQL deployment.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from src.foundation.dao.security_dao import SecurityDAO
from src.foundation.datasets.balancesheet_contracts import BALANCESHEET_SOURCE_FIELDS
from src.foundation.datasets.cashflow_contracts import CASHFLOW_SOURCE_FIELDS
from src.foundation.datasets.income_contracts import INCOME_SOURCE_FIELDS
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.errors import IngestionNormalizeError, IngestionWriteError
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot, ValidatedDatasetActionRequest
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.source_client import SourceFetchResult
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.raw.raw_balancesheet import RawBalancesheet
from src.foundation.models.raw.raw_cashflow import RawCashflow
from src.foundation.models.raw.raw_income import RawIncome


ANN_DATE = date(2024, 1, 11)
LIST_DATE = date(2026, 9, 29)
CASES = (
    ("income", INCOME_SOURCE_FIELDS, RawIncome),
    ("balancesheet", BALANCESHEET_SOURCE_FIELDS, RawBalancesheet),
    ("cashflow", CASHFLOW_SOURCE_FIELDS, RawCashflow),
)
FIXTURE = json.loads((Path(__file__).parent / "fixtures/financial_statements/balancesheet_920202_prelisting.json").read_text())


def _row(fields, **overrides):
    # Nullable numeric fields follow the producer contracts, not consumer guesses.
    return {
        **dict.fromkeys(fields),
        "ts_code": "920202.BJ", "ann_date": "20240111", "f_ann_date": "20240312",
        "end_date": "20230831", "end_type": "0", "report_type": "1",
        "comp_type": "1", "update_flag": "0", **overrides,
    }


def _fetch(rows):
    return SourceFetchResult(unit_id="financial-test", request_count=1, retry_count=0, latency_ms=0, rows_raw=rows)


def _request_and_unit(key):
    unit = PlanUnitSnapshot(
        unit_id="financial-test", dataset_key=key, source_key="tushare", trade_date=ANN_DATE,
        request_params={"ann_date": "20240111", "report_type": "1"},
        progress_context={"ann_date": "2024-01-11", "report_type": "1"},
        pagination_policy="offset_limit", page_limit=5000,
    )
    request = ValidatedDatasetActionRequest(
        request_id="prelisting-test", dataset_key=key, action="maintain",
        run_profile="point_incremental", trigger_source="test", trade_date=ANN_DATE,
    )
    return request, unit


def _normalize(key, rows, listing_dates):
    loader = Mock(return_value=listing_dates)
    batch = DatasetNormalizer(listing_dates_loader=loader).normalize(
        definition=get_dataset_definition(key), fetch_result=_fetch(rows), expected_unit_date=ANN_DATE,
    )
    return batch, loader


@pytest.mark.parametrize("key,fields,model", CASES)
@pytest.mark.parametrize("listing_dates", ({"920202.BJ": LIST_DATE}, {}, {"920202.BJ": None}))
@pytest.mark.parametrize("end_date", ("20230831", "20230630"))
def test_zero_end_type_preserved_before_listing_or_with_unknown_date(key, fields, model, listing_dates, end_date):
    batch, loader = _normalize(key, [_row(fields, end_date=end_date)], listing_dates)
    assert batch.rows_rejected == 0
    assert len(batch.rows_normalized) == 1
    row = batch.rows_normalized[0]
    assert row["end_type"] == "0"
    assert row["end_date"] == date.fromisoformat(f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}")
    assert set(row) == {*fields, "source_content_hash"}
    loader.assert_called_once_with(["920202.BJ"])


@pytest.mark.parametrize("key,fields,model", CASES)
@pytest.mark.parametrize(
    "end_date,end_type,listing_date,reason",
    (
        ("20260929", "0", LIST_DATE, "normalize.financial_statement_end_date_invalid"),
        ("20260930", "0", LIST_DATE, "normalize.invalid_enum:end_type"),
        ("20260930", "0", date(2026, 9, 30), "normalize.invalid_enum:end_type"),
        ("20230831", "1", LIST_DATE, "normalize.financial_statement_end_date_invalid"),
        ("20230831", None, LIST_DATE, "normalize.financial_statement_end_date_invalid"),
        ("20230630", "3", LIST_DATE, "normalize.end_type_mismatch"),
        ("20230630", "5", None, "normalize.invalid_enum:end_type"),
        ("20230831", "0", "20260929", "normalize.invalid_date:list_date"),
    ),
)
def test_other_cases_still_rejected(key, fields, model, end_date, end_type, listing_date, reason):
    batch, _ = _normalize(key, [_row(fields, end_date=end_date, end_type=end_type)], {"920202.BJ": listing_date})
    assert batch.rows_normalized == []
    assert batch.rejected_reasons == {reason: 1}


@pytest.mark.parametrize("key,fields,model", CASES)
@pytest.mark.parametrize(
    "overrides,reason",
    (
        ({"end_date": "20230230"}, "normalize.invalid_date:end_date"),
        ({"ts_code": ""}, "normalize.empty_not_allowed:ts_code"),
        ({"f_ann_date": None}, "normalize.empty_not_allowed:f_ann_date"),
        ({"report_type": "13"}, "normalize.invalid_enum:report_type"),
        ({"comp_type": ""}, "normalize.empty_not_allowed:comp_type"),
        ({"update_flag": "2"}, "normalize.invalid_enum:update_flag"),
    ),
)
def test_exemption_does_not_skip_other_fields(key, fields, model, overrides, reason):
    batch, _ = _normalize(key, [_row(fields, **overrides)], {})
    assert batch.rows_normalized == []
    assert batch.rejected_reasons == {reason: 1}


@pytest.mark.parametrize("key,fields,model", CASES)
def test_exemption_keeps_unit_date_and_conflict_checks(key, fields, model):
    with pytest.raises(IngestionNormalizeError) as error:
        _normalize(key, [_row(fields, ann_date="20240112")], {})
    assert error.value.structured_error.error_code == "normalize.unit_date_mismatch"
    numeric_field = get_dataset_definition(key).normalization.decimal_fields[0]
    with pytest.raises(IngestionNormalizeError) as error:
        _normalize(key, [_row(fields), _row(fields, **{numeric_field: "1"})], {})
    assert error.value.structured_error.error_code == "normalize.batch_unique_key_conflicting"
    deduped, _ = _normalize(key, [_row(fields), _row(fields)], {})
    assert len(deduped.rows_normalized) == 1
    assert deduped.rows_deduplicated == 1


def test_candidate_codes_are_cleaned_deduplicated_and_not_cached_between_units():
    rows = [
        _row(BALANCESHEET_SOURCE_FIELDS, ts_code="\x00 920202.bj ", end_type=0),
        _row(BALANCESHEET_SOURCE_FIELDS),
        _row(BALANCESHEET_SOURCE_FIELDS, ts_code="600000.SH", end_date="20230630", end_type="2"),
    ]
    loader = Mock(side_effect=[{"920202.BJ": LIST_DATE}, {"920202.BJ": date(2020, 1, 1)}])
    normalizer = DatasetNormalizer(listing_dates_loader=loader)
    first = normalizer.normalize(definition=get_dataset_definition("balancesheet"), fetch_result=_fetch(rows), expected_unit_date=ANN_DATE)
    assert first.rows_rejected == 0
    second = normalizer.normalize(definition=get_dataset_definition("balancesheet"), fetch_result=_fetch(rows[:1]), expected_unit_date=ANN_DATE)
    assert second.rejected_reasons == {"normalize.financial_statement_end_date_invalid": 1}
    assert loader.call_count == 2
    assert all(call.args == (["920202.BJ"],) for call in loader.call_args_list)


def test_valid_quarter_needs_no_listing_query_and_zero_has_stable_source_hash():
    row = _row(BALANCESHEET_SOURCE_FIELDS, end_date="20230630", end_type=None)
    batch, loader = _normalize("balancesheet", [row], {})
    assert batch.rows_normalized[0]["end_type"] == "2"
    loader.assert_not_called()
    first, _ = _normalize("balancesheet", [FIXTURE["row"]], {"920202.BJ": LIST_DATE})
    second, _ = _normalize("balancesheet", [FIXTURE["row"]], {})
    assert first.rows_normalized == second.rows_normalized


def test_listing_lookup_is_not_used_for_other_datasets():
    loader = Mock(side_effect=AssertionError("unrelated dataset queried listing dates"))
    batch = DatasetNormalizer(listing_dates_loader=loader).normalize(
        definition=get_dataset_definition("trade_cal"),
        fetch_result=_fetch([{"exchange": "SSE", "cal_date": "20240111", "is_open": "1", "pretrade_date": "20240110", "end_type": "0"}]),
        expected_unit_date=ANN_DATE,
    )
    assert batch.rows_rejected == 0
    loader.assert_not_called()


@pytest.fixture
def isolated_session():
    engine = create_engine("sqlite://", execution_options={"schema_translate_map": {"core_serving": None, "raw_tushare": None}})
    @event.listens_for(engine, "connect")
    def sqlite_now(connection, _record):
        connection.create_function("now", 0, lambda: datetime.now().isoformat(" "))
    Security.__table__.create(engine)
    for _, _, model in CASES:
        model.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_listing_dao_reads_only_requested_columns_codes_and_includes_delisted(isolated_session):
    session = isolated_session
    session.add_all([
        Security(ts_code="920202.BJ", name="安达股份", list_date=LIST_DATE, list_status="L"),
        Security(ts_code="000583.SZ", name="已退市样本", list_date=date(1995, 1, 1), list_status="D"),
        Security(ts_code="600000.SH", name="空日期样本", list_date=None),
        Security(ts_code="not-requested", name="不得读取", list_date=LIST_DATE),
    ])
    session.commit()
    execute = Mock(wraps=session.execute)
    session.execute = execute
    dao = SecurityDAO(session)
    assert dao.get_listing_dates([]) == {}
    execute.assert_not_called()
    dates = dao.get_listing_dates(["920202.BJ", "000583.SZ", "600000.SH", "missing", "920202.BJ"])
    assert dates == {"920202.BJ": LIST_DATE, "000583.SZ": date(1995, 1, 1), "600000.SH": None}
    statement = execute.call_args.args[0]
    assert list(statement.selected_columns.keys()) == ["ts_code", "list_date"]
    assert set(next(iter(statement.compile().params.values()))) == {"920202.BJ", "000583.SZ", "600000.SH", "missing"}
    assert "list_status" not in str(statement)


@pytest.mark.parametrize("count,expected_queries", ((500, 1), (501, 2)))
def test_listing_dao_bounds_query_batches(isolated_session, count, expected_queries):
    execute = Mock(wraps=isolated_session.execute)
    isolated_session.execute = execute
    assert SecurityDAO(isolated_session).get_listing_dates([f"{number:06}.SZ" for number in range(count)]) == {}
    assert execute.call_count == expected_queries
    assert all(len(next(iter(call.args[0].compile().params.values()))) <= 500 for call in execute.call_args_list)


@pytest.mark.parametrize("key,fields,model", CASES)
@pytest.mark.parametrize("listing_state", ("known", "null", "missing"))
def test_executor_uses_listing_dao_then_real_writer_and_idempotent_readback(isolated_session, key, fields, model, listing_state):
    session = isolated_session
    if listing_state != "missing":
        session.add(Security(ts_code="920202.BJ", name="安达股份", list_date=LIST_DATE if listing_state == "known" else None))
        session.commit()
    row = FIXTURE["row"] if key == "balancesheet" else _row(fields)
    if key == "balancesheet":
        assert len(row) == 158
        assert row["end_date"] == "20230831" and row["end_type"] == "0"
        assert FIXTURE["stock_basic"]["list_date"] == "20260929"
    executor = IngestionExecutor(session)
    executor.source_client = Mock()
    executor.source_client.fetch.return_value = _fetch([row])
    request, unit = _request_and_unit(key)
    for _ in range(2):
        summary = executor.run(request=request, definition=get_dataset_definition(key), units=(unit,))
        assert (summary.rows_fetched, summary.rows_written, summary.rows_committed, summary.rows_rejected) == (1, 1, 1, 0)
        assert (summary.unit_done, summary.unit_failed) == (1, 0)
    saved = session.scalars(select(model)).one()
    assert saved.end_date == date(2023, 8, 31) and saved.end_type == "0"
    assert saved.ts_code == "920202.BJ"
    assert session.scalar(select(func.count()).select_from(model)) == 1


def test_listing_database_error_is_not_treated_as_unknown_date(isolated_session):
    executor = IngestionExecutor(isolated_session)
    executor.normalizer._listing_dates_loader = Mock(side_effect=RuntimeError("database offline"))
    executor.source_client = Mock()
    executor.source_client.fetch.return_value = _fetch([FIXTURE["row"]])
    executor.writer = Mock()
    request, unit = _request_and_unit("balancesheet")
    # The existing executor rolls back and re-raises IngestionError (executor.py).
    with pytest.raises(IngestionNormalizeError) as error:
        executor.run(request=request, definition=get_dataset_definition("balancesheet"), units=(unit,))
    assert error.value.structured_error.error_code == "normalize.financial_statement_listing_dates_failed"
    assert error.value.structured_error.retryable is True
    executor.writer.write.assert_not_called()
    assert isolated_session.scalar(select(func.count()).select_from(RawBalancesheet)) == 0


@pytest.mark.parametrize("key,fields,model", CASES)
def test_executor_reads_known_listing_date_and_blocks_postlisting_zero(isolated_session, key, fields, model):
    # This must fail if the executor forgets to inject its DAO into the normalizer.
    isolated_session.add(Security(ts_code="920202.BJ", name="边界测试", list_date=date(2020, 1, 1)))
    isolated_session.commit()
    executor = IngestionExecutor(isolated_session)
    executor.source_client = Mock()
    executor.source_client.fetch.return_value = _fetch([_row(fields)])
    executor.writer = Mock(wraps=executor.writer)
    request, unit = _request_and_unit(key)
    with pytest.raises(IngestionNormalizeError) as error:
        executor.run(request=request, definition=get_dataset_definition(key), units=(unit,))
    assert error.value.structured_error.error_code == "all_rows_rejected"
    assert error.value.structured_error.details["rejected_reasons"] == {"normalize.financial_statement_end_date_invalid": 1}
    executor.writer.write.assert_not_called()
    assert isolated_session.scalar(select(func.count()).select_from(model)) == 0


def test_mixed_rejected_batch_still_blocks_entire_write(isolated_session):
    rows = [FIXTURE["row"], _row(BALANCESHEET_SOURCE_FIELDS, ts_code="600000.SH", end_date="20230831", end_type="3")]
    batch, _ = _normalize("balancesheet", rows, {})
    assert len(batch.rows_normalized) == 1 and batch.rows_rejected == 1
    with pytest.raises(IngestionWriteError) as error:
        DatasetWriter(isolated_session).write(definition=get_dataset_definition("balancesheet"), batch=batch)
    assert error.value.structured_error.error_code == "write.unit_rows_rejected"
    assert isolated_session.scalar(select(func.count()).select_from(RawBalancesheet)) == 0
