"""LLD 04.4/19.17: real temporary SQL, isolated stop signal, no source reads.

The 21-row normal history input is the independently specified post-qfq
seq/close from the failed D2 check: first ten closes 5, last eleven 10.
Only the history/rename/cleanup boundary is replayed, not file reads or qfq.
Other literal rows locate the same rename failure and cancellation boundaries.
No real ExecutionControl, monitor thread, server or durable database is used.
"""

import json
import threading
from time import monotonic
from types import SimpleNamespace

import pyarrow as pa
import pytest

from src.foundation.config.settings import Settings
from src.foundation.technical_indicators import CalculationInstance, CalculationRequest
from src.foundation.technical_indicators.calculation.calculation import SqlStep
from src.foundation.technical_indicators.calculation.history import HistoryRequirement
from src.foundation.technical_indicators.configuration import KernelConfig
from src.foundation.technical_indicators.errors import CalculationCancelledError, CalculationExecutionError
from src.foundation.technical_indicators.service import TechnicalIndicatorService
from src.foundation.technical_indicators.sources.contracts import PriceBatch, ReadRequirement
from src.foundation.technical_indicators.sources.session import PriceInputSession


class RenameTestControl:
    """Replace only timing/monitoring; database execution and cleanup are real."""

    clock = staticmethod(monotonic)

    def __init__(self):
        self.owner = threading.get_ident()
        self.stop_requested_at = self.resources_released_at = None
        self.cleanup_ready = False
        self.stopped = False

    def _assert_working_thread(self):
        assert threading.get_ident() == self.owner

    def check_active(self):
        if self.stopped:
            raise CalculationCancelledError("Injected stop after table rename")

    def start_monitor(self, callback):
        self._assert_working_thread()  # Deliberately no background thread.

    def _note_sql_returned(self):
        pass

    def stop_monitor(self):
        self.cleanup_ready = True
        return ()


@pytest.fixture
def rename_execution(record_property):
    cfg = KernelConfig.from_settings(Settings(_env_file=None,
        GOLDENSHARE_LAKE_ROOT="/not-accessed/data_lake"))
    service = TechnicalIndicatorService(source=None, registry=None, config=cfg)
    control = RenameTestControl()
    connection, executor = service._open_execution(control)
    state = SimpleNamespace(connection=connection, executor=executor, control=control,
                            inputs=None, literal_rows=0, verification_rows=0)

    def literal(name, select, rows):
        state.literal_rows += rows
        executor.execute(SqlStep("literal", f"CREATE TEMP TABLE {name} AS {select}",
                                 (), (), (name,), rows))

    def value(sql, rows):
        state.verification_rows += rows
        return executor.scalar(sql)

    state.literal, state.value = literal, value
    try:
        yield state
    finally:
        try:
            assert control.stop_monitor() == ()
            if state.inputs is not None:
                state.inputs.close()
                assert not state.inputs._tables and state.inputs._closed
                # Do not sweep executor entries: this is the original failing
                # assertion, after the real owner's cleanup has run.
                assert not executor._live_tables and not executor._live_arrow
            else:
                for name in tuple(executor._live_arrow):
                    executor.cleanup_unregister(name)
                for name in tuple(executor._live_tables):
                    executor.cleanup_drop(name)
            assert not executor._live_tables and not executor._live_arrow
            assert connection.execute(
                "SELECT table_name FROM duckdb_tables() "
                "WHERE temporary AND starts_with(table_name, 'ti_')").fetchall() == []
        finally:
            errors = service._close_execution(control, connection)
            record_property("rename_metrics", json.dumps(dict(
                literal_rows=state.literal_rows, source_rows=0, real_controls=0,
                sql_logical_rows=executor.sql_processed_rows + state.verification_rows,
                final_live_tables=sorted(executor._live_tables),
                final_live_arrow=sorted(executor._live_arrow),
                inputs_failed=None if state.inputs is None else state.inputs._failed,
                cleanup_errors=[str(error) for error in errors],
            ), sort_keys=True))
            assert not errors


def test_rename_reuses_released_target_and_keeps_plain_sql_inputs(rename_execution):
    s = rename_execution
    s.literal("ti_history_next", "SELECT * FROM (VALUES (5.0),(6.0)) p(close)", 2)
    stats = s.executor.rename_table("ti_history_next", "ti_history", processed_rows=2)
    assert s.executor._live_tables == {"ti_history"}
    assert (stats.step_name, stats.logical_input_rows, stats.output_rows, stats.failed) == (
        "rename_table", 2, 0, False)
    assert s.value("SELECT list(close ORDER BY close) FROM ti_history", 2) == [5.0, 6.0]
    s.executor.drop_table("ti_history")
    s.literal("ti_history_next", "SELECT 7.0 AS close", 1)
    s.executor.rename_table("ti_history_next", "ti_history", processed_rows=1)
    s.executor.execute(SqlStep("plain copy", "CREATE TEMP TABLE ti_copy AS SELECT * FROM ti_history",
                              (), ("ti_history",), ("ti_copy",), 1))
    assert s.executor._live_tables == {"ti_history", "ti_copy"}
    assert s.value("SELECT close FROM ti_copy", 1) == 7.0
    s.executor.drop_table("ti_copy")
    s.executor.drop_table("ti_history")
    assert s.control.stop_monitor() == ()
    s.executor.cleanup_drop("ti_history_next")
    s.executor.cleanup_drop("ti_history")


def test_rename_rejects_invalid_names_ownership_conflicts_and_row_counts(rename_execution):
    s = rename_execution
    s.literal("ti_history_next", "SELECT 5.0 AS close", 1)
    s.literal("ti_other", "SELECT 6.0 AS close", 1)
    s.executor.register_arrow("ti_arrow", pa.record_batch([pa.array([1.0])], names=["close"]))
    s.literal_rows += 1
    cases = [
        ("ti_unknown", "ti_history", 1), ("ti_arrow", "ti_history", 1),
        ("ti_history_next", "ti_history_next", 1), ("ti_history_next", "ti_arrow", 1),
        ("ti_history_next", "ti_other", 1),
        ("ti_history_next", 'ti_bad";DROP TABLE ti_history_next', 1),
        ("ti_history_next", "ti_history", -1), ("ti_history_next", "ti_history", True),
    ]
    before = len(s.executor.statistics)
    for old, new, rows in cases:
        with pytest.raises(ValueError):
            s.executor.rename_table(old, new, processed_rows=rows)
    assert len(s.executor.statistics) == before
    s.executor.rename_table("ti_history_next", "ti_history", processed_rows=1)
    s.executor.declare_table("ti_history_next")
    with pytest.raises(ValueError):
        s.executor.rename_table("ti_history", "ti_arrow", processed_rows=1)
    # Even a formerly registered old name is no longer a live source.
    with pytest.raises(ValueError):
        s.executor.rename_table("ti_history_next", "ti_history", processed_rows=1)
    s.control.stopped = True
    before = len(s.executor.statistics)
    with pytest.raises(CalculationCancelledError):
        s.executor.rename_table("ti_history", "ti_unused", processed_rows=1)
    assert "ti_unused" in s.executor._known_tables and "ti_unused" not in s.executor._live_tables
    assert "ti_history" in s.executor._live_tables and len(s.executor.statistics) == before


@pytest.mark.parametrize("when", ["before", "after"])
def test_rename_sql_error_keeps_both_cleanup_names(rename_execution, when):
    s = rename_execution
    s.literal("ti_history_next", "SELECT 5.0 AS close", 1)

    class FailingRename:
        def execute(self, sql, *args):
            if sql.startswith("ALTER TABLE"):
                if when == "after":
                    s.connection.execute(sql, *args)
                raise OSError("Injected driver error during rename")
            return s.connection.execute(sql, *args)

    s.executor.connection = FailingRename()
    with pytest.raises(CalculationExecutionError) as raised:
        s.executor.rename_table("ti_history_next", "ti_history", processed_rows=1)
    assert isinstance(raised.value.__cause__, OSError)
    assert s.executor._live_tables == {"ti_history_next", "ti_history"}
    assert s.executor.statistics[-1].failed
    existing = s.connection.execute(
        "SELECT table_name FROM duckdb_tables() WHERE temporary").fetchall()
    assert existing == [("ti_history" if when == "after" else "ti_history_next",)]


@pytest.mark.parametrize("mode", ["normal", "sql_error", "cancel"])
def test_session_history_rename_and_cleanup(rename_execution, mode):
    s = rename_execution
    request = CalculationRequest("stock", "600000.SH", "day",
        (CalculationInstance("price", "price", {}),), adjustment="qfq")
    rows, keep = (21, 19) if mode == "normal" else (3, 2)
    requirement = ReadRequirement(request, HistoryRequirement(frozenset(("close",)), keep,
        None, True, (), "Literal post-adjustment history"), 8192, None, None)
    inputs = PriceInputSession(s.executor, None, requirement, read_context=None)
    s.inputs = inputs
    # Start at the already materialized input boundary; no file/source is used.
    inputs._own_table("ti_price_window")
    s.literal("ti_price_window", "SELECT i::BIGINT AS seq, "
              "CASE WHEN i<=10 THEN 5.0::DOUBLE ELSE 10.0::DOUBLE END AS close "
              f"FROM range(1,{rows+1}) p(i)", rows)
    inputs._prepared, inputs._rows = True, rows
    inputs._batch = PriceBatch("ti_price_window", 1, rows, rows, 0, (), ("close",), "qfq")
    if mode != "normal":
        class StopOrFailRename:
            def execute(self, sql, *args):
                if sql.startswith("ALTER TABLE") and mode == "sql_error":
                    raise OSError("Injected history rename error")
                result = s.connection.execute(sql, *args)
                if sql.startswith("ALTER TABLE"):
                    s.control.stopped = True
                return result
        s.executor.connection = StopOrFailRename()
        expected = CalculationExecutionError if mode == "sql_error" else CalculationCancelledError
        with pytest.raises(expected):
            inputs.retain_required_history()
        assert inputs._failed and not inputs._retained
        assert {"ti_history", "ti_history_next"} <= set(inputs._tables)
        assert ("ti_history_next" in s.executor._live_tables) == (mode == "sql_error")
        with pytest.raises(RuntimeError):
            inputs.finish_batch()
        with pytest.raises(RuntimeError):
            inputs.next_batch()
    else:
        inputs.retain_required_history()
        assert inputs._tables == ["ti_price_window", "ti_history"]
        assert s.executor._live_tables == {"ti_price_window", "ti_history"}
        assert s.value("SELECT list(seq ORDER BY seq) FROM ti_history", 19) == list(range(3, 22))
        assert s.value("SELECT list(close ORDER BY seq) FROM ti_history", 19) == [5.0]*8+[10.0]*11
        inputs.finish_batch()
        assert s.executor._live_tables == {"ti_history"}
