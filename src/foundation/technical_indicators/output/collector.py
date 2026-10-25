"""Check generated rows and retain only this request's selected result tail."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import re
from types import MappingProxyType

from ..calculation.calculation import BatchCalculationOutputs, CalculationOutput, SqlStep
from ..calculation.sql_templates import load_sql_templates, render_sql
from ..contracts import CalculationRequest, CalculationResult, CalculationStatistics, TimePosition
from ..errors import CalculationExecutionError, OutputContractError, ResourceCleanupError
from ..executor import DuckDBExecutor
from ..sources.contracts import PriceBatch, SourceDescription
from .contracts import OutputInstanceDescription
from .result import build_calculation_result


_COLUMN = re.compile(r"[a-z][a-z0-9_]*\Z")
_VALUE_FIELDS = frozenset({"open", "high", "low", "close", "volume", "amount"})
_OUTPUT_PACKAGE = "src.foundation.technical_indicators.output"
_INSPECT_SQL = "SELECT name,type FROM pragma_table_info(?) ORDER BY cid"
_CHECK_ROWS_SQL = """SELECT
 COUNT(*) FILTER (WHERE seq BETWEEN ? AND ?) AS new_rows,
 COUNT(DISTINCT seq) FILTER (WHERE seq BETWEEN ? AND ?) AS distinct_new_rows,
 MIN(seq) FILTER (WHERE seq BETWEEN ? AND ?) AS first_seq,
 MAX(seq) FILTER (WHERE seq BETWEEN ? AND ?) AS last_seq,
 COUNT(*) FILTER (WHERE seq IS NULL OR seq > ? OR (? AND seq < ?)) AS unexpected_rows
 FROM {{result_table}}"""
_COUNT_SQL = "SELECT COUNT(*) AS row_count FROM {{tail}}"
_CHECK_COLUMNS = tuple((name, "BIGINT") for name in (
    "new_rows", "distinct_new_rows", "first_seq", "last_seq", "unexpected_rows",
))


def _column(name: str) -> str:
    """Only verified internal field names enter a fixed projection."""
    if not isinstance(name, str) or _COLUMN.fullmatch(name) is None:
        raise OutputContractError(
            "An output column is not a declared internal identifier",
            reason="unexpected_fields", stage="inspect", actual_fields=(name,),
        )
    return f'"{name}"'


class OutputCollector:
    SQL_PACKAGE = _OUTPUT_PACKAGE
    SQL_FILES = ("merge_batch.sql", "retain_tail.sql", "select_result.sql")
    FIXED_SQL_STEPS = MappingProxyType({
        "inspect_columns": _INSPECT_SQL,
        "check_batch_rows": _CHECK_ROWS_SQL,
        "count_tail": _COUNT_SQL,
    })
    TABLE_ROLES = ("ti_output_batch", "ti_output_tail", "ti_output_tail_next")

    def __init__(
        self, *, executor: DuckDBExecutor, request: CalculationRequest,
        instances: tuple[OutputInstanceDescription, ...],
    ):
        self.executor = executor
        self.request = request
        self.instances = tuple(instances)
        self._tables: list[str] = []
        self._template_texts: dict[tuple[str, str], str] = {}
        self._templates = MappingProxyType({})
        self._tail_rows = 0
        self._last_seq: int | None = None
        self._failed = self._discarded = self._built = False
        self._time_fields = (("trade_date", "trade_time") if request.period.endswith("m")
                             else ("trade_date", "period_start", "period_end", "source_as_of"))
        self._value_columns = tuple(
            tuple(f"value_{i}_{j}" for j, _ in enumerate(item.fields))
            for i, item in enumerate(self.instances)
        )
        self._columns = ("seq", *self._time_fields,
                         *(name for aliases in self._value_columns for name in aliases))
        self._expected_columns = (
            ("seq", "BIGINT"),
            *((name, "TIMESTAMP" if name == "trade_time" else "DATE") for name in self._time_fields),
            *((name, "DOUBLE") for aliases in self._value_columns for name in aliases),
        )
        try:
            self._check_descriptions()
            if type(self).SQL_PACKAGE != _OUTPUT_PACKAGE:
                raise CalculationExecutionError("The output collector only loads its fixed output package")
            self._templates = load_sql_templates(
                type(self), request_texts=self._template_texts, control=executor.control,
            )
        except BaseException:
            # The service has no collector yet if construction itself fails.
            self._templates = MappingProxyType({})
            self._template_texts.clear()
            raise

    def _check_descriptions(self) -> None:
        expected = tuple((item.instance_id, item.calculation_id) for item in self.request.calculations)
        actual = tuple((item.instance_id, item.calculation_id) for item in self.instances)
        identities = tuple(identity for identity, _ in actual)
        if len(set(identities)) != len(identities):
            self._contract("duplicate_instance", "append", "Output descriptions repeat a requested item")
        if expected != actual:
            reason = "missing_instance" if set(expected) - set(actual) else "unexpected_instance"
            self._contract(reason, "append", "Output descriptions do not match this request",
                           expected_ids=tuple(item[0] for item in expected), actual_ids=identities)
        for item in self.instances:
            names = tuple(field.name for field in item.fields)
            if not names or len(names) != len(set(names)):
                self._contract("missing_fields", "append", "Output fields must be declared exactly once",
                               instance_id=item.instance_id, actual_fields=names)
            for field in item.fields:
                _column(field.name)
                if field.sql_type != "DOUBLE":
                    self._contract("type_mismatch", "append", "Numerical output fields require DOUBLE",
                                   instance_id=item.instance_id, actual_fields=(field.sql_type,))

    @staticmethod
    def _contract(reason: str, stage: str, message: str, **diagnostics):
        raise OutputContractError(message, reason=reason, stage=stage, **diagnostics)

    def _assert_open(self) -> None:
        if self._failed or self._discarded or self._built:
            raise CalculationExecutionError("Output collection cannot continue after failure, result or discard")
        self.executor.control.check_active()

    def _own_table(self, name: str) -> None:
        if name not in self.TABLE_ROLES:
            raise CalculationExecutionError("Output cannot own an input or indicator table")
        if name not in self._tables:
            self.executor.declare_table(name)
            self._tables.append(name)

    def _drop(self, name: str) -> None:
        if name not in self._tables:
            raise CalculationExecutionError("Output cannot delete a borrowed or undeclared table")
        self.executor.drop_table(name)
        self._tables.remove(name)

    def _template(self, name: str, *, tables: dict[str, str], fragments=None) -> str:
        if name not in self.SQL_FILES:
            raise CalculationExecutionError("Output attempted an undeclared SQL file")
        text = self._templates[name]
        # Fragments are generated solely by the fixed projection/join/range
        # methods below. Business strings, IDs and expressions never enter them.
        allowed = {
            "merge_batch.sql": frozenset({"projection", "joins"}),
            "retain_tail.sql": frozenset({"columns", "range", "previous"}),
            "select_result.sql": frozenset({"columns"}),
        }[name]
        supplied = fragments or {}
        if set(supplied) != allowed:
            raise CalculationExecutionError("Output SQL fragments do not match the fixed template")
        for key, value in supplied.items():
            marker = "/* " + key + " */"
            if marker not in text:
                raise CalculationExecutionError("A fixed output SQL marker is missing")
            text = text.replace(marker, value)
        return render_sql(text, tables=tables)

    def _read(self, name, sql, bindings, inputs, processed_rows, *, expected, maximum):
        if name not in self.FIXED_SQL_STEPS and name != "select_result":
            raise CalculationExecutionError("Output attempted an undeclared result query")
        return self.executor.read_result(
            SqlStep(name, sql, bindings, inputs, (), processed_rows),
            expected_columns=expected, max_rows=maximum,
        )

    def _check_batch(self, outputs: BatchCalculationOutputs):
        batch = outputs.price_batch
        if (batch.time_fields != self._time_fields or not set(batch.fields) <= _VALUE_FIELDS
                or len(set(batch.fields)) != len(batch.fields)):
            self._contract("unexpected_fields", "append", "The price batch has different time or value fields")
        if (any(type(value) is not int for value in (
            batch.new_first_seq, batch.new_last_seq, batch.new_row_count, batch.history_rows,
        )) or batch.new_row_count <= 0 or batch.history_rows < 0
                or batch.new_last_seq - batch.new_first_seq + 1 != batch.new_row_count
                or (self._last_seq is not None and batch.new_first_seq != self._last_seq + 1)):
            self._contract("wrong_batch", "append", "The new price range does not match this output batch")
        received = {}
        for identity, output in outputs.instances:
            if identity in received:
                self._contract("duplicate_instance", "append", "This batch repeats a requested item",
                               instance_id=identity)
            received[identity] = output
        expected = tuple(item.instance_id for item in self.instances)
        missing = tuple(identity for identity in expected if identity not in received)
        if missing:
            self._contract("missing_instance", "append", "This batch omits a requested item",
                           instance_id=missing[0], expected_ids=expected, actual_ids=tuple(received))
        unexpected = tuple(identity for identity in received if identity not in expected)
        if unexpected:
            self._contract("unexpected_instance", "append", "This batch contains an unrequested item",
                           instance_id=unexpected[0], expected_ids=expected, actual_ids=tuple(received))
        checked = set()
        for item in self.instances:
            output = received[item.instance_id]
            fields = tuple((field.name, field.sql_type, field.nullable, field.initialization_rule)
                           for field in output.fields)
            wanted = tuple((field.name, field.sql_type, field.nullable, field.initialization_rule)
                           for field in item.fields)
            if fields != wanted:
                reason = ("missing_fields" if set(field[0] for field in wanted) - set(field[0] for field in fields)
                          else "type_mismatch" if tuple(field[0] for field in fields) == tuple(field[0] for field in wanted)
                          else "unexpected_fields")
                self._contract(reason, "append", "This item's fields differ from its output description",
                               instance_id=item.instance_id, expected_fields=wanted, actual_fields=fields)
            if (output.sequence_field != "seq" or output.new_first_seq != batch.new_first_seq
                    or output.new_last_seq != batch.new_last_seq):
                self._contract("wrong_batch", "append", "An indicator returned a different price range",
                               instance_id=item.instance_id)
            key = (output.table_name, output.fields)
            if key not in checked:
                self._inspect_output(output, batch, item.instance_id)
                checked.add(key)
        return batch, received

    def _inspect_output(self, output: CalculationOutput, batch: PriceBatch, identity: str) -> None:
        columns = tuple(field.column_name for field in output.fields)
        for name in columns:
            _column(name)
        if len(columns) != len(set(columns)):
            self._contract("unexpected_fields", "inspect", "Two output fields use the same internal column",
                           instance_id=identity, actual_fields=columns)
        borrowed_price = output.table_name == batch.table_name
        expected = (("seq", "BIGINT"),
                    *((name, "TIMESTAMP" if name == "trade_time" else "DATE") for name in batch.time_fields),
                    *((name, "DOUBLE") for name in batch.fields)) if borrowed_price else (
                        ("seq", "BIGINT"), *((name, "DOUBLE") for name in columns),
                    )
        metadata = self._read(
            "inspect_columns", _INSPECT_SQL, (output.table_name,), (output.table_name,), len(expected),
            expected=(("name", "VARCHAR"), ("type", "VARCHAR")), maximum=len(expected),
        )
        actual = tuple(metadata)
        if actual != expected:
            actual_names = tuple(row[0] for row in actual)
            wanted_names = tuple(row[0] for row in expected)
            reason = ("missing_fields" if set(wanted_names) - set(actual_names)
                      else "unexpected_fields" if actual_names != wanted_names else "type_mismatch")
            self._contract(reason, "inspect", "The indicator table does not match its declared columns",
                           instance_id=identity, expected_fields=expected, actual_fields=actual)
        if borrowed_price and not set(columns) <= set(batch.fields):
            self._contract("missing_fields", "inspect", "The borrowed price table lacks a requested value",
                           instance_id=identity, expected_fields=columns, actual_fields=batch.fields)
        first, last = batch.new_first_seq, batch.new_last_seq
        summary = self._read(
            "check_batch_rows", render_sql(_CHECK_ROWS_SQL, tables={"result_table": output.table_name}),
            (first, last) * 4 + (last, not borrowed_price, first), (output.table_name,),
            batch.new_row_count + (batch.history_rows if borrowed_price else 0),
            expected=_CHECK_COLUMNS, maximum=1,
        )
        if len(summary) != 1:
            self._contract("missing_rows", "append", "The indicator row check did not return its summary",
                           instance_id=identity)
        count, distinct, actual_first, actual_last, outside = summary[0]
        if any(type(value) is not int for value in (count, distinct, outside)):
            self._contract("type_mismatch", "append", "The indicator row summary has invalid counts",
                           instance_id=identity)
        reason = ("duplicate_rows" if distinct != count else "missing_rows" if count < batch.new_row_count
                  else "unexpected_rows" if count > batch.new_row_count or outside != 0
                  else "wrong_batch" if (actual_first, actual_last) != (first, last) else None)
        if reason:
            self._contract(reason, "append", "The indicator did not return exactly the new price rows",
                           instance_id=identity, expected_count=batch.new_row_count, actual_count=count,
                           distinct_count=distinct, unexpected_count=outside,
                           expected_range=(first, last), actual_range=(actual_first, actual_last))

    def _merge(self, batch: PriceBatch, received) -> None:
        tables = {"price": batch.table_name, "output": "ti_output_batch"}
        projection = [f"p.{_column(name)}" for name in ("seq", *self._time_fields)]
        joins, joined = [], {}
        for item, aliases in zip(self.instances, self._value_columns):
            output = received[item.instance_id]
            if output.table_name == batch.table_name:
                alias = "p"
            else:
                if output.table_name not in joined:
                    index = len(joined)
                    alias = f"r{index}"
                    role = f"result_{index}"
                    joined[output.table_name] = alias
                    tables[role] = output.table_name
                    joins.append("LEFT JOIN {{" + role + "}} AS " + alias + " ON p.seq=" + alias + ".seq")
                alias = joined[output.table_name]
            projection.extend(f"{alias}.{_column(field.column_name)} AS {_column(name)}"
                              for field, name in zip(output.fields, aliases))
        self._own_table("ti_output_batch")
        stats = self.executor.execute(SqlStep(
            "merge_batch", self._template("merge_batch.sql", tables=tables,
                                          fragments={"projection": ", ".join(projection), "joins": "\n".join(joins)}),
            (batch.new_first_seq, batch.new_last_seq),
            (batch.table_name, *joined), ("ti_output_batch",),
            batch.new_row_count + batch.history_rows + len(joined) * batch.new_row_count,
        ))
        if stats.output_rows != batch.new_row_count:
            self._contract("missing_rows" if stats.output_rows < batch.new_row_count else "unexpected_rows",
                           "merge", "Merging indicators changed the number of new price rows",
                           expected_count=batch.new_row_count, actual_count=stats.output_rows)

    def _range_filter(self):
        minute = self.request.period.endswith("m")
        time_key = "trade_time" if minute else "period_start"
        terms, bindings = [], []
        for value, column, operator in (
            (self.request.start, "period_end" if self.request.period in ("week", "month") else time_key, ">="),
            (self.request.end, time_key, "<="),
            (self.request.before, time_key, "<"),
        ):
            if value is not None:
                # Input SQL uses local TIMESTAMP, never the host's timezone.
                if minute and isinstance(value, datetime):
                    value = value.replace(tzinfo=None)
                terms.append(_column(column) + " " + operator + " ?")
                bindings.append(value)
        return " AND ".join(terms) or "TRUE", tuple(bindings)

    def _retain(self, batch: PriceBatch) -> None:
        columns = ", ".join(_column(name) for name in self._columns)
        selection, bindings = self._range_filter()
        had_tail = "ti_output_tail" in self._tables
        tables = {"next": "ti_output_tail_next", "batch": "ti_output_batch"}
        previous = ""
        inputs = ("ti_output_batch",)
        if had_tail:
            tables["tail"] = "ti_output_tail"
            previous = "SELECT " + columns + " FROM {{tail}} UNION ALL"
            inputs += ("ti_output_tail",)
        self._own_table("ti_output_tail_next")
        stats = self.executor.execute(SqlStep(
            "retain_tail", self._template("retain_tail.sql", tables=tables,
                                          fragments={"columns": columns, "range": selection, "previous": previous}),
            bindings + (self.request.limit,), inputs, ("ti_output_tail_next",),
            batch.new_row_count + self._tail_rows,
        ))
        if not 0 <= stats.output_rows <= min(self.request.limit, batch.new_row_count + self._tail_rows):
            self._contract("unexpected_rows", "merge", "Retaining output exceeded the requested limit",
                           expected_count=self.request.limit, actual_count=stats.output_rows)
        if had_tail:
            self._drop("ti_output_tail")
        self._own_table("ti_output_tail")
        self.executor.rename_table("ti_output_tail_next", "ti_output_tail", processed_rows=stats.output_rows)
        self._tables.remove("ti_output_tail_next")
        self._tail_rows = stats.output_rows
        self._drop("ti_output_batch")

    def append_new_rows(self, batch_outputs: BatchCalculationOutputs) -> None:
        self._assert_open()
        try:
            batch, received = self._check_batch(batch_outputs)
            self._merge(batch, received)
            self._retain(batch)
            self._last_seq = batch.new_last_seq
        except BaseException:
            self._failed = True
            raise

    def build_result(
        self, description: SourceDescription, statistics: CalculationStatistics,
        *, read_start: TimePosition | None, read_end: TimePosition | None,
    ) -> CalculationResult:
        self._assert_open()
        try:
            rows = ()
            if "ti_output_tail" in self._tables:
                counts = self._read(
                    "count_tail", render_sql(_COUNT_SQL, tables={"tail": "ti_output_tail"}),
                    (), ("ti_output_tail",), self._tail_rows,
                    expected=(("row_count", "BIGINT"),), maximum=1,
                )
                if len(counts) != 1 or type(counts[0][0]) is not int or counts[0][0] != self._tail_rows:
                    self._contract("fetch_count_mismatch", "final_query", "The final output count changed",
                                   expected_count=self._tail_rows, actual_count=counts)
                rows = self._read(
                    "select_result", self._template("select_result.sql", tables={"tail": "ti_output_tail"},
                                                    fragments={"columns": ", ".join(_column(name) for name in self._columns)}),
                    (), ("ti_output_tail",), self._tail_rows,
                    expected=self._expected_columns, maximum=self.request.limit,
                )
                if len(rows) != counts[0][0]:
                    self._contract("fetch_count_mismatch", "final_fetch", "The final fetch omitted output rows",
                                   expected_count=counts[0][0], actual_count=len(rows))
            final_statistics = replace(
                statistics, sql_processed_rows=self.executor.sql_processed_rows,
                elapsed_ms=(self.executor.control.clock() - self.executor.control.arrived_at) * 1000,
            )
            result = build_calculation_result(
                request=self.request, instances=self.instances, description=description,
                statistics=final_statistics, rows=rows, columns=self._columns,
                value_columns=self._value_columns, read_start=read_start, read_end=read_end,
            )
            self.executor.control.check_active()
            self._built = True
            return result
        except BaseException:
            self._failed = True
            raise

    def discard(self) -> None:
        """Clean only owned tables after the service stops interrupt monitoring."""
        errors = []
        try:
            for name in tuple(reversed(self._tables)):
                try:
                    self.executor.cleanup_drop(name)
                    self._tables.remove(name)
                except BaseException as exc:
                    errors.append(exc)
            self._discarded = True
        finally:
            self._templates = MappingProxyType({})
            self._template_texts.clear()
        if errors:
            error = ResourceCleanupError("Output resources could not all be released")
            for exc in errors:
                error.add_note(f"{type(exc).__name__}: {exc}")
            raise error from errors[0]
