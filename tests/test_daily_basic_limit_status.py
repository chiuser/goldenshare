"""Stage-two contracts. The complete source row was verified by MCP on 2026-11-12.

000001.SZ / 20261110 returned exactly these 19 business fields; variants below
are deliberate synthetic validation cases, not additional source observations.
Network and persistence are replaced only in the executor unit tests.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest
import requests

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.errors import (
    IngestionError,
    IngestionNormalizeError,
    StructuredError,
)
from src.foundation.ingestion.execution_plan import (
    PlanUnitSnapshot,
    ValidatedDatasetActionRequest,
)
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.source_client import (
    DatasetSourceClient,
    SourceFetchResult,
)
from src.foundation.ingestion.writer import WriteResult

SOURCE_ROW = {
    "ts_code": "000001.SZ", "trade_date": "20261110", "close": 11.86,
    "turnover_rate": 0.3859, "turnover_rate_f": 0.9177, "volume_ratio": 0.49,
    "pe": 5.3985, "pe_ttm": 5.2933, "pb": 0.4828, "ps": 1.751,
    "ps_ttm": 1.7192, "dv_ratio": 5.0423, "dv_ttm": 5.1349,
    "total_share": 1940591.8198, "float_share": 1940568.4991,
    "free_share": 816056.5553, "total_mv": 23015418.9852,
    "circ_mv": 23015142.41, "limit_status": 4,
}
SOURCE_FIELDS = tuple(SOURCE_ROW)
DAY = date(2026, 11, 10)
ERROR_CODE = "normalize.source_validation_failed"


def unit(day=DAY, dataset_key="daily_basic"):
    return PlanUnitSnapshot(
        unit_id=f"{dataset_key}:{day.isoformat()}", dataset_key=dataset_key,
        source_key="tushare", trade_date=day, request_params={"trade_date": day.strftime("%Y%m%d")},
        progress_context={"trade_date": day.isoformat()},
    )


def request(dataset_key="daily_basic"):
    return ValidatedDatasetActionRequest(
        request_id="daily-basic-stage2", dataset_key=dataset_key, action="maintain",
        run_profile="range_backfill", trigger_source="test", params={}, source_key="tushare",
        trade_date=None, start_date=DAY, end_date=date(2026, 11, 12), run_id=123,
    )


def normalize(rows, definition=None):
    return DatasetNormalizer().normalize(
        definition=definition or get_dataset_definition("daily_basic"),
        fetch_result=SourceFetchResult(unit_id="sample", rows_raw=rows, request_count=1, retry_count=0, latency_ms=0),
        expected_unit_date=DAY,
    )


class Source:
    def __init__(self, rows_by_day):
        self.rows_by_day = rows_by_day
        self.called = []

    def fetch(self, *, definition, unit):
        self.called.append(unit.trade_date)
        return SourceFetchResult(
            unit_id=unit.unit_id, rows_raw=self.rows_by_day[unit.trade_date],
            request_count=1, retry_count=0, latency_ms=0,
        )


def make_executor(rows_by_day):
    session = Mock()
    executor = IngestionExecutor(session)
    executor.source_client = Source(rows_by_day)
    writer = Mock()
    writer.write.side_effect = lambda **kw: WriteResult(
        unit_id=kw["batch"].unit_id, rows_written=len(kw["batch"].rows_normalized),
        rows_upserted=len(kw["batch"].rows_normalized), rows_skipped=0,
        target_table=kw["definition"].storage.target_table, conflict_strategy="upsert",
    )
    executor.writer = writer
    return executor, session, writer


def test_definition_preserves_time_storage_and_decimal_contracts():
    definition = get_dataset_definition("daily_basic")
    assert definition.source.source_fields == SOURCE_FIELDS
    assert definition.normalization.row_transform_name == "daily_basic_limit_status"
    assert definition.quality.reject_policy == "fail_unit_on_any_rejection"
    assert definition.normalization.decimal_fields == SOURCE_FIELDS[2:-1]
    assert definition.normalization.date_fields == ("trade_date",)
    assert definition.normalization.required_fields == ("trade_date", "ts_code")
    assert definition.storage.write_path == "raw_core_upsert"
    assert definition.transaction.commit_policy == "unit"
    assert definition.date_model.input_shape == "trade_date_or_start_end"
    assert definition.date_model.observed_field == "trade_date"
    assert definition.planning.page_limit == 6000
    assert tuple(field.name for field in definition.input_model.filters) == ("ts_code",)


@pytest.mark.parametrize("status", range(7))
def test_native_status_and_old_nullable_negative_values_are_preserved(status):
    result = normalize([{**SOURCE_ROW, "limit_status": status, "pe": -2.5, "pb": None}])
    assert result.rows_rejected == 0
    row = result.rows_normalized[0]
    assert type(row["limit_status"]) is int and row["limit_status"] == status
    assert row["pe"] == Decimal("-2.5") and row["pb"] is None
    assert row["trade_date"] == DAY and row["close"] == Decimal("11.86")


@pytest.mark.parametrize("status", [None, True, False, "1", "1" * 300, 1.0, 1.5, Decimal(1), -1, 7])
def test_invalid_status_is_not_coerced_or_defaulted(status):
    result = normalize([{**SOURCE_ROW, "limit_status": status}])
    assert result.rows_normalized == [] and result.rows_rejected == 1
    reason = "normalize.daily_basic_limit_status_invalid:limit_status"
    assert result.rejected_reasons == {reason: 1}
    sample = result.rejected_samples[reason][0]
    assert sample["row"]["ts_code"] == "000001.SZ"
    assert type(status).__name__ in sample["message"]
    assert "0～6" in sample["message"]


@pytest.mark.parametrize("missing", SOURCE_FIELDS)
def test_every_business_field_must_be_present_but_can_keep_its_existing_null_rule(missing):
    row = dict(SOURCE_ROW)
    del row[missing]
    result = normalize([row])
    assert result.rows_normalized == [] and result.rows_rejected == 1
    assert result.rejected_reasons == {f"normalize.required_field_missing:{missing}": 1}


def test_rejection_samples_are_bounded_while_counts_include_all_bad_rows():
    result = normalize([{**SOURCE_ROW, "limit_status": 1.5}] * 5)
    reason = "normalize.daily_basic_limit_status_invalid:limit_status"
    assert result.rows_rejected == 5 and result.rejected_reasons[reason] == 5
    assert len(result.rejected_samples[reason]) == 3


def test_each_source_page_receives_the_full_field_contract(monkeypatch):
    from src.foundation.ingestion import source_client as module

    connector = Mock()
    connector.call.side_effect = [[SOURCE_ROW], []]
    monkeypatch.setattr(module, "create_source_connector", lambda _: connector)
    result = DatasetSourceClient().fetch(
        definition=get_dataset_definition("daily_basic"),
        unit=replace(unit(), page_limit=1, pagination_policy="offset_limit"),
    )
    assert len(result.rows_raw) == 1 and result.request_count == 2
    assert [call.kwargs["params"]["offset"] for call in connector.call.call_args_list] == [0, 1]
    assert all(tuple(call.kwargs["fields"]) == SOURCE_FIELDS for call in connector.call.call_args_list)


def test_bad_row_stops_whole_date_and_preserves_only_previous_commits():
    next_day, last_day = date(2026, 11, 11), date(2026, 11, 12)
    rows = {DAY: [SOURCE_ROW], next_day: [
        {**SOURCE_ROW, "trade_date": "20261111", "ts_code": "000002.SZ"},
        {**SOURCE_ROW, "trade_date": "20261111", "limit_status": 1.5},
    ], last_day: [SOURCE_ROW]}
    executor, session, writer = make_executor(rows)
    with pytest.raises(IngestionNormalizeError) as caught:
        executor.run(request=request(), definition=get_dataset_definition("daily_basic"),
                     units=tuple(unit(day) for day in rows))
    error = caught.value.structured_error
    assert error.error_code == ERROR_CODE
    assert error.details["trade_date"] == "2026-11-11"
    assert error.details["rows_fetched"] == 2 and error.details["rows_rejected"] == 1
    progress = error.details["committed_progress"]
    assert (progress["unit_done"], progress["unit_total"], progress["rows_fetched"], progress["rows_committed"], progress["rows_rejected"]) == (1, 3, 1, 1, 0)
    assert writer.write.call_count == session.commit.call_count == session.rollback.call_count == 1
    assert executor.source_client.called == [DAY, next_day]


@pytest.mark.parametrize("kind", ["date", "duplicate"])
def test_existing_configured_batch_validation_errors_keep_their_original_cause(kind):
    definition = get_dataset_definition("daily_basic")
    if kind == "date":
        definition = replace(definition, quality=replace(definition.quality, unit_date_field="trade_date"))
        rows = [{**SOURCE_ROW, "trade_date": "20261111"}]
        original_code = "normalize.unit_date_mismatch"
    else:
        definition = replace(definition, quality=replace(definition.quality, batch_unique_key_fields=("ts_code", "trade_date")))
        rows = [SOURCE_ROW, dict(SOURCE_ROW)]
        original_code = "normalize.batch_unique_key_duplicate"
    executor, session, writer = make_executor({DAY: rows})
    with pytest.raises(IngestionNormalizeError) as caught:
        executor.run(request=request(), definition=definition, units=(unit(),))
    assert caught.value.structured_error.error_code == ERROR_CODE
    assert caught.value.structured_error.details["original_error"]["error_code"] == original_code
    assert isinstance(caught.value.__cause__, IngestionNormalizeError)
    assert caught.value.structured_error.details["committed_progress"]["rows_committed"] == 0
    writer.write.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.parametrize("failure", [RuntimeError("program bug"), IngestionNormalizeError(
    StructuredError(error_code="normalize.row_transform_failed", error_type="normalize", phase="normalizer",
                    message="unknown transform", retryable=False))])
def test_program_errors_are_not_relabelled_as_bad_source_values(failure):
    executor, _, writer = make_executor({DAY: [SOURCE_ROW]})
    executor.normalizer.normalize = Mock(side_effect=failure)
    with pytest.raises(IngestionError) as caught:
        executor.run(request=request(), definition=get_dataset_definition("daily_basic"), units=(unit(),))
    assert caught.value.structured_error.error_code != ERROR_CODE
    writer.write.assert_not_called()


def test_unexpected_row_transform_failure_uses_the_existing_program_error_code(monkeypatch):
    from src.foundation.ingestion import normalizer as module

    def broken_transform(row):
        raise RuntimeError("deliberate transform programming error")

    monkeypatch.setattr(module, "daily_basic_limit_status", broken_transform)
    executor, _, writer = make_executor({DAY: [SOURCE_ROW]})
    with pytest.raises(IngestionNormalizeError) as caught:
        executor.run(request=request(), definition=get_dataset_definition("daily_basic"), units=(unit(),))
    assert caught.value.structured_error.error_code == "normalize.row_transform_failed"
    assert "行转换执行失败" in caught.value.structured_error.message
    writer.write.assert_not_called()


def test_source_connection_error_is_not_reported_as_an_invalid_status():
    executor, _, writer = make_executor({DAY: [SOURCE_ROW]})
    executor.source_client.fetch = Mock(side_effect=requests.ConnectionError("deliberate source connection error"))
    with pytest.raises(IngestionError) as caught:
        executor.run(request=request(), definition=get_dataset_definition("daily_basic"), units=(unit(),))
    assert caught.value.structured_error.error_code != ERROR_CODE
    writer.write.assert_not_called()


def test_other_dataset_partial_rejection_keeps_the_existing_write_behavior():
    rows = [{"ts_code": "000001.SZ", "trade_date": "20261110", "pre_close": 10, "up_limit": 11, "down_limit": 9},
            {"ts_code": "000002.SZ", "trade_date": "bad-date", "pre_close": 10, "up_limit": 11, "down_limit": 9}]
    executor, session, writer = make_executor({DAY: rows})
    summary = executor.run(request=request("stk_limit"), definition=get_dataset_definition("stk_limit"),
                           units=(unit(dataset_key="stk_limit"),))
    assert summary.rows_committed == 1 and summary.rows_rejected == 1
    assert writer.write.call_count == session.commit.call_count == 1
    session.rollback.assert_not_called()
