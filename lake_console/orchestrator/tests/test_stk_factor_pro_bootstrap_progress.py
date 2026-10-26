"""LLD 17.8.5: real temporary bootstrap, synchronous standard log records.

Only Prod transport, configured paths, connection ownership and logging failures
are replaced. The 261-column carrier comes from the doc328-based native fixture;
source persistence, two-layer publication and coverage records are real.
"""

import logging
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
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
from tests.test_stk_factor_pro_bootstrap_coverage import supplement_audits, upstream
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
    "source_rows",
    "raw_rows",
    "silver_rows",
    "coverage_state",
    "reused_source_rows",
    "elapsed_seconds",
    "updated_at",
    "outcome",
    "space_estimate_stage",
    "space_initial_estimate",
    "space_latest_estimate",
    "space_initial_row_bytes",
    "space_observed_row_bytes",
    "space_initial_record_bytes",
    "space_observed_record_bytes",
    "space_latest_observation",
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
    assert [event["source_rows"] for event in completed] == [1, 2]
    assert all(
        event["source_rows"] is None
        for event in events
        if event["event"] != "date_completed"
    )
    first_budget = {
        "source_bytes": 4_206_838,
        "candidate_bytes": 16_802_284,
        "temp_bytes": 50_415_208,
        "record_bytes": 3_145_728,
    }
    assert all(event["space_initial_estimate"] == first_budget for event in events)
    assert events[0]["space_latest_estimate"] == first_budget
    assert events[-1]["space_latest_estimate"]["source_bytes"] == 0
    assert events[-1]["space_latest_estimate"]["candidate_bytes"] == 0
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
    assert middle["source_rows"] == 0
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
    assert len(calls) == 4
    assert all(FIELDS <= record.stk_factor_pro_bootstrap.keys() for record in calls)
    assert all(
        record.stk_factor_pro_bootstrap["space_initial_estimate"] is not None
        for record in calls
    )
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
    assert events[-2]["source_rows"] == 1
    assert events[-1]["source_rows"] is None
    assert events[-1]["space_estimate_stage"] == "完整日期处理完成"
    assert events[-1]["space_initial_estimate"] == {
        "source_bytes": 4_202_660,
        "candidate_bytes": 16_793_928,
        "temp_bytes": 50_398_496,
        "record_bytes": 3_145_728,
    }
    assert events[-1]["space_latest_estimate"]["source_bytes"] == 0
    assert events[-1]["space_latest_estimate"]["candidate_bytes"] == 8_396_964
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
    dates = [event for event in events if event["event"] == "date_completed"]
    assert len(dates) == 1 and dates[0]["source_rows"] == 1
    assert all(
        event["source_rows"] is None
        for event in events
        if event["event"] != "date_completed"
    )


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


def test_supplement_log_keeps_original_zero_source_separate_from_five_current_rows(
    tmp_path, monkeypatch, caplog
):
    # Existing approved import and independent supplement fixture both use the
    # real 261-column producer; only the DG publication reader remains replaced.
    days = (DAY - timedelta(days=1), DAY, DAY + timedelta(days=1))
    args, _, lake, staging, approval = _setup(
        tmp_path,
        monkeypatch,
        counts=((days[0], 1), (DAY, 0), (days[2], 1)),
        rows=[native_row(day=days[0]), native_row(day=days[2])],
    )
    caplog.set_level(logging.INFO, logger=B._LOGGER.name)
    B.bootstrap_stk_factor_pro_history(**args)
    root = R.operation_root(staging, approval)
    source_path = root / f"source/dates/{DAY}/source-complete.json"
    original_source = source_path.read_bytes()
    caplog.clear()
    with connection(tmp_path) as conn:
        raw, silver = supplement_audits(
            conn,
            {"trade_date": DAY, "lake_root": lake},
            ("000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ", "000005.SZ"),
        )
        publication = C.StkFactorProBootstrapCurrentPublication(
            "supplement-run",
            DAY,
            11,
            12,
            13,
            14,
            raw.file_sha256,
            silver.file_sha256,
            raw.file_sha256,
            approval.contract_content_digest,
            "1",
        )
        result = B._run_stk_factor_pro_bootstrap(
            conn,
            lake_root=lake,
            staging_root=staging,
            operation_id=approval.operation_id,
            instance=args["instance"],
            prod_postgres=NoProd(),
            current_publications=((publication, raw, silver),),
        )
    events = _events(caplog)
    assert [event["event"] for event in events] == [
        "month_started",
        "date_completed",
        "date_completed",
        "date_completed",
    ]
    dates = [event for event in events if event["event"] == "date_completed"]
    assert [
        (event["source_rows"], event["raw_rows"], event["silver_rows"])
        for event in dates
    ] == [(1, 1, 1), (0, 5, 5), (1, 1, 1)]
    assert events[0]["source_rows"] is None
    assert all(event["saved_rows"] is None for event in events)
    assert result.verified_source_rows == 2
    assert result.current_raw_rows == result.current_silver_rows == 7
    assert source_path.read_bytes() == original_source


def test_space_observation_adds_no_io_or_events_and_reports_literal_size_differences(
    tmp_path, monkeypatch, caplog
):
    # This is metadata arithmetic only. The sparse files below deliberately are
    # not business Parquet/JSON records and never enter a source/publication path.
    _args, _, lake, staging, approval = _setup(tmp_path, monkeypatch)
    progress = B._BootstrapProgress(approval.operation_id)
    caplog.set_level(logging.INFO, logger=B._LOGGER.name)
    with connection(tmp_path) as conn:
        classified = {DAY: (None, False, False, None)}
        common = {
            "lake_root": lake,
            "staging_root": staging,
            "approval": approval,
            "counts": {DAY: 1},
            "classified": classified,
        }
        plain = B._bootstrap_space_check(conn, **common)
        watched = B._bootstrap_space_check(conn, **common, progress=progress)
        root = R.operation_root(staging, approval)
        stats, capacities = [], []
        real_stat = Path.stat

        def stat(path, *values, **keywords):
            stats.append(path)
            return real_stat(path, *values, **keywords)

        def capacity(path):
            capacities.append(path)
            return SimpleNamespace(free=10**12)

        monkeypatch.setattr(Path, "stat", stat)
        monkeypatch.setattr(R.shutil, "disk_usage", capacity)

        def both(stage, **values):
            stats.clear()
            capacities.clear()
            baseline = plain(stage, **values)
            original_counts = (len(stats), len(capacities))
            stats.clear()
            capacities.clear()
            observed = watched(stage, **values)
            assert observed == baseline
            assert (len(stats), len(capacities)) == original_counts
            assert not _events(caplog)
            return observed

        both("首次预算", path=root)
        first = {
            "source_bytes": 4_198_482,
            "candidate_bytes": 8_396_964,
            "temp_bytes": 50_381_784,
            "record_bytes": 2_097_152,
        }
        assert progress.fields["space_initial_estimate"] == first
        assert progress.fields["space_latest_estimate"] == first
        assert progress.fields["space_latest_observation"] is None
        assert progress.fields["space_initial_row_bytes"] == 4178
        assert progress.fields["space_observed_row_bytes"] == 4178
        assert progress.fields["space_initial_record_bytes"] == 1_048_576
        assert progress.fields["space_observed_record_bytes"] == 1_048_576

        record = root / "coverage" / str(DAY) / "size-observation.json"
        record.parent.mkdir(parents=True, exist_ok=True)
        with record.open("wb") as stream:
            stream.truncate(3_145_728)
        both("记录已保存", path=record, trade_date=DAY, event="record_saved")
        assert capacities == []  # Saved record observation remains no admission.
        assert progress.fields["space_initial_estimate"] == first
        assert progress.fields["space_latest_estimate"]["record_bytes"] == 3_145_728
        assert progress.fields["space_observed_record_bytes"] == 3_145_728
        assert progress.fields["space_latest_observation"] == {
            "stage": "记录已保存",
            "trade_date": DAY.isoformat(),
            "kind": "record_group",
            "rows": None,
            "initial_estimate_bytes": 1_048_576,
            "actual_bytes": 3_145_728,
            "difference_bytes": 2_097_152,
        }
        data = root / "size-observation.parquet"
        with data.open("wb") as stream:
            stream.truncate(4_208_482)
        both("数据已保存", path=data, trade_date=DAY, rows=1)
        assert progress.fields["space_latest_observation"] == {
            "stage": "数据已保存",
            "trade_date": DAY.isoformat(),
            "kind": "data_file",
            "rows": 1,
            "initial_estimate_bytes": 4_198_482,
            "actual_bytes": 4_208_482,
            "difference_bytes": 10_000,
        }
        assert progress.fields["space_observed_row_bytes"] == 14_178
        assert progress.fields["space_initial_estimate"] == first
        with data.open("wb") as stream:
            stream.truncate(32)
        both("较小文件观测", path=data, trade_date=DAY, rows=1)
        assert (
            progress.fields["space_latest_observation"]["difference_bytes"]
            == -4_198_450
        )
        assert progress.fields["space_observed_row_bytes"] == 14_178
        latest = progress.fields["space_latest_observation"]
        both("最终统计准备前", path=root, event="final_statistics")
        assert progress.fields["space_estimate_stage"] == "最终统计准备前"
        assert progress.fields["space_latest_observation"] == latest
        assert progress.fields["space_initial_estimate"] == first

        failed_progress = B._BootstrapProgress(approval.operation_id)
        failing = B._bootstrap_space_check(conn, **common, progress=failed_progress)
        monkeypatch.setattr(R.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
        with pytest.raises(ValueError, match="空间不足"):
            failing("首次不足", path=root)
        assert failed_progress.fields["space_estimate_stage"] == "首次不足"
        assert failed_progress.fields["space_initial_estimate"] == first
        assert failed_progress.fields["space_latest_estimate"] == first
        assert not _events(caplog)
