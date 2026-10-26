"""LLD 16.5: real temporary inputs and faults at the four cleanup boundaries.

Range/manifest fixtures follow the existing closed 12/17-column contracts;
source rows use doc328's 261 fields, and factor files use the actual three
columns from the adj_factor producer. Only the indicated operation is faulted.
"""

from __future__ import annotations

import sys

import pytest
from duckdb import Error as DuckDBError

from orchestrator.defs.io import stk_factor_pro_history as history
from tests.stk_factor_pro_history_test_support import (
    connection,
    eligibility,
    roots,
    write_factor_file,
)
from tests.test_stk_factor_pro_history_plan import build, inputs
from tests.test_stk_factor_pro_history_records import (
    new_plan,
    ranges,
    root_for,
    save_source,
)
from tests.test_stk_factor_pro_history_scope import A, B, P, T, prepared, resolve

MODES = ("normal", "primary_only", "cleanup_only", "primary_and_cleanup")
ACTIONS = {
    "writer": (
        "unregister:stk_factor_pro_record_frame",
        "DROP TABLE IF EXISTS stk_factor_pro_record_rows",
    ),
    "verify": ("DROP VIEW IF EXISTS stk_factor_pro_verified_source_unit",),
    "plan": (
        "DROP TABLE IF EXISTS stk_factor_pro_history_factor_t",
        "DROP TABLE IF EXISTS stk_factor_pro_history_factor_p",
    ),
    "recheck": (
        "DROP TABLE IF EXISTS stk_factor_pro_history_recheck_t",
        "DROP TABLE IF EXISTS stk_factor_pro_history_recheck_p",
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
        return self._release(
            f"unregister:{name}", lambda: self.conn.unregister(name)
        )


def assert_outcome(wrapped, invoke, expected_primary_type, known_primary=None):
    if not wrapped.fail_primary and not wrapped.fail_cleanup:
        result = invoke()
    else:
        error_type = (
            expected_primary_type if wrapped.fail_primary else DuckDBError
        )
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
    with connection(tmp_path) as conn:
        wrapped = CleanupConnection(conn, "writer", mode)
        plan = assert_outcome(
            wrapped,
            lambda: history.write_stk_factor_pro_history_plan(
                root_for(tmp_path), new_plan(), ranges(), connection=wrapped
            ),
            OSError,
            wrapped.primary_error,
        )
        # This must reach COPY with the full valid range schema; an earlier
        # input rejection would not reproduce the audited write failure.
        assert wrapped.copy_attempts == 1
        assert table_count(conn, "stk_factor_pro_record_rows") == 0
        if mode == "normal":
            assert plan.full_code_count == 1
        if mode == "cleanup_only":
            assert (root_for(tmp_path) / "history-ranges.parquet").is_file()


@pytest.mark.parametrize("mode", MODES)
def test_source_cleanup_keeps_original_field_error_visible(tmp_path, mode):
    with connection(tmp_path) as conn:
        root = root_for(tmp_path)
        bad_source = mode in ("primary_only", "primary_and_cleanup")
        _, source, unit, path = save_source(
            conn, root, kind="missing_column" if bad_source else "normal"
        )
        before = path.read_bytes()
        wrapped = CleanupConnection(conn, "verify", mode)
        verified = assert_outcome(
            wrapped,
            lambda: history.verify_stk_factor_pro_current_source(
                root,
                source,
                connection=wrapped,
                current_run_id="run-a",
                expected_units=(unit,),
            ),
            ValueError,
        )
        remaining = conn.execute(
            "SELECT count(*) FROM duckdb_views() WHERE view_name=?",
            ["stk_factor_pro_verified_source_unit"],
        ).fetchone()[0]
        # The deliberately failed DROP cannot be assumed to succeed.
        assert remaining == int(wrapped.fail_cleanup)
        assert path.read_bytes() == before
        if mode == "normal":
            assert verified.source_complete == source


@pytest.mark.parametrize("mode", MODES)
def test_plan_cleanup_retains_cancellation_and_attempts_both_tables(tmp_path, mode):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        refs = inputs(conn, lake)
        wrapped = CleanupConnection(conn, "plan", mode)
        cancellation = KeyboardInterrupt("controlled planning cancellation")
        cancellation_checks = 0

        def cancel():
            nonlocal cancellation_checks
            cancellation_checks += 1
            if cancellation_checks == 2:
                assert table_count(conn, "stk_factor_pro_history_factor_t") == 1
                assert table_count(conn, "stk_factor_pro_history_factor_p") == 1
                if wrapped.fail_primary:
                    raise cancellation

        plan = assert_outcome(
            wrapped,
            lambda: build(wrapped, lake, staging, refs, cancel=cancel),
            KeyboardInterrupt,
            cancellation,
        )
        assert cancellation_checks == 2
        assert table_count(conn, "stk_factor_pro_history_factor_t") == int(
            wrapped.fail_cleanup
        )
        assert table_count(conn, "stk_factor_pro_history_factor_p") == 0
        if mode == "normal":
            assert plan.full_code_count == 1


@pytest.mark.parametrize("mode", MODES)
def test_recheck_cleanup_retains_factor_error_and_attempts_second_table(tmp_path, mode):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, saved_ranges, _, _ = prepared(conn, lake, staging)
        units = resolve(conn, staging, plan, saved_ranges)
        wrapped = CleanupConnection(conn, "recheck", mode)
        # Both files have real byte changes. Legitimate changes to B alone
        # create both relations without invalidating requested stock A.
        ft = write_factor_file(
            conn, lake, T, ((A, 3.0 if wrapped.fail_primary else 2.0), (B, 2.0))
        )
        fp = write_factor_file(conn, lake, P, ((A, 1.0), (B, 2.0)))
        allowed = eligibility(plan.identity, plan)
        facts = (ft, fp, allowed.raw_coverage, allowed.target_silver)
        result = assert_outcome(
            wrapped,
            lambda: history.recheck_stk_factor_pro_history_inputs(
                wrapped,
                plan=plan,
                ranges=saved_ranges,
                expected_units=units,
                lake_root=lake,
                recheck_inputs=lambda: facts,
            ),
            ValueError,
        )
        assert table_count(conn, "stk_factor_pro_history_recheck_t") == int(
            wrapped.fail_cleanup
        )
        assert table_count(conn, "stk_factor_pro_history_recheck_p") == 0
        if mode == "normal":
            assert result == facts
