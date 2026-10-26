"""Own the current shared input and its retained history, never indicator state."""

from pathlib import Path

from ..calculation.calculation import SqlStep
from ..errors import ResourceCleanupError, ResourceLimitError, SourceContractError, SourceUnsupportedError
from ..time_range import check_period_cutoff
from .contracts import PriceBatch, SourceDescription
from .price_adjustment import PriceAdjustmentCalculation, VALUE_FIELDS

_SQL = Path(__file__).parent / "sql"
_FIELD_ORDER = ("open", "high", "low", "close", "volume", "amount")


class PriceInputSession:
    def __init__(self, executor, source, requirement, *, read_context):
        self.executor = executor
        self.source = source
        self.description = None
        self.requirement = requirement
        self.read_context = read_context
        self._resolved = None
        self._stream = None
        self._locator = None
        self._tables: list[str] = []
        self._registrations: list[str] = []
        self._prepared = self._closed = self._failed = self._exhausted = False
        self._batch = None
        self._retained = False
        self._rows = 0
        self._history_rows = 0
        self.read_start = self.read_end = None
        self.conversion_batches = 0
        fields = requirement.history.fields
        if not fields <= VALUE_FIELDS:
            raise SourceContractError("Unknown standard input fields")
        self.fields = tuple(name for name in _FIELD_ORDER if name in fields)
        self.time_fields = (("trade_date", "trade_time") if requirement.request.period.endswith("m")
                            else ("trade_date", "period_start", "period_end", "source_as_of"))
        self.time_key = "trade_time" if requirement.request.period.endswith("m") else "period_start"

    def prepare(self):
        if self._prepared or self._closed or self._failed:
            raise RuntimeError("Input session cannot be prepared in this state")
        self.executor.control.check_active()
        request = self.requirement.request
        try:
            self._locator = self.source.create_locator(
                self.executor, self.requirement, read_context=self.read_context)
            self.description = self._locator.describe()
            if not isinstance(self.description, SourceDescription):
                raise SourceContractError("Source must return the declared source description")
            self._validate_selection()
            path = (self.description.input_adjustment, request.adjustment)
            if path not in self.description.supported_adjustment_paths:
                raise SourceUnsupportedError("Source does not support the requested adjustment")
            projected = {name for name, _ in self.description.standard_projection}
            if projected != set(self.fields) | set(self.time_fields):
                raise SourceContractError("Source projection does not match the required standard fields")
            self._locator.close()
            self._locator = None
            resolved = self.description
            if self.description.selection.target_rows and path[0] != path[1]:
                self._own_table("ti_anchor")
                resolved = self.source.prepare_basis(self.executor, self.description, self.requirement,
                    table_name="ti_anchor", read_context=self.read_context)
                if resolved.basis_date is None or resolved.basis_value is None:
                    raise SourceContractError("Converted daily prices require an actual basis")
            if self.description.selection.target_rows:
                self._stream = self.source.open(self.executor, resolved, self.requirement,
                                               read_context=self.read_context)
            else:
                self._exhausted = True
            self.executor.control.check_active()
            self._resolved = resolved
            self._prepared = True
        except BaseException:
            self._failed = True
            raise

    def _validate_selection(self):
        selection = self.description.selection
        history = self.requirement.history
        request = self.requirement.request
        if selection.target_rows > request.limit:
            raise SourceContractError("Selection exceeds the requested output count")
        if selection.target_rows + selection.preceding_rows > self.executor.control.config.max_input_rows:
            raise ResourceLimitError("Selected input exceeds max_input_rows")
        if selection.target_rows:
            if not selection.reached_source_origin and (
                history.requires_source_origin or selection.preceding_rows < history.warmup_rows
            ):
                raise ResourceLimitError("Selected input cannot satisfy the required warmup")
            for stamp in (selection.target_start, selection.target_end, selection.read_start, selection.read_end):
                from datetime import date, datetime
                from zoneinfo import ZoneInfo
                minute = request.period.endswith("m")
                if (minute and (not isinstance(stamp, datetime) or stamp.tzinfo is None
                        or stamp.utcoffset() != stamp.astimezone(ZoneInfo("Asia/Shanghai")).utcoffset())
                        or not minute and type(stamp) is not date):
                    raise SourceContractError("Selected time positions do not match the period")

    def _check_delivered_count(self):
        selection = self.description.selection
        expected = selection.target_rows + selection.preceding_rows
        if self._rows != expected:
            error = SourceContractError("Price delivery differs from the selected input count")
            error.reason = "selection_count_mismatch"
            error.expected_count, error.actual_count = expected, self._rows
            raise error

    def resolved_description(self):
        if not self._prepared:
            raise RuntimeError("Input preparation has not completed")
        return self._resolved

    def _own_table(self, name):
        if name not in self._tables:
            self.executor.declare_table(name)
            self._tables.append(name)

    def _execute(self, name, sql, inputs, output, rows, bindings=()):
        self._own_table(output)
        return self.executor.execute(SqlStep(name, sql, bindings, tuple(inputs), (output,), rows))

    def _drop(self, name):
        if name in self._tables:
            self.executor.drop_table(name)
            self._tables.remove(name)

    def next_batch(self):
        if not self._prepared or self._closed or self._failed:
            raise RuntimeError("Input session is not available")
        if self._batch is not None:
            raise RuntimeError("finish_batch must precede the next read")
        if self._exhausted:
            return None
        self.executor.control.check_active()
        try:
            batch = self._stream.next_batch(self.requirement.batch_rows)
            if batch is None:
                self._check_delivered_count()
                self._exhausted = True
                return None
            # A conforming SourceStream skips empty Arrow batches; a source
            # violating that handoff cannot be mistaken for normal end of input.
            if batch.selected_rows <= 0:
                raise SourceContractError("SourceStream must deliver a nonempty batch or EOF")
            registration = "ti_source_batch"
            self._registrations.append(registration)
            self.executor.register_arrow(registration, batch.columns)
            projection = ", ".join(f'{expression} AS "{name}"'
                for name, expression in self.description.standard_projection)
            sql = (_SQL / "stage_input.sql").read_text().format(output_table="ti_raw_new",
                time_key=self.time_key, projection=projection, registration=registration)
            self._execute("stage_input", sql, (registration,), "ti_raw_new",
                          batch.selected_rows, (self._rows,))
            self.executor.unregister_arrow(registration)
            self._registrations.remove(registration)
            self._stream.release_current_batch()
            del batch
            check_period_cutoff(self.executor, "ti_raw_new", self.requirement.request)
            metadata = self.executor.scalar(
                f"SELECT struct_pack(n := count(*), first_time := min({self.time_key}), "
                f"last_time := max({self.time_key})) FROM ti_raw_new")
            new_rows = metadata["n"]
            if new_rows <= 0:
                raise SourceContractError("A delivered price batch must retain its time positions")
            self._rows += new_rows
            if self.read_start is None:
                self.read_start = metadata["first_time"]
            self.read_end = metadata["last_time"]
            converted = self.description.input_adjustment != self.requirement.request.adjustment
            if converted:
                dates = tuple(self.executor.scalar("SELECT list(DISTINCT trade_date) FROM ti_raw_new"))
                self._own_table("ti_day_factor")
                self.source.prepare_factors(self.executor, self._resolved, self.requirement,
                    dates, table_name="ti_day_factor", read_context=self.read_context)
                step = PriceAdjustmentCalculation().build_sql("ti_raw_new", "ti_day_factor", "ti_anchor",
                    output_table="ti_price_new", fields=self.fields, time_fields=self.time_fields,
                    processed_rows=new_rows)
                self._own_table("ti_price_new")
                self.executor.execute(step)
                self.conversion_batches += 1
                self._drop("ti_day_factor")
            else:
                self._execute("target_price", "CREATE TEMP TABLE ti_price_new AS SELECT * FROM ti_raw_new",
                              ("ti_raw_new",), "ti_price_new", new_rows)
            self._drop("ti_raw_new")
            if self._history_rows:
                sql = ("CREATE TEMP TABLE ti_price_window AS SELECT * FROM ti_history "
                       "UNION ALL SELECT * FROM ti_price_new ORDER BY seq")
                inputs = ("ti_history", "ti_price_new")
            else:
                sql = "CREATE TEMP TABLE ti_price_window AS SELECT * FROM ti_price_new ORDER BY seq"
                inputs = ("ti_price_new",)
            self._execute("input_window", sql, inputs, "ti_price_window", new_rows + self._history_rows)
            self._batch = PriceBatch("ti_price_window", self._rows-new_rows+1, self._rows,
                new_rows, self._history_rows, self.time_fields, self.fields, self.requirement.request.adjustment)
            self._retained = False
            return self._batch
        except BaseException:
            self._failed = True
            raise

    def retain_required_history(self):
        if self._batch is None or self._failed or self._closed or self._retained:
            raise RuntimeError("No unfinished input batch to retain")
        wanted = self.requirement.history.preceding_rows
        try:
            if wanted:
                sql = (_SQL / "retain_history.sql").read_text().format(
                    output_table="ti_history_next", input_table=self._batch.table_name)
                self._execute("retain_input_history", sql, (self._batch.table_name,),
                              "ti_history_next", self._batch.new_row_count+self._history_rows, (wanted,))
                self._drop("ti_history")
                # The owner remembers both names until the executor confirms
                # the rename; failures retain everything needed for cleanup.
                self._own_table("ti_history")
                self.executor.rename_table("ti_history_next", "ti_history",
                                           processed_rows=min(wanted, self._rows))
                self._tables.remove("ti_history_next")
        except BaseException:
            self._failed = True
            raise
        self._history_rows = min(wanted, self._rows)
        self._retained = True

    def finish_batch(self):
        if self._batch is None or self._closed or self._failed:
            raise RuntimeError("No unfinished input batch")
        if not self._retained and self.requirement.history.preceding_rows:
            raise RuntimeError("Required input history has not been saved")
        for name in ("ti_price_window", "ti_price_new"):
            self._drop(name)
        self._batch = None

    def close(self):
        if self._closed:
            return
        errors = []
        if self._locator is not None:
            try:
                self._locator.close()
                self._locator = None
            except BaseException as exc:
                errors.append(exc)
        for name in tuple(reversed(self._registrations)):
            try:
                self.executor.cleanup_unregister(name)
                self._registrations.remove(name)
            except BaseException as exc:
                errors.append(exc)
        if self._stream is not None:
            try:
                self._stream.close()
                self._stream = None
            except BaseException as exc:
                errors.append(exc)
        for name in tuple(reversed(self._tables)):
            try:
                self.executor.cleanup_drop(name)
                self._tables.remove(name)
            except BaseException as exc:
                errors.append(exc)
        self._batch = None
        self._closed = not errors
        if errors:
            error = ResourceCleanupError("Input resources could not all be released")
            for exc in errors:
                error.add_note(f"{type(exc).__name__}: {exc}")
            raise error from errors[0]
