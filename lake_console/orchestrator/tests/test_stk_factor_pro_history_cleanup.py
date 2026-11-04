"""LLD 16/18: real temporary inputs, source ownership and cleanup failures.

Range/manifest fixtures follow the existing closed 12/17-column contracts;
source rows use doc328's 261 fields, and factor files use the actual three
columns from the adj_factor producer. Only the indicated operation is faulted.
"""

from __future__ import annotations

import sys

import pytest
from duckdb import Error as DuckDBError

from orchestrator.defs.checks import stk_factor_pro as checks
from orchestrator.defs.io import stk_factor_pro_download as downloads
from orchestrator.defs.io import stk_factor_pro_history as history
from tests.stk_factor_pro_history_test_support import (
    connection,
    contract,
    eligibility,
    identity,
    roots,
    write_factor_file,
)
from tests.test_stk_factor_pro_history_download import (
    prepare,
    run_download,
    sample_downloader,
)
from tests.test_stk_factor_pro_history_plan import inputs, prior, start
from tests.test_stk_factor_pro_history_records import (
    new_plan,
    ranges,
    root_for,
)
from tests.test_stk_factor_pro_history_scope import A, B, T, prepared, resolve

MODES = ("normal", "primary_only", "cleanup_only", "primary_and_cleanup")
ACTIONS = {
    "writer": (
        "unregister:stk_factor_pro_record_frame",
        "DROP TABLE IF EXISTS stk_factor_pro_record_rows",
    ),
    "source": ("DROP TABLE IF EXISTS stk_factor_pro_history_source",),
    "plan": (
        "DROP TABLE IF EXISTS stk_factor_pro_history_factor_t",
        "DROP TABLE IF EXISTS stk_factor_pro_history_factor_p",
    ),
}


class CleanupConnection:
    """Delegate to DuckDB; fail only COPY or the selected first cleanup."""

    def __init__(self, conn, entry, mode):
        self.conn, self.entry, self.mode = conn, entry, mode
        self.actions = ACTIONS[entry]
        self.attempts = []
        self.first_cleanup_primary = None
        self.copy_attempts = 0
        self.primary_error = OSError("controlled record COPY failure")
        self.cleanup_error = DuckDBError("controlled first cleanup failure")

    def __getattr__(self, name):
        return getattr(self.conn, name)

    @property
    def fail_primary(self):
        return self.mode in ("primary_only", "primary_and_cleanup")

    @property
    def fail_cleanup(self):
        return self.mode in ("cleanup_only", "primary_and_cleanup")

    def _release(self, action, call):
        if action not in self.actions:
            return call()
        if not self.attempts:
            self.first_cleanup_primary = sys.exception()
        self.attempts.append(action)
        if self.fail_cleanup and action == self.actions[0]:
            raise self.cleanup_error
        return call()

    def execute(self, statement, parameters=None):
        text = str(statement).strip()
        if self.entry == "writer" and text.upper().startswith("COPY "):
            self.copy_attempts += 1
            if self.fail_primary:
                raise self.primary_error

        def call():
            if parameters is None:
                return self.conn.execute(statement)
            return self.conn.execute(statement, parameters)

        return self._release(text, call)

    def unregister(self, name):
        return self._release(f"unregister:{name}", lambda: self.conn.unregister(name))


def assert_outcome(wrapped, invoke, expected_primary_type, known_primary=None):
    if not wrapped.fail_primary and not wrapped.fail_cleanup:
        result = invoke()
    else:
        error_type = expected_primary_type if wrapped.fail_primary else DuckDBError
        with pytest.raises(error_type) as caught:
            invoke()
        if wrapped.fail_primary:
            # Capture the independently produced body error at the first
            # cleanup, rather than regenerating an expected error message.
            assert caught.value is wrapped.first_cleanup_primary
            if known_primary is not None:
                assert caught.value is known_primary
        else:
            assert caught.value is wrapped.cleanup_error
            assert wrapped.first_cleanup_primary is None
        if wrapped.fail_cleanup:
            assert any(
                type(wrapped.cleanup_error).__name__ in note
                for note in getattr(caught.value, "__notes__", ())
            )
        result = None
    assert tuple(wrapped.attempts) == wrapped.actions
    return result


def table_count(conn, name):
    return conn.execute(
        "SELECT count(*) FROM duckdb_tables() WHERE table_name=?", [name]
    ).fetchone()[0]


@pytest.mark.parametrize("mode", MODES)
def test_record_cleanup_preserves_copy_error_and_attempts_drop(tmp_path, mode):
    known_records = {}
    with connection(tmp_path) as conn:
        wrapped = CleanupConnection(conn, "writer", mode)
        plan = assert_outcome(
            wrapped,
            lambda: history.write_stk_factor_pro_history_plan(
                root_for(tmp_path),
                new_plan(),
                ranges(),
                connection=wrapped,
                known_records=known_records,
            ),
            OSError,
            wrapped.primary_error,
        )
        # This must reach COPY with the full valid range schema; an earlier
        # input rejection would not reproduce the audited write failure.
        assert wrapped.copy_attempts == 1
        assert table_count(conn, "stk_factor_pro_record_rows") == 0
        if mode == "normal":
            assert plan[0].full_code_count == 1
        if mode == "cleanup_only":
            assert (root_for(tmp_path) / "history-ranges.parquet").is_file()


@pytest.mark.parametrize("mode", MODES)
def test_plan_cleanup_retains_cancellation_and_attempts_both_tables(tmp_path, mode):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        refs = inputs(conn, lake)
        wrapped = CleanupConnection(conn, "plan", mode)
        cancellation = KeyboardInterrupt("controlled planning cancellation")
        cancellation_checks = 0

        def cancel():
            nonlocal cancellation_checks
            cancellation_checks += 1
            assert table_count(conn, "stk_factor_pro_history_factor_t") == 1
            assert table_count(conn, "stk_factor_pro_history_factor_p") == 1
            if wrapped.fail_primary:
                raise cancellation

        def plan_and_release():
            primary = None
            try:
                factor_relations, lifecycle_relation = (
                    history.prepare_stk_factor_pro_history_inputs(
                        wrapped,
                        identity=identity(),
                        lake_root=lake,
                        factor_t=refs[0],
                        factor_p=refs[1],
                        known_records=known_records,
                        check_cancel=lambda: None,
                    )
                )
                return history.build_stk_factor_pro_history_plan(
                    wrapped,
                    identity=identity(),
                    contract=contract(),
                    lake_root=lake,
                    staging_root=staging,
                    factor_t=refs[0],
                    factor_p=refs[1],
                    factor_relations=factor_relations,
                    lifecycle_relation=lifecycle_relation,
                    prior_results=prior(),
                    history_starts=(start(),),
                    check_cancel=cancel,
                    known_records=known_records,
                )[0]
            except BaseException as error:
                primary = error
                raise
            finally:
                history.release_stk_factor_pro_history_inputs(wrapped, primary=primary)

        plan = assert_outcome(
            wrapped,
            plan_and_release,
            KeyboardInterrupt,
            cancellation,
        )
        assert cancellation_checks >= 1
        assert table_count(conn, "stk_factor_pro_history_factor_t") == int(
            wrapped.fail_cleanup
        )
        assert table_count(conn, "stk_factor_pro_history_factor_p") == 0
        if mode == "normal":
            assert plan.full_code_count == 1


@pytest.mark.parametrize("mode", MODES)
def test_owned_history_source_release_preserves_cancellation_and_saved_facts(
    tmp_path, mode
):
    known_records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=known_records)
        downloader = sample_downloader()
        source = run_download(conn, args, downloader, known_records=known_records)
        assert conn.execute(
            f"SELECT ts_code,trade_date,close FROM {source.source_relation} ORDER BY ts_code,trade_date"
        ).fetchall() == [(A, "20261015", 10.0), (A, "20261016", 10.0)]
        complete = root / "source/history/source-complete.json"
        before = complete.read_bytes()
        wrapped = CleanupConnection(conn, "source", mode)
        cancellation = KeyboardInterrupt("controlled history owner cancellation")

        def release():
            primary = None
            try:
                if wrapped.fail_primary:
                    raise cancellation
            except BaseException as error:
                primary = error
                raise
            finally:
                downloads.release_stk_factor_pro_history_source(
                    wrapped, primary=primary
                )

        assert_outcome(wrapped, release, KeyboardInterrupt, cancellation)
        assert table_count(conn, source.source_relation) == int(wrapped.fail_cleanup)
        assert table_count(conn, "stk_factor_pro_history_factor_t") == 0
        assert table_count(conn, "stk_factor_pro_history_factor_p") == 0
        assert downloader.sessions[0].closed
        assert complete.read_bytes() == before


@pytest.mark.parametrize("changed", [False, True])
def test_history_input_recheck_uses_first_identity_without_reading_again(
    tmp_path, monkeypatch, changed
):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, saved_ranges, _, _ = prepared(
            conn, lake, staging, known_records=known_records
        )
        units = resolve(conn, staging, plan, saved_ranges, known_records=known_records)
        allowed = eligibility(plan.identity, plan)
        facts = (
            plan.factor_t_ref,
            plan.factor_p_ref,
            allowed.raw_coverage,
            allowed.target_silver,
        )
        if changed:
            # A real new version is a changed input even when only another stock differs.
            write_factor_file(conn, lake, T, ((A, 2.0), (B, 2.0)))

        class NoQueries:
            def execute(self, *args, **kwargs):
                raise AssertionError("输入重核不得重新查询业务数据")

        def no_hash(*args, **kwargs):
            raise AssertionError("输入重核不得重算首次SHA")

        monkeypatch.setattr(history, "factor_file_sha", no_hash)
        monkeypatch.setattr(checks, "factor_file_sha", no_hash)
        arguments = {
            "plan": plan,
            "ranges": saved_ranges,
            "expected_units": units,
            "lake_root": lake,
            "recheck_inputs": lambda: facts,
            "known_records": known_records,
        }
        if changed:
            with pytest.raises(ValueError, match="改变|变化"):
                history.recheck_stk_factor_pro_history_inputs(NoQueries(), **arguments)
        else:
            assert (
                history.recheck_stk_factor_pro_history_inputs(NoQueries(), **arguments)
                == facts
            )
        assert table_count(conn, "stk_factor_pro_history_recheck_t") == 0
        assert table_count(conn, "stk_factor_pro_history_recheck_p") == 0
