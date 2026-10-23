"""Working-thread DuckDB operations; resource names are registered, not inferred."""

from __future__ import annotations

import re
import threading

from .calculation.calculation import ExecutionStats, SqlStep
from .errors import CalculationExecutionError, ResourceLimitError, TechnicalIndicatorError
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
