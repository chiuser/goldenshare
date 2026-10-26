"""Working-thread DuckDB operations; resource names are registered, not inferred."""

from __future__ import annotations

import re
import threading

from .calculation.calculation import ExecutionStats, SqlStep
from .errors import (
    CalculationExecutionError, OutputContractError, OutputReadError,
    ResourceLimitError, TechnicalIndicatorError,
)
from .execution_control import ExecutionControl


_INTERNAL_NAME = re.compile(r"ti_[a-z][a-z0-9_]*\Z")


class DuckDBExecutor:
    def __init__(self, connection, control: ExecutionControl):
        self.connection = connection
        self.control = control
        self._owner_thread = threading.get_ident()
        self._executing = False
        self._known_tables: set[str] = set()
        self._live_tables: set[str] = set()
        self._known_arrow: set[str] = set()
        self._live_arrow: set[str] = set()
        self._statistics: list[ExecutionStats] = []

    @property
    def statistics(self) -> tuple[ExecutionStats, ...]:
        return tuple(self._statistics)

    @property
    def sql_processed_rows(self) -> int:
        return sum(item.logical_input_rows for item in self._statistics)

    def _assert_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("DuckDB operations must remain in their working thread")
        if self._executing:
            raise RuntimeError("A DuckDB operation is already active")

    @staticmethod
    def _validate_name(name: str) -> None:
        if not isinstance(name, str) or not _INTERNAL_NAME.fullmatch(name):
            raise ValueError("Only internally generated technical indicator names are allowed")

    def _raise_execution_error(self, exc: Exception) -> None:
        # A recorded stop has priority over the interrupted call's database exception.
        self.control.check_active()
        if isinstance(exc, TechnicalIndicatorError):
            raise exc
        from duckdb import OutOfMemoryException

        if isinstance(exc, OutOfMemoryException):
            raise ResourceLimitError("DuckDB query memory limit was exceeded") from exc
        raise CalculationExecutionError("DuckDB operation failed") from exc

    def declare_table(self, name: str) -> None:
        """Remember ownership before source preparation or cancellation checks.

        Declaration does not mean the driver has started creating the table.
        An uncreated resource can be cleaned up without accepting foreign names.
        """
        self._assert_owner()
        self._validate_name(name)
        if name in self._live_arrow:
            raise ValueError("A SQL table cannot replace an active Arrow registration")
        self._known_tables.add(name)

    def execute(self, step: SqlStep) -> ExecutionStats:
        return self._execute_step(step)

    def rename_table(
        self, old_name: str, new_name: str, *, processed_rows: int,
    ) -> ExecutionStats:
        """Rename an owned table and retire its old name before checking stop.

        If the driver raises, both names remain eligible for IF EXISTS cleanup:
        the statement may have failed before or after the database renamed it.
        """
        self._assert_owner()
        self._validate_name(old_name)
        self._validate_name(new_name)
        if old_name == new_name or old_name not in self._live_tables:
            raise ValueError("Rename requires a live owned table and a different target name")
        if new_name in self._live_tables or new_name in self._live_arrow:
            raise ValueError("Rename target is already an active resource")
        return self._execute_step(SqlStep(
            "rename_table", f'ALTER TABLE "{old_name}" RENAME TO "{new_name}"',
            (), (old_name,), (new_name,), processed_rows,
        ), renamed_from=old_name)

    def _execute_step(
        self, step: SqlStep, *, renamed_from: str | None = None,
    ) -> ExecutionStats:
        self._assert_owner()
        if not isinstance(step, SqlStep) or type(step.processed_rows) is not int or step.processed_rows < 0:
            raise ValueError("SQL steps require a nonnegative logical row count")
        for name in (*step.input_tables, *step.output_tables):
            self._validate_name(name)
        if any(name in self._live_arrow for name in step.output_tables):
            raise ValueError("A SQL table cannot replace an active Arrow registration")
        for name in step.output_tables:
            self.declare_table(name)
        self.control.check_active()
        started_at = self.control.clock()
        output_rows = 0
        failed = True
        self._executing = True
        try:
            try:
                self._live_tables.update(step.output_tables)
                cursor = self.connection.execute(step.sql, step.bindings)
                if renamed_from is not None:
                    # The native call succeeded. Match the actual name before
                    # any later cancellation can interrupt the handoff.
                    self._live_tables.remove(renamed_from)
                description = cursor.description
                if description and len(description) == 1 and description[0][0] == "Count":
                    count = cursor.fetchone()
                    if count is not None and type(count[0]) is int:
                        output_rows = count[0]
            finally:
                self.control._note_sql_returned()
            self.control.check_active()
            failed = False
        except Exception as exc:
            self._raise_execution_error(exc)
        finally:
            self._executing = False
            stats = ExecutionStats(
                step.name, (self.control.clock() - started_at) * 1000,
                step.processed_rows, output_rows, failed,
            )
            self._statistics.append(stats)
        return stats

    def scalar(self, sql: str, bindings=()):
        self._assert_owner()
        self.control.check_active()
        self._executing = True
        try:
            try:
                cursor = self.connection.execute(sql, bindings)
                if not cursor.description or len(cursor.description) != 1:
                    raise ValueError("The internal scalar query must return exactly one column")
                row = cursor.fetchone()
            finally:
                self.control._note_sql_returned()
            self.control.check_active()
            return None if row is None else row[0]
        except Exception as exc:
            self._raise_execution_error(exc)
        finally:
            self._executing = False

    def read_control_row(self, step: SqlStep, *, expected_columns):
        """Read one fixed smoothing-control row, never indicator values."""
        self._assert_owner()
        if step.name not in ("read_smoothing_limits", "read_segment_bounds", "read_warmup_rows"):
            raise CalculationExecutionError("Unknown calculation control query")
        if step.output_tables or type(step.processed_rows) is not int or step.processed_rows < 0:
            raise CalculationExecutionError("Control queries must be read-only and counted")
        for name in step.input_tables:
            self._validate_name(name)
        self.control.check_active()
        started_at = self.control.clock()
        failed, row_count, phase = True, 0, "control_query_failed"
        self._executing = True
        try:
            cursor = self.connection.execute(step.sql, step.bindings)
            actual = tuple((column[0], str(column[1])) for column in (cursor.description or ()))
            if actual != tuple(expected_columns):
                error = CalculationExecutionError("Control query columns do not match its fixed contract")
                error.reason, error.step_name = "control_columns", step.name
                raise error
            phase = "control_fetch_failed"
            self.control.check_active()
            row = cursor.fetchone()
            self.control.check_active()
            row_count = int(row is not None)
            extra = cursor.fetchone()
            self.control.check_active()
            row_count += int(extra is not None)
            if row is None or extra is not None:
                error = CalculationExecutionError("Control query must return exactly one row")
                error.reason, error.step_name = "control_row_count", step.name
                raise error
            failed = False
            return tuple(row)
        except Exception as exc:
            self.control.check_active()
            if isinstance(exc, TechnicalIndicatorError):
                raise
            from duckdb import OutOfMemoryException
            if isinstance(exc, OutOfMemoryException):
                raise ResourceLimitError("DuckDB query memory limit was exceeded") from exc
            error = CalculationExecutionError("Calculation control query or fetch failed")
            error.reason, error.step_name = phase, step.name
            raise error from exc
        finally:
            self.control._note_sql_returned()
            self._executing = False
            self._statistics.append(ExecutionStats(
                step.name, (self.control.clock() - started_at) * 1000,
                step.processed_rows, row_count, failed,
            ))

    def read_result(self, step: SqlStep, *, expected_columns, max_rows: int):
        """Fully fetch a fixed collector query without exposing a live cursor."""
        self._assert_owner()
        stages = {"inspect_columns": "inspect", "check_batch_rows": "append",
                  "count_tail": "final_query", "select_result": "final_query"}
        if step.name not in stages or step.output_tables:
            raise ValueError("Only fixed read-only output steps are supported")
        if type(max_rows) is not int or max_rows < 0:
            raise ValueError("Output read limit must be a nonnegative integer")
        if type(step.processed_rows) is not int or step.processed_rows < 0:
            raise ValueError("Output steps require a nonnegative logical row count")
        for name in step.input_tables:
            self._validate_name(name)
        self.control.check_active()
        started_at = self.control.clock()
        rows, actual_count, failed = [], 0, True
        stage, reason = stages[step.name], "query_failed"
        self._executing = True
        try:
            cursor = self.connection.execute(step.sql, step.bindings)
            actual = tuple((column[0], str(column[1])) for column in (cursor.description or ()))
            expected = tuple(expected_columns)
            actual_names = tuple(name for name, _ in actual)
            expected_names = tuple(name for name, _ in expected)
            if actual != expected:
                field_reason = ("missing_fields" if set(expected_names) - set(actual_names)
                                else "unexpected_fields" if actual_names != expected_names
                                else "type_mismatch")
                raise OutputContractError(
                    "Output query columns do not match their fixed contract",
                    reason=field_reason, stage=stage,
                    expected_fields=expected, actual_fields=actual,
                )
            reason = "fetch_failed"
            if step.name == "select_result":
                stage = "final_fetch"
            while True:
                self.control.check_active()
                batch = cursor.fetchmany(8192)
                self.control.check_active()
                if not batch:
                    break
                actual_count += len(batch)
                if actual_count > max_rows:
                    raise OutputContractError(
                        "Output fetch exceeded its declared result limit",
                        reason="fetch_count_mismatch", stage=stage,
                        expected_count=max_rows, actual_count=actual_count,
                    )
                if any(len(row) != len(expected) for row in batch):
                    raise OutputContractError(
                        "Output rows have incomplete fields", reason="missing_fields", stage=stage,
                    )
                rows.extend(tuple(row) for row in batch)
            failed = False
            return tuple(rows)
        except Exception as exc:
            self.control.check_active()
            if isinstance(exc, TechnicalIndicatorError):
                raise
            from duckdb import OutOfMemoryException
            if isinstance(exc, OutOfMemoryException):
                raise ResourceLimitError("DuckDB query memory limit was exceeded") from exc
            raise OutputReadError(
                "Output query or result fetch failed", reason=reason,
                stage=stage, step_name=step.name,
            ) from exc
        finally:
            self.control._note_sql_returned()
            self._executing = False
            self._statistics.append(ExecutionStats(
                step.name, (self.control.clock() - started_at) * 1000,
                step.processed_rows, actual_count, failed,
            ))

    def register_arrow(self, name: str, batch) -> None:
        self._assert_owner()
        self._validate_name(name)
        if name in self._live_arrow or name in self._live_tables:
            raise ValueError("An active resource already uses this internal name")
        self._known_arrow.add(name)
        self.control.check_active()
        self._executing = True
        try:
            self._live_arrow.add(name)
            self.connection.register(name, batch)
            self.control.check_active()
        except Exception as exc:
            self._raise_execution_error(exc)
        finally:
            self._executing = False

    def _release(self, name: str, *, arrow: bool, cleanup: bool) -> None:
        self._assert_owner()
        self._validate_name(name)
        known = self._known_arrow if arrow else self._known_tables
        live = self._live_arrow if arrow else self._live_tables
        if name not in known:
            raise ValueError("Cleanup requires a resource registered by this executor")
        if cleanup:
            if not self.control.cleanup_ready:
                raise RuntimeError("Cleanup must wait for interrupt monitoring to stop")
        else:
            self.control.check_active()
        if name not in live:
            return
        self._executing = True
        try:
            if arrow:
                self.connection.unregister(name)
            else:
                self.connection.execute(f'DROP TABLE IF EXISTS "{name}"')
            live.remove(name)
            if not cleanup:
                self.control.check_active()
        except Exception as exc:
            if cleanup:
                raise
            self._raise_execution_error(exc)
        finally:
            self._executing = False

    def drop_table(self, name: str) -> None:
        self._release(name, arrow=False, cleanup=False)

    def unregister_arrow(self, name: str) -> None:
        self._release(name, arrow=True, cleanup=False)

    def cleanup_drop(self, name: str) -> None:
        self._release(name, arrow=False, cleanup=True)

    def cleanup_unregister(self, name: str) -> None:
        self._release(name, arrow=True, cleanup=True)
