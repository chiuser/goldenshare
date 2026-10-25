"""TaskRun dates only: no minute source, Lake, or Dagster instance access.

Independent literal evidence: reports/datasets_recovery_20261022_20261024/
resume_20261025/prod-stock-task-evidence.txt, Prod TaskRun 16729. Fake cursors
capture queries, not PostgreSQL predicate execution; that is verified separately.
"""
from __future__ import annotations

import json
from collections import namedtuple
from contextlib import contextmanager
from copy import deepcopy
from datetime import date

import pytest

from orchestrator.defs.bootstrap import stk_mins_raw_replace_from_prod as recovery
from orchestrator.defs.prod_db import stk_mins_task_run as task_runs

TARGET = "2026-10-22"
FREQS = ["1min", "5min", "15min", "30min", "60min"]
_Column = namedtuple("_Column", "name")


def completed_range_row(**overrides):
    """Literal successful task evidence; counts describe two days, not one."""
    row = {
        "id": 16729, "task_type": "dataset_action", "resource_key": "stk_mins",
        "action": "maintain", "status": "success", "status_reason_code": None,
        "ended_at": "2026-10-25T01:16:41.811462+08:00",
        "unit_total": 29605, "unit_done": 29605, "unit_failed": 0,
        "progress_percent": 100, "rows_fetched": 3594514,
        "rows_saved": 3594514, "rows_rejected": 0,
        "time_input_json": {"mode": "range", "start_date": TARGET, "end_date": "2026-10-23"},
        "filters_json": {"freq": list(FREQS)},
    }
    row.update(deepcopy(overrides))
    return row


def parsed(time_input, *, target=TARGET):
    return task_runs.full_market_stk_mins_task_run_from_row(
        completed_range_row(time_input_json=time_input), trade_date=target)


@pytest.mark.parametrize("target,accepted", [("2026-10-21", False), (TARGET, True),
                                              ("2026-10-23", True), ("2026-10-24", False)])
def test_real_range_shape_covers_only_inclusive_dates(target, accepted):
    result = task_runs.full_market_stk_mins_task_run_from_row(completed_range_row(), trade_date=target)
    assert (result is not None) is accepted
    if result is not None:
        assert result.task_run_id == 16729 and result.trade_date == target
        assert result.ended_at == "2026-10-25T01:16:41.811462+08:00"
        assert result.rows_saved == 3594514


@pytest.mark.parametrize("mode_fields", [{}, {"mode": "point"}])
def test_existing_explicit_day_with_or_without_mode_remains_valid(mode_fields):
    assert parsed({**mode_fields, "trade_date": TARGET}) is not None
    assert parsed({**mode_fields, "trade_date": "2026-10-21"}) is None


@pytest.mark.parametrize("empty", [None, ""])
def test_irrelevant_dates_accept_only_documented_empty_values(empty):
    assert parsed({"mode": "point", "trade_date": TARGET,
                   "start_date": empty, "end_date": empty}) is not None
    assert parsed({"mode": "range", "trade_date": empty,
                   "start_date": TARGET, "end_date": TARGET}) is not None


@pytest.mark.parametrize("bad_empty", [" ", [], [None], 0, False, {}])
@pytest.mark.parametrize("field", ["start_date", "end_date", "trade_date"])
def test_irrelevant_dates_do_not_coerce_other_values_to_empty(field, bad_empty):
    value = ({"mode": "range", "start_date": TARGET, "end_date": TARGET}
             if field == "trade_date" else {"mode": "point", "trade_date": TARGET})
    value[field] = bad_empty
    assert parsed(value) is None


@pytest.mark.parametrize("mode", [None, "", " ", "unknown", "POINT", 0, False, [], {}])
def test_explicit_null_empty_or_unknown_mode_is_rejected(mode):
    assert parsed({"mode": mode, "trade_date": TARGET}) is None


@pytest.mark.parametrize("value", [
    {"start_date": TARGET, "end_date": "2026-10-23"},
    {"mode": "range", "start_date": TARGET},
    {"mode": "range", "end_date": "2026-10-23"},
    {"mode": "range", "start_date": "2026-10-23", "end_date": TARGET},
    {"mode": "range", "trade_date": TARGET, "start_date": TARGET, "end_date": "2026-10-23"},
    {"mode": "point", "trade_date": TARGET, "start_date": TARGET},
    {"mode": "point", "trade_date": TARGET, "end_date": TARGET},
    {"mode": "range", "trade_date": TARGET}, {"mode": "point"}, {}, [], None, "not-json",
])
def test_missing_reversed_mixed_or_unrecognizable_scope_is_rejected(value):
    assert parsed(value) is None


@pytest.mark.parametrize("bad_date", [
    "2026-02-30", "2026-13-01", "2026-00-10", "0000-01-01", "2026-2-22", "20261022",
    " 2026-10-22", "2026-10-22 ", "2026-10-22T00:00:00", None, "", 20261022, [], {},
])
@pytest.mark.parametrize("field", ["start_date", "end_date"])
def test_range_requires_canonical_real_date_boundaries(field, bad_date):
    value = {"mode": "range", "start_date": TARGET, "end_date": "2026-10-23"}
    value[field] = bad_date
    assert parsed(value) is None


@pytest.mark.parametrize("overrides", [
    {"task_type": "workflow"}, {"resource_key": "index_mins"}, {"action": "refresh"},
    {"status": "queued"}, {"status": "running"}, {"status": "canceling"},
    {"status": "failed"}, {"status": "canceled"}, {"status": "partial_success"},
    {"ended_at": None}, {"unit_total": 0, "unit_done": 0}, {"unit_done": 29604},
    {"unit_failed": 1}, {"progress_percent": 99}, {"rows_fetched": 0},
    {"rows_saved": 0}, {"rows_rejected": 1}, {"filters_json": {"freq": ["1min"]}},
    {"filters_json": {"freq": FREQS[:-1]}}, {"filters_json": {"freq": [1, 5, 15, 30, 60]}},
    {"filters_json": {"freq": list(FREQS), "ts_code": "600000.SH"}},
    {"filters_json": {"freq": list(FREQS), "ts_code": ["600000.SH"]}},
    {"filters_json": {}}, {"id": None},
])
def test_range_retains_every_existing_success_and_full_market_requirement(overrides):
    assert task_runs.full_market_stk_mins_task_run_from_row(
        completed_range_row(**overrides), trade_date=TARGET) is None


class FakeCursor:
    def __init__(self, rows):
        columns = task_runs.PROD_STK_MINS_TASK_RUN_COLUMNS
        self.description = tuple(_Column(column) for column in columns)
        self.rows = [tuple(row[column] for column in columns) for row in rows]
        self.sql, self.params = "", ()

    def execute(self, sql, params):
        self.sql, self.params = sql, tuple(params)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeProd:
    def __init__(self, rows):
        self.result_cursor = FakeCursor(rows)
        self.readonly_calls = 0

    def cursor(self):
        return self.result_cursor

    @contextmanager
    def connect_readonly_transaction(self):
        self.readonly_calls += 1
        yield self


@pytest.mark.parametrize("target,accepted", [(TARGET, True), ("2026-10-23", True),
                                              ("2026-10-21", False), ("2026-10-24", False)])
@pytest.mark.parametrize("entry", ["shared", "by_id", "offline"])
def test_shared_by_id_and_offline_use_same_target_day_judgment(target, accepted, entry):
    prod = FakeProd([completed_range_row()])
    if entry == "shared":
        result = task_runs.probe_full_market_stk_mins_task_run(prod_postgres=prod, trade_date=target)
        assert result.ready is accepted
        selected = result.task_run
    elif entry == "by_id":
        result = task_runs.probe_full_market_stk_mins_task_run_by_id(
            prod_postgres=prod, task_run_id=16729, trade_date=target)
        assert result.ready is accepted
        assert prod.result_cursor.params == (16729,)
        selected = result.task_run
    else:
        source = recovery.ProdStkMinsRawReplaceSource(duckdb=object(), prod_postgres=prod)
        selected = source.select_full_market_task_run(trade_date=target)
    assert (selected is not None) is accepted
    if selected is not None:
        assert selected.task_run_id == 16729
    assert prod.readonly_calls == 1


def test_fixed_sql_builder_binds_dates_instead_of_interpolating_them():
    sql, params = task_runs.build_stk_mins_task_run_date_filter(trade_date=TARGET)
    other_sql, other_params = task_runs.build_stk_mins_task_run_date_filter(trade_date="2026-10-23")
    assert sql == other_sql and TARGET not in sql and "2026-10-23" not in sql
    assert params == (TARGET, TARGET, TARGET)
    assert other_params == ("2026-10-23",) * 3


@pytest.mark.parametrize("entry", ["shared", "offline"])
def test_both_candidate_queries_share_filter_before_order_and_limit(monkeypatch, entry):
    builder = task_runs.build_stk_mins_task_run_date_filter
    date_sql, date_params = builder(trade_date=TARGET)
    calls = []

    def capture(*, trade_date):
        calls.append(trade_date)
        return builder(trade_date=trade_date)

    monkeypatch.setattr(task_runs, "build_stk_mins_task_run_date_filter", capture)
    monkeypatch.setattr(recovery, "build_stk_mins_task_run_date_filter", capture)
    prod = FakeProd([completed_range_row()])
    if entry == "shared":
        assert task_runs.probe_full_market_stk_mins_task_run(prod_postgres=prod, trade_date=TARGET).ready
    else:
        source = recovery.ProdStkMinsRawReplaceSource(duckdb=object(), prod_postgres=prod)
        assert source.select_full_market_task_run(trade_date=TARGET) is not None
    sql = " ".join(prod.result_cursor.sql.lower().split())
    predicate = " ".join(date_sql.lower().split())
    assert calls == [TARGET]
    assert sql.index("where") < sql.index(predicate) < sql.index("order by") < sql.index("limit")
    assert "from ops.task_run" in sql and "select *" not in sql
    assert "raw_tushare" not in sql and "ops.task_run_node" not in sql
    assert "ops.schedule" not in sql and "ops.task_run_issue" not in sql
    assert prod.result_cursor.params == (*date_params, 20)


@pytest.mark.parametrize("invalid_target", [
    "20261022", "2026-W43-4", "2026W434", "2026-2-22",
    " 2026-10-22", "2026-10-22 ", "2026-10-22\n", "\n2026-10-22", "\n",
    "2026-02-30", "", None, 20261022, False, [], {}, date(2026, 10, 22),
])
def test_noncanonical_or_nonstring_target_is_rejected_before_query(invalid_target):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        task_runs.build_stk_mins_task_run_date_filter(trade_date=invalid_target)
    assert task_runs.full_market_stk_mins_task_run_from_row(
        completed_range_row(), trade_date=invalid_target) is None


@pytest.mark.parametrize("time_input", [
    {"mode": "range", "start_date": TARGET, "end_date": "2026-10-23"},
    {"mode": "point", "trade_date": TARGET},
    {"trade_date": TARGET},
])
def test_valid_json_text_matches_mapping_for_range_point_and_legacy_point(time_input):
    mapping_result = parsed(time_input)
    text_result = parsed(json.dumps(time_input))
    assert mapping_result is not None
    assert text_result == mapping_result
    assert text_result.task_run_id == 16729 and text_result.trade_date == TARGET


@pytest.mark.parametrize("time_input", [
    "not-json", "{", "null", "[]", '[{"trade_date":"2026-10-22"}]',
    "true", "42", '"2026-10-22"', [], [{"trade_date": TARGET}],
])
def test_invalid_json_text_or_nonmapping_json_is_rejected(time_input):
    assert parsed(time_input) is None
