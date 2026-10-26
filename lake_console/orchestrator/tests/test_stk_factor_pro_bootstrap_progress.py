"""LLD 17.8.5: real temporary bootstrap, synchronous standard log records.

Only Prod transport, configured paths, connection ownership and logging failures
are replaced. The 261-column carrier comes from the doc328-based native fixture;
source persistence, two-layer publication and coverage records are real.
"""

import logging
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from threading import get_ident
from types import SimpleNamespace

import pytest

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_publication as P
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as R
from orchestrator.defs.bootstrap import stk_factor_pro_history as B
from orchestrator.defs.checks.stk_factor_pro import factor_file_sha
from orchestrator.defs.run_contracts import stk_factor_pro as C
from tests.stk_factor_pro_bootstrap_test_support import approval_fixture, native_row
from tests.stk_factor_pro_test_support import connection
from tests.test_stk_factor_pro_bootstrap import Instance, NoProd
from tests.test_stk_factor_pro_bootstrap_coverage import upstream
from tests.test_stk_factor_pro_bootstrap_source import FakeProd

DAY = date(2019, 10, 16)
FIELDS = {
    "operation_id",
    "attempt_id",
    "month",
    "stage",
    "event",
    "batch_no",
    "batch_rows",
    "saved_rows",
    "completed_dates",
    "total_dates",
    "trade_date",
    "raw_rows",
    "silver_rows",
    "coverage_state",
    "reused_source_rows",
    "elapsed_seconds",
    "updated_at",
    "outcome",
}


class SelectedDateProd(FakeProd):
    """Apply the actual fixed SQL date predicate, including multiple months."""

    def cursor(self, name=None, **keywords):
        cursor = super().cursor(name=name, **keywords)
        execute = cursor.execute

        def selected(query, parameters=None):
            execute(query, parameters)
            if cursor.named:
                start, stop, dates, limit = parameters
                cursor.result = [
                    row
                    for row in self.rows
                    if start <= row[1] < stop and row[1] in dates
                ][:limit]
                cursor.position = 0

        cursor.execute = selected
        return cursor


def _setup(tmp_path, monkeypatch, *, counts=((DAY, 1),), rows=None, market=None):
    with connection(tmp_path) as conn:
        lake, staging, approval, identity = approval_fixture(
            conn, tmp_path, counts=counts
        )
        if market is not None:
            upstream(conn, lake, days=tuple(d for d, _ in counts), **market)
    monkeypatch.setattr(B, "DEFAULT_LAKE_ROOT", str(lake))
    monkeypatch.setattr(B, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    state = SimpleNamespace(closed=[], close_error=None)

    @contextmanager
    def owned_connection():
        try:
            with connection(tmp_path) as conn:
                yield conn
        finally:
            state.closed.append("duckdb_closed")
            if state.close_error is not None:
                raise state.close_error

    monkeypatch.setattr(B, "connect_configured_duckdb", owned_connection)
    resource = SimpleNamespace(
        ensure_available_for_run=lambda: None,
        root=lambda: lake,
    )
    remote = SelectedDateProd(
        approval,
        identity,
        counts,
        [native_row()] if rows is None else rows,
        sample_rows=[native_row(day=counts[0][0])],
    )
    return (
        {
            "operation_id": approval.operation_id,
            "instance": Instance(),
            "prod_postgres": remote,
            "lake_root": resource,
        },
        state,
        lake,
        staging,
        approval,
    )


def _events(caplog):
    return [
        record.stk_factor_pro_bootstrap
        for record in caplog.records
        if hasattr(record, "stk_factor_pro_bootstrap")
    ]


def _data(lake, day, layer):
    parts = (
        ("raw", "tushare", "stk_factor_pro")
        if layer == "raw"
        else ("silver", "stock_factor_pro")
    )
    return lake.joinpath(*parts, f"trade_date={day}", "data.parquet")


def test_standard_sequence_and_fields_after_owned_connection_closed(
    tmp_path, monkeypatch, caplog
):
    following = DAY + timedelta(days=1)
    counts = ((DAY, 1), (following, 2))
    rows = [
        native_row(),
        native_row("000001.SZ", following),
        native_row("000002.SZ", following),
    ]
    args, state, _, _, _ = _setup(tmp_path, monkeypatch, counts=counts, rows=rows)
    monkeypatch.setattr(C, "STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS", 1)
    caplog.set_level(logging.INFO, logger=B._LOGGER.name)
    finish_states = []
    original = B._LOGGER.info

    def observe(*values, **keywords):
        if (
            keywords["extra"]["stk_factor_pro_bootstrap"]["event"]
            == "operation_finished"
        ):
            finish_states.append(tuple(state.closed))
        return original(*values, **keywords)

    monkeypatch.setattr(B._LOGGER, "info", observe)
    result = B.bootstrap_stk_factor_pro_history(**args)
    events = _events(caplog)
    assert [event["event"] for event in events] == [
        "month_started",
        "batch_saved",
        "batch_saved",
        "date_completed",
        "batch_saved",
        "date_completed",
        "operation_finished",
    ]
    assert finish_states == [("duckdb_closed",)]
    assert result.current_raw_rows == result.current_silver_rows == 3
    assert all(FIELDS <= event.keys() for event in events)
    assert all(
        event["operation_id"] == "bootstrap-a" and event["total_dates"] == 2
        for event in events
    )
    assert all(
        datetime.fromisoformat(event["updated_at"]).utcoffset() == timedelta(hours=8)
        for event in events
    )
    assert all(
        record.thread == get_ident()
        for record in caplog.records
        if hasattr(record, "stk_factor_pro_bootstrap")
    )
    assert [event["elapsed_seconds"] for event in events] == sorted(
        event["elapsed_seconds"] for event in events
    )
    batches = [event for event in events if event["event"] == "batch_saved"]
    assert [event["saved_rows"] for event in batches] == [1, 2, 3]
    assert [event["batch_rows"] for event in batches] == [1, 1, 1]
    assert len({event["attempt_id"] for event in batches}) == 1
    assert all(
        event["raw_rows"] is None
        and event["silver_rows"] is None
        and event["coverage_state"] is None
        for event in batches
    )
    completed = [event for event in events if event["event"] == "date_completed"]
    assert [event["completed_dates"] for event in completed] == [1, 2]
    assert [event["raw_rows"] for event in completed] == [1, 2]
    assert events[-1]["coverage_state"] == "unknown"


def test_month_change_starts_a_new_attempt_without_cumulative_saved_rows(
    tmp_path, monkeypatch, caplog
):
    first, second = date(2019, 10, 31), date(2019, 11, 1)
    args, _, _, _, _ = _setup(
        tmp_path,
        monkeypatch,
        counts=((first, 1), (second, 1)),
        rows=[native_row(day=first), native_row(day=second)],
    )
    caplog.set_level(logging.INFO, logger=B._LOGGER.name)
    result = B.bootstrap_stk_factor_pro_history(**args)
    batches = [event for event in _events(caplog) if event["event"] == "batch_saved"]
    assert len(batches) == 2 and batches[0]["attempt_id"] != batches[1]["attempt_id"]
    assert [event["saved_rows"] for event in batches] == [1, 1]
    assert [event["batch_no"] for event in batches] == [1, 1]
    assert [event["month"] for event in batches] == ["2019-10", "2019-11"]
    assert result.verified_source_rows == 2
    assert [query[2][2] for query in args["prod_postgres"].queries if query[0]] == [
        [first],
        [second],
    ]


@pytest.mark.parametrize("middle_closed", [False, True])
def test_empty_date_is_counted_and_replay_restores_completed_date_baseline(
    tmp_path, monkeypatch, caplog, middle_closed
):
    days = (DAY - timedelta(days=1), DAY, DAY + timedelta(days=1))
    counts = ((days[0], 1), (DAY, 0), (days[2], 1))
    args, _, lake, _, _ = _setup(
        tmp_path,
        monkeypatch,
        counts=counts,
        rows=[native_row(day=days[0]), native_row(day=days[2])],
        market={
            "codes": ("000001.SZ",),
            "calendar": [
                ("SSE", days[0], True, None),
                ("SSE", DAY, not middle_closed, days[0]),
                ("SSE", days[2], True, days[0] if middle_closed else DAY),
            ],
        },
    )
    caplog.set_level(logging.INFO, logger=B._LOGGER.name)
    B.bootstrap_stk_factor_pro_history(**args)
    dates = [event for event in _events(caplog) if event["event"] == "date_completed"]
    assert [event["completed_dates"] for event in dates] == [1, 2, 3]
    middle = next(event for event in dates if event["trade_date"] == DAY.isoformat())
    assert middle["raw_rows"] == middle["silver_rows"] == 0
    assert "源0且无业务文件" in middle["outcome"]
    assert middle["coverage_state"] == (None if middle_closed else "incomplete")
    assert (
        not _data(lake, DAY, "raw").exists() and not _data(lake, DAY, "silver").exists()
    )
    caplog.clear()
    replay = dict(args, prod_postgres=NoProd())
    B.bootstrap_stk_factor_pro_history(**replay)
    events = _events(caplog)
    assert events[0]["event"] == "month_started"
    assert events[0]["completed_dates"] == 3
    assert events[0]["reused_source_rows"] == 2
    assert not any(event["event"] == "batch_saved" for event in events)
    assert all(event["saved_rows"] is None for event in events)
    assert all(event["completed_dates"] == 3 for event in events)


@pytest.mark.parametrize("failure", ["raw", "silver", "statistics", "connection_close"])
def test_business_or_connection_close_failure_never_reports_operation_finished(
    tmp_path, monkeypatch, caplog, failure
):
    args, state, lake, _, _ = _setup(tmp_path, monkeypatch)
    caplog.set_level(logging.INFO, logger=B._LOGGER.name)
    primary = OSError(f"intentional {failure} failure")

    def fail(*_values, **_keywords):
        raise primary

    if failure == "connection_close":
        state.close_error = primary
    elif failure == "statistics":
        monkeypatch.setattr(B, "write_stk_factor_pro_bootstrap_coverage_date", fail)
    else:
        monkeypatch.setattr(
            P,
            "build_stk_factor_pro_raw_candidate_from_relation"
            if failure == "raw"
            else "build_stk_factor_pro_silver_candidate",
            fail,
        )
    with pytest.raises(OSError) as caught:
        B.bootstrap_stk_factor_pro_history(**args)
    assert caught.value is primary and state.closed == ["duckdb_closed"]
    events = _events(caplog)
    assert events[-1]["event"] == "operation_failed"
    assert not any(event["event"] == "operation_finished" for event in events)
    completed = [event for event in events if event["event"] == "date_completed"]
    assert len(completed) == (1 if failure == "connection_close" else 0)
    assert _data(lake, DAY, "raw").exists() == (failure != "raw")
    assert _data(lake, DAY, "silver").exists() == (
        failure in ("statistics", "connection_close")
    )


def test_broken_log_handler_warns_once_without_retries_or_repeated_publication(
    tmp_path, monkeypatch, caplog, capsys
):
    args, _, _, _, _ = _setup(tmp_path, monkeypatch)
    caplog.set_level(logging.INFO, logger=B._LOGGER.name)
    calls = []

    class Broken(logging.Handler):
        def emit(self, record):
            calls.append(record)
            raise OSError("token=secret-token password=secret-password")

    monkeypatch.setattr(B._LOGGER, "handlers", [Broken()])
    replacements = []
    original = P.atomic_promote

    def promote(candidate, target):
        replacements.append(target)
        return original(candidate, target)

    monkeypatch.setattr(P, "atomic_promote", promote)
    result = B.bootstrap_stk_factor_pro_history(**args)
    assert result.verified_source_rows == 1
    assert len(calls) >= 4
    assert len(replacements) == 2 and len(set(replacements)) == 2
    remote = args["prod_postgres"]
    assert remote.connections == 1 and len([q for q in remote.queries if q[0]]) == 1
    assert remote.fetch_sizes == [2, 1]
    captured = capsys.readouterr()
    assert captured.err.count("bootstrap进度日志输出失败") == 1
    assert "secret-token" not in captured.out + captured.err
    assert "secret-password" not in captured.out + captured.err


def test_post_publication_capacity_failure_keeps_completed_date_in_failed_summary(
    tmp_path, monkeypatch, caplog
):
    following = DAY + timedelta(days=1)
    args, state, lake, staging, approval = _setup(
        tmp_path,
        monkeypatch,
        counts=((DAY, 1), (following, 1)),
        rows=[native_row(), native_row(day=following)],
    )
    first_result = R.operation_root(staging, approval) / f"coverage/{DAY}/result.json"
    monkeypatch.setattr(
        R.shutil,
        "disk_usage",
        lambda _: SimpleNamespace(free=0 if first_result.exists() else 10**12),
    )
    caplog.set_level(logging.INFO, logger=B._LOGGER.name)
    with pytest.raises(ValueError, match="空间不足"):
        B.bootstrap_stk_factor_pro_history(**args)
    events = _events(caplog)
    assert [event["event"] for event in events[-2:]] == [
        "date_completed",
        "operation_failed",
    ]
    assert events[-2]["trade_date"] == DAY.isoformat()
    assert events[-2]["completed_dates"] == events[-1]["completed_dates"] == 1
    assert first_result.is_file() and state.closed == ["duckdb_closed"]
    assert not any(event["event"] == "operation_finished" for event in events)
    for layer in ("raw", "silver"):
        assert _data(lake, DAY, layer).is_file()
        assert not _data(lake, following, layer).exists()


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
def test_log_control_exception_propagates_and_resources_close(
    tmp_path, monkeypatch, caplog, kind
):
    args, state, _, _, _ = _setup(tmp_path, monkeypatch)
    caplog.set_level(logging.INFO, logger=B._LOGGER.name)
    primary = kind("intentional log interruption")

    class Interrupted(logging.Handler):
        def emit(self, _record):
            raise primary

    monkeypatch.setattr(B._LOGGER, "handlers", [Interrupted()])
    with pytest.raises(kind) as caught:
        B.bootstrap_stk_factor_pro_history(**args)
    assert caught.value is primary and state.closed == ["duckdb_closed"]
    assert args["prod_postgres"].queries == []


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
def test_failure_log_interruption_and_close_error_keep_original_business_error(
    tmp_path, monkeypatch, caplog, kind
):
    args, state, _, _, _ = _setup(tmp_path, monkeypatch)
    caplog.set_level(logging.INFO, logger=B._LOGGER.name)
    primary = RuntimeError("original business failure")
    state.close_error = OSError("connection close failure")

    def fail(*_values, **_keywords):
        raise primary

    class InterruptedOnFailure(logging.Handler):
        def emit(self, record):
            if record.stk_factor_pro_bootstrap["event"] == "operation_failed":
                raise kind("secondary log interruption")

    monkeypatch.setattr(P, "build_stk_factor_pro_raw_candidate_from_relation", fail)
    monkeypatch.setattr(B._LOGGER, "handlers", [InterruptedOnFailure()])
    with pytest.raises(RuntimeError) as caught:
        B.bootstrap_stk_factor_pro_history(**args)
    assert caught.value is primary and state.closed == ["duckdb_closed"]
    assert any("资源退出同时失败" in note for note in primary.__notes__)
    assert any("失败摘要同时中断" in note for note in primary.__notes__)


def test_reused_complete_source_reports_zero_new_downloads(
    tmp_path, monkeypatch, caplog
):
    args, _, lake, staging, approval = _setup(tmp_path, monkeypatch)
    original = P.build_stk_factor_pro_silver_candidate

    def fail(*_values, **_keywords):
        raise OSError("Silver failure after Raw completion")

    monkeypatch.setattr(P, "build_stk_factor_pro_silver_candidate", fail)
    with pytest.raises(OSError, match="Silver failure"):
        B.bootstrap_stk_factor_pro_history(**args)
    root = R.operation_root(staging, approval)
    fragment = next(root.rglob("fragment-*.parquet"))
    prior_fragment_sha = factor_file_sha(fragment)
    prior_raw_sha = factor_file_sha(_data(lake, DAY, "raw"))
    monkeypatch.setattr(P, "build_stk_factor_pro_silver_candidate", original)
    previous = args["prod_postgres"]
    retry = SelectedDateProd(approval, previous.identity, ((DAY, 1),), [native_row()])
    caplog.set_level(logging.INFO, logger=B._LOGGER.name)
    result = B.bootstrap_stk_factor_pro_history(**dict(args, prod_postgres=retry))
    events = _events(caplog)
    assert events[0]["outcome"] == "恢复业务文件"
    assert events[0]["reused_source_rows"] == 1
    assert not any(event["event"] == "batch_saved" for event in events)
    assert all(
        event["attempt_id"] is None and event["saved_rows"] is None for event in events
    )
    assert not any(query[0] for query in retry.queries)
    assert factor_file_sha(fragment) == prior_fragment_sha
    assert factor_file_sha(_data(lake, DAY, "raw")) == prior_raw_sha
    assert result.current_raw_rows == result.current_silver_rows == 1


def test_borrowed_connection_does_not_claim_resource_close_success(
    tmp_path, monkeypatch, caplog
):
    args, _, lake, staging, _ = _setup(tmp_path, monkeypatch)
    caplog.set_level(logging.INFO, logger=B._LOGGER.name)
    with connection(tmp_path) as conn:
        result = B._run_stk_factor_pro_bootstrap(
            conn,
            lake_root=lake,
            staging_root=staging,
            operation_id=args["operation_id"],
            instance=args["instance"],
            prod_postgres=args["prod_postgres"],
        )
        assert result.current_raw_rows == 1
        assert conn.execute("SELECT 1").fetchone() == (1,)
        assert not any(
            event["event"] == "operation_finished" for event in _events(caplog)
        )
