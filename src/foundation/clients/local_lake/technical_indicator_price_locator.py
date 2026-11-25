"""Locate bounded price ranges and retain selected DG price rows."""

from __future__ import annotations

from bisect import bisect_left
from collections import deque
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo

from goldenshare_technical_indicators.calculation.calculation import SqlStep
from goldenshare_technical_indicators.configuration.datasets import (
    DG_RECENT_INDEX_MINUTE_DATASETS, DG_RECENT_STOCK_MINUTE_DATASETS,
)
from goldenshare_technical_indicators.errors import (
    CalculationCancelledError, CalculationDeadlineError,
    ResourceCleanupError, ResourceLimitError, SourceContractError, SourceReadError,
    TechnicalIndicatorError,
)
from goldenshare_technical_indicators.sources.contracts import (
    CalendarDayFacts, PriceReadSelection, SourceDescription, SourceReadFacts, TargetBarFacts,
)
from goldenshare_technical_indicators.sources.price_adjustment import (
    validate_adjustment_basis, validate_adjustment_factors,
)
from goldenshare_technical_indicators.time_range import check_period_cutoff, range_filter

from ..technical_indicator_stock_daily import (
    DAILY_PRICE_FIELDS, daily_adjustment_paths, daily_price_projection, dg_index_daily_origin, scheduled_open_days,
)
from ..technical_indicator_index_minutes import (
    dg_recent_index_minute_sql, index_minute_projection, index_minute_volume_unit,
)
from ..technical_indicator_index_period import (
    INDEX_PERIOD_DATASETS, INDEX_PERIOD_KEYS, check_index_period_cutoff, check_period_key,
    describe_index_period, index_period_projection, period_bounds, period_request_start,
    preceding_limit, require_index_period,
)
from ..technical_indicator_stock_minutes import (
    STOCK_MINUTE_SELECTED_ROWS_SQL, adjusted_stock_minute_sql, stock_minute_selection_sql,
)
from ..technical_indicator_stock_period import STOCK_PERIOD_DATASETS, describe_stock_period, require_stock_period
from .major_index_mins_contract import EXPECTED_BARS_PER_SESSION
from .technical_indicator_contracts import DAILY_SCHEMA, PERIOD_SCHEMA
from .technical_indicator_price_source import _arrow, _file_version, _matches_type, _stock_batches


_INDEX_PERIOD_SCHEMA = (
    ("ts_code", "VARCHAR"), ("period_start_date", "DATE"), ("trade_date", "DATE"),
    *((column, "DECIMAL(18,4)") for column in ("open", "high", "low", "close")),
    ("vol", "DECIMAL(20,6)"), ("amount", "DECIMAL(20,7)"),
)


@dataclass(frozen=True, slots=True)
class _Group:
    path: Path
    index: int
    rows: int
    targets: int
    first: object
    last: object
    price_schema_error: str | None
    price_projected_bytes: int
    price_batch: object | None = None


class LakePriceLocator:
    """Own only current metadata/keys and the small selected file/group list."""

    FIXED_SQL_STEPS = MappingProxyType({
        "locate_count": "WITH eligible AS (SELECT * FROM ti_locator_times WHERE {upper}) "
            "SELECT struct_pack(n := count(*), targets := count(*) FILTER (WHERE {target}), "
            "distinct_positions := count(DISTINCT {time_key}), "
            "first_time := min({time_key}), last_time := max({time_key})) FROM eligible",
        "locate_bounds": "WITH eligible AS (SELECT row_number() OVER (ORDER BY {time_key}) AS rank, "
            "{time_key} AS position FROM ti_locator_times WHERE {upper}) "
            "SELECT struct_pack(first_time := min(position) FILTER (WHERE rank=?), "
            "second_time := min(position) FILTER (WHERE rank=?)) FROM eligible",
        "check_period_cutoff": "Existing time_range.check_period_cutoff",
    })

    def __init__(self, source, executor, requirement, *, read_context):
        # The caller must hold this object before describe opens anything.
        self.source, self.executor, self.requirement = source, executor, requirement
        self.context, self.control = read_context, executor.control
        self._root = None
        self._metadata_reader = self._reader = self._scanner = self._fragment = None
        self._tables, self._registrations = [], []
        self._stage_text = None
        self._closed = self._started = False
        self._defer_sql_cleanup = False

    def _position(self, value):
        if self.requirement.period.endswith("m") and isinstance(value, datetime):
            return value.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return value

    def _close_metadata(self):
        if self._metadata_reader is not None:
            try:
                self._metadata_reader.close()
            except Exception as exc:
                raise ResourceCleanupError("The price locator metadata handle did not close") from exc
            self._metadata_reader = None

    def _open_metadata(self, path, schema, projection, *, price_projection):
        pa, _, _, pq = _arrow()
        self.control.check_active()
        path = self.source._safe_path(self._root, path)
        self.context.record_file(path, path.stat().st_size)
        self._metadata_reader = pq.ParquetFile(path)
        expected = dict(schema)
        actual = self._metadata_reader.schema_arrow
        for name in projection:
            if (name not in actual.names or name not in expected
                    or not _matches_type(pa, actual.field(name).type, expected[name])):
                raise SourceContractError("The projected source schema does not match its declared contract")
        price_schema_error = None
        for name in price_projection:
            if name in projection:
                continue
            if (name not in actual.names or name not in expected
                    or not _matches_type(pa, actual.field(name).type, expected[name])):
                price_schema_error = f"The projected price field does not match its declared contract: {name}"
                break
        self.control.check_active()
        return self._metadata_reader.metadata, price_schema_error

    def _validate_selected_price_groups(self, groups: tuple[_Group, ...]) -> None:
        for group in groups:
            self.control.check_active()
            if group.price_schema_error is not None:
                raise SourceContractError(group.price_schema_error)
            if group.price_projected_bytes > self.source._config.max_projected_row_group_bytes:
                raise ResourceLimitError("Projected row group bytes exceed the initial protection")

    def _may_match(self, group, projection):
        """Use only reliable typed metadata; missing statistics require keys."""
        request = self.requirement
        for index in range(group.num_columns):
            column = group.column(index)
            if column.path_in_schema not in projection:
                continue
            stats = column.statistics
            if stats is None or not stats.has_min_max:
                continue
            if column.path_in_schema == "ts_code":
                if request.ts_code < stats.min or request.ts_code > stats.max:
                    return False
        return True

    def _check_group_bytes(self, group, projection):
        projected = sum(group.column(index).total_uncompressed_size
                        for index in range(group.num_columns)
                        if group.column(index).path_in_schema in projection)
        if projected > self.source._config.max_projected_row_group_bytes:
            raise ResourceLimitError("Projected row group bytes exceed the initial protection")

    def _close_key_reader(self):
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception as exc:
                raise ResourceCleanupError("The price locator key reader did not close") from exc
        self._reader = self._scanner = self._fragment = None

    def _key_batches(self, path, index, projection, standard):
        primary = None
        try:
            yield from self._read_key_batches(path, index, projection, standard)
        except GeneratorExit:
            raise
        except BaseException as error:
            primary = error
            self._defer_sql_cleanup = True
            raise
        finally:
            try:
                self._close_key_reader()
            except BaseException as error:
                if primary is not None:
                    primary.add_note(f"Locator key reader cleanup: {type(error).__name__}: {error}")
                else:
                    raise

    def _read_key_batches(self, path, index, projection, standard):
        import pyarrow.compute as pc

        _, ds, fs, _ = _arrow()
        request = self.requirement
        predicate = ds.field("ts_code") == request.ts_code
        partition_day = date.fromisoformat(path.parent.name.removeprefix("trade_date="))
        self.control.check_active()
        self._fragment = ds.ParquetFileFormat().make_fragment(
            str(path), filesystem=fs.LocalFileSystem(), row_groups=[index])
        self._scanner = ds.Scanner.from_fragment(
            self._fragment, columns=list(projection), filter=predicate,
            batch_size=self.requirement.batch_rows, batch_readahead=0, fragment_readahead=0,
            fragment_scan_options=ds.ParquetFragmentScanOptions(pre_buffer=False, use_buffered_stream=False),
            use_threads=False, cache_metadata=False)
        self._reader = self._scanner.to_reader()
        time_key = "period_start"
        expression = ", ".join(f'{sql} AS "{name}"' for name, sql in standard)
        text = self._stage_text.format(output_table="ti_locator_times", time_key=time_key,
                                       projection=expression, registration="ti_locator_keys")
        while True:
            self.control.check_active()
            try:
                batch = self._reader.read_next_batch()
            except StopIteration:
                break
            self.control.check_active()
            if not batch.num_rows:
                batch = None
                continue
            self.context.record_locator_rows(batch.num_rows)
            if not pc.all(pc.fill_null(
                    pc.equal(batch.column("trade_date"), partition_day), False)).as_py():
                raise SourceContractError("Source prices do not match their partition date")
            try:
                self._registrations.append("ti_locator_keys")
                self.executor.register_arrow("ti_locator_keys", batch)
                self.executor.declare_table("ti_locator_times")
                self._tables.append("ti_locator_times")
                self.executor.execute(SqlStep("locate_stage", text, (0,), ("ti_locator_keys",),
                                              ("ti_locator_times",), batch.num_rows))
                self.executor.unregister_arrow("ti_locator_keys")
                self._registrations.remove("ti_locator_keys")
                yield time_key
            except GeneratorExit:
                raise
            except BaseException:
                self._defer_sql_cleanup = True
                raise
            finally:
                batch = None
                if not self._defer_sql_cleanup:
                    if "ti_locator_keys" in self._registrations:
                        self.executor.unregister_arrow("ti_locator_keys")
                        self._registrations.remove("ti_locator_keys")
                    if "ti_locator_times" in self._tables:
                        self.executor.drop_table("ti_locator_times")
                        self._tables.remove("ti_locator_times")

    def _count_group(self, path, index, projection, standard, *, price_schema_error, price_projected_bytes):
        request = self.requirement
        upper, upper_bindings = range_filter(request, include_start=False)
        target, target_bindings = range_filter(request)
        rows = targets = 0
        first = last = None
        iterator, primary = self._key_batches(path, index, projection, standard), None
        try:
            for time_key in iterator:
                check_period_cutoff(self.executor, "ti_locator_times", request)
                sql = self.FIXED_SQL_STEPS["locate_count"].format(
                    upper=upper, target=target, time_key=time_key)
                summary = self.executor.scalar(sql, upper_bindings + target_bindings)
                rows += summary["n"]
                targets += summary["targets"]
                if summary["n"]:
                    if first is None:
                        first = summary["first_time"]
                    last = summary["last_time"]
        except BaseException as error:
            primary = error
            self._defer_sql_cleanup = True
            raise
        finally:
            self._close_iteration(iterator, primary)
        return _Group(path, index, rows, targets, first, last, price_schema_error, price_projected_bytes)

    def _read_stock_daily_group(self, path, index, keys, prices, *, schema_error, projected_bytes):
        import pyarrow.compute as pc

        # A bad price projection matters only if this group is selected. Locate
        # by its keys without reading unsafe columns in that case.
        read_prices = (schema_error is None
                       and projected_bytes <= self.source._config.max_projected_row_group_bytes)
        columns = prices if read_prices else keys
        partition_day = date.fromisoformat(path.parent.name.removeprefix("trade_date="))
        rows, price_batch = 0, None
        for batch in _stock_batches(self._metadata_reader, columns, self.requirement.ts_code, self.control,
                                    batch_rows=self.requirement.batch_rows, row_groups=[index]):
            self.context.record_locator_rows(batch.num_rows)
            if not pc.all(pc.fill_null(pc.equal(batch.column("trade_date"), partition_day), False)).as_py():
                raise SourceContractError("Source prices do not match their partition date")
            rows += batch.num_rows
            if rows > 1:
                raise SourceContractError("Duplicate stock daily positions in the partition")
            if read_prices:
                price_batch = batch
        position = partition_day if rows else None
        targets = rows if partition_day >= self.requirement.start else 0
        return _Group(path, index, rows, targets, position, position, schema_error, projected_bytes, price_batch)

    def _close_iteration(self, iterator, primary):
        try:
            iterator.close()
        except BaseException as error:
            if primary is not None:
                primary.add_note(f"Locator iterator cleanup: {type(error).__name__}: {error}")
            else:
                if isinstance(error, (CalculationCancelledError, CalculationDeadlineError)):
                    raise
                raise ResourceCleanupError("The locator key iteration could not be released") from error

    def _bounds(self, group, ranks, projection, standard):
        """Second key pass for at most two ordinal positions in this group."""
        found, preceding = {}, 0
        upper, bindings = range_filter(self.requirement, include_start=False)
        target, target_bindings = range_filter(self.requirement)
        iterator, primary = self._key_batches(group.path, group.index, projection, standard), None
        try:
            for time_key in iterator:
                summary = self.executor.scalar(self.FIXED_SQL_STEPS["locate_count"].format(
                    upper=upper, target=target, time_key=time_key), bindings + target_bindings)
                count = summary["n"]
                wanted = tuple(rank for rank in ranks if preceding < rank <= preceding + count)
                if wanted:
                    first = wanted[0] - preceding
                    second = wanted[1] - preceding if len(wanted) > 1 else first
                    values = self.executor.scalar(self.FIXED_SQL_STEPS["locate_bounds"].format(
                        upper=upper, time_key=time_key), bindings + (first, second))
                    found[wanted[0]] = values["first_time"]
                    if len(wanted) > 1:
                        found[wanted[1]] = values["second_time"]
                preceding += count
                if set(found) == set(ranks):
                    break
        except BaseException as error:
            primary = error
            self._defer_sql_cleanup = True
            raise
        finally:
            self._close_iteration(iterator, primary)
        if set(found) != set(ranks):
            raise SourceContractError("The second key read could not reproduce the selected boundary")
        return found

    def _select(self, paths, schema, projection, standard, *, price_projection):
        history = self.requirement.history
        maximum = self.source._config.max_input_rows
        output_maximum = self.requirement.output_limit(self.context.config)
        stock_daily = self.requirement.target.dataset_id == "stock_daily"
        first_target_partition = f"trade_date={self.requirement.start}"
        groups, rows, targets = [], 0, 0
        candidates_exhausted = False
        complete = False
        # Paths hold only partition descriptions. Older footers are opened only
        # if the newer groups did not already provide the necessary history.
        for path_index in range(len(paths) - 1, -1, -1):
            path = paths[path_index]
            if not targets and path.parent.name < first_target_partition:
                break
            metadata, price_schema_error = self._open_metadata(path, schema, projection,
                                                               price_projection=price_projection)
            partition_rows = 0
            for index in range(metadata.num_row_groups - 1, -1, -1):
                self.control.check_active()
                group_metadata = metadata.row_group(index)
                if not self._may_match(group_metadata, projection):
                    continue
                self._check_group_bytes(group_metadata, projection)
                price_projected_bytes = sum(group_metadata.column(i).total_uncompressed_size
                    for i in range(group_metadata.num_columns)
                    if group_metadata.column(i).path_in_schema in price_projection)
                if stock_daily:
                    group = self._read_stock_daily_group(path, index, projection, price_projection,
                        schema_error=price_schema_error, projected_bytes=price_projected_bytes)
                else:
                    group = self._count_group(path, index, projection, standard,
                        price_schema_error=price_schema_error, price_projected_bytes=price_projected_bytes)
                if group.rows:
                    partition_rows += group.rows
                    if partition_rows > 1:
                        raise SourceContractError("Duplicate stock daily positions in the partition")
                    groups.append(group)
                    rows += group.rows
                    targets += group.targets
                if targets > output_maximum:
                    raise ResourceLimitError("Target positions exceed max_output_rows")
                target_known = group.rows > group.targets
                actual = targets
                needs_origin = history.requires_source_origin or (
                    target_known and history.warmup_rows + actual > maximum)
                if needs_origin and rows > maximum:
                    raise ResourceLimitError("The required warmup cannot fit without reaching the source origin")
                if target_known and (actual == 0 or (
                        not needs_origin and rows >= actual + history.warmup_rows)):
                    complete = True
            self._close_metadata()
            metadata = group_metadata = None
            if complete:
                candidates_exhausted = path_index == 0
                break
        else:
            candidates_exhausted = True
        actual = targets
        if not actual:
            return (), PriceReadSelection(None, None, None, None, 0, 0, candidates_exhausted, ()), ()
        needs_origin = history.requires_source_origin or actual + history.warmup_rows > maximum
        # Counting the oldest group does not select all of its rows. First
        # keep the finite requested range; only then decide whether its lower
        # bound is the actual source origin.
        wanted = rows if needs_origin else min(rows, actual + history.warmup_rows)
        origin = candidates_exhausted and wanted == rows
        if wanted > maximum or (needs_origin and not origin):
            raise ResourceLimitError("The selected input exceeds the request's historical capacity")
        # Locate the target/read lower bounds without retaining all timestamps.
        boundary_groups = {}
        positions, included, newer = {}, [], 0
        for group in groups:
            if newer >= wanted:
                break
            included.append(group)
            for name, rank in (("target", actual), ("read", wanted)):
                if newer < rank <= newer + group.rows:
                    ordinal = group.rows - (rank - newer) + 1
                    if ordinal == 1:
                        positions[name] = group.first
                    elif ordinal == group.rows:
                        positions[name] = group.last
                    else:
                        boundary_groups.setdefault(group, {})[name] = ordinal
            newer += group.rows
        for group, requested in boundary_groups.items():
            values = self._bounds(group, tuple(sorted(set(requested.values()))), projection, standard)
            positions.update((name, values[ordinal]) for name, ordinal in requested.items())
        selected = {}
        for group in reversed(included):
            selected.setdefault(group.path, []).append(group.index)
        selected_paths = tuple(selected)
        selection = PriceReadSelection(
            self._position(positions["target"]), self._position(groups[0].last),
            self._position(positions["read"]), self._position(groups[0].last),
            actual, wanted - actual, origin,
            tuple(tuple(indices) for indices in selected.values()),
        )
        return selected_paths, selection, tuple(reversed(included))

    def _index_period_keys(self, path, index):
        _, ds, fs, _ = _arrow()
        self._fragment = ds.ParquetFileFormat().make_fragment(
            str(path), filesystem=fs.LocalFileSystem(), row_groups=[index])
        self._scanner = ds.Scanner.from_fragment(
            self._fragment, columns=list(INDEX_PERIOD_KEYS), filter=ds.field("ts_code") == self.requirement.ts_code,
            batch_size=self.requirement.batch_rows, batch_readahead=0, fragment_readahead=0,
            fragment_scan_options=ds.ParquetFragmentScanOptions(pre_buffer=False, use_buffered_stream=False),
            use_threads=False, cache_metadata=False)
        self._reader = self._scanner.to_reader()
        try:
            for batch in self._reader:
                self.control.check_active()
                self.context.record_locator_rows(batch.num_rows)
                yield from zip(batch.column("period_start_date").to_pylist(),
                               batch.column("trade_date").to_pylist(), strict=True)
        finally:
            self._close_key_reader()

    def _describe_stock_period(self):
        request = self.requirement
        require_stock_period(request, "dg")
        self._root = self.source._root()
        template = Path(request.target.location["path_template"])
        base = self.source._safe_path(self._root, template.parent.parent)
        prefix = "week_end=" if request.period == "week" else "month="
        partitions = []
        if base.is_dir():
            for entry in base.iterdir():
                self.control.check_active()
                if not entry.name.startswith(prefix):
                    continue
                label = entry.name.removeprefix(prefix)
                try:
                    day = date.fromisoformat(label if request.period == "week" else f"{label}-01")
                except ValueError:
                    continue
                partitions.append((day, entry / template.name))
        partitions.sort(reverse=True)

        def read_rows(start, end, limit, columns):
            rows = []
            for day, path in partitions:
                self.control.check_active()
                if day > end:
                    continue
                if day < start or len(rows) == limit:
                    break
                if not path.is_file():
                    continue
                row = self._read_stock_period_partition(path, day, columns)
                if row is not None:
                    rows.append(row)
            return rows

        return describe_stock_period(request, self.context, read_rows)

    def _read_stock_period_partition(self, path, day, columns):
        projection = ("ts_code", *columns)
        schema = (*PERIOD_SCHEMA, ("pct_chg", "DECIMAL(10,4)"))
        metadata, _ = self._open_metadata(path, schema, projection, price_projection=())
        row = None
        try:
            for index in range(metadata.num_row_groups):
                self.control.check_active()
                group = metadata.row_group(index)
                if not self._may_match(group, projection):
                    continue
                self._check_group_bytes(group, projection)
                for batch in _stock_batches(self._metadata_reader, projection, self.requirement.ts_code,
                                            self.control, batch_rows=self.requirement.batch_rows, row_groups=[index]):
                    if row is not None or batch.num_rows != 1:
                        raise SourceContractError("Duplicate DG stock period positions in the partition")
                    row = batch.select(columns).to_pylist()[0]
        finally:
            self._close_metadata()
        if row is not None:
            try:
                row["trade_date"] = date.fromisoformat(row["trade_date"])
            except (TypeError, ValueError) as exc:
                raise SourceContractError("Invalid DG stock period trade_date") from exc
            period = self.requirement.period
            if period_bounds(row["trade_date"], period)[0] != period_bounds(day, period)[0]:
                raise SourceContractError("DG stock period trade_date does not belong to its partition")
            if "end_date" in row:
                try:
                    row["end_date"] = date.fromisoformat(row["end_date"])
                except (TypeError, ValueError):
                    row["end_date"] = None
        return row

    def _describe_recent_index_period(self):
        request, config = self.requirement, self.context.config
        require_index_period(request, "dg")
        self._root = self.source._root()
        path = self.source._safe_path(self._root, Path(request.target.location["path_template"]))
        version = _file_version(path)
        self.context.record_file(path, version[2])
        physical, _ = index_period_projection(request)
        price_columns = physical[len(INDEX_PERIOD_KEYS):]
        auxiliary = ("pre_close", "change_amount", "pct_chg") if request.include_source_facts else ()
        projection = "".join(f", {column}" for column in (*price_columns, *auxiliary))
        table = "ti_index_period_rows"
        self._tables.append(table)
        self.executor.execute(SqlStep("materialize_index_period", f"""
            CREATE TEMP TABLE {table} AS
            SELECT period_start_date, CAST(date_trunc(?, period_start_date) AS DATE) AS period_start,
                   trade_date{projection}
            FROM read_parquet(?, hive_partitioning=false)
            WHERE ts_code = ?
        """, (request.period, str(path), request.ts_code), (), (table,), 0))
        if _file_version(path) != version:
            raise SourceReadError("The index period file changed during the request")

        read_error = "The retained index period rows could not be read"
        ((source_count, distinct_count, first_period, source_first, source_latest),) = self._read_rows(
            f"""SELECT count(*), count(DISTINCT period_start), min(period_start),
                       arg_min(row(period_start_date, trade_date), period_start),
                       arg_max(row(period_start_date, trade_date), period_start)
                FROM {table}""",
            (), error_message=read_error,
        )
        self.context.record_locator_rows(source_count)
        if source_count != distinct_count:
            raise SourceContractError("Index period source has invalid or duplicate period keys")
        if source_first is not None:
            check_period_key(source_first, request.period)
            check_period_key(source_latest, request.period)
        lower = period_bounds(request.start, request.period)[0] if request.start is not None else None
        upper = period_bounds(request.end, request.period)[0]
        candidates = self._read_rows(
            f"""SELECT * FROM {table}
                WHERE period_start <= ? AND trade_date <= ?
                  AND (?::DATE IS NULL OR (period_start >= ?::DATE AND trade_date >= ?::DATE))
                ORDER BY period_start DESC
                LIMIT ?""",
            (upper, request.end, request.start, lower, request.start, request.latest_rows + 1),
            error_message=read_error, as_arrow=True,
        )

        targets = candidates.slice(0, request.latest_rows)
        preceding = candidates.slice(targets.num_rows)
        older = preceding["trade_date"][0].as_py() if preceding.num_rows else None
        effective_request = request
        pa, _, _, _ = _arrow()
        if targets.num_rows:
            history_limit, _ = preceding_limit(config, request, targets.num_rows)
            # Keep one further row as evidence when the source origin has not been reached.
            before = (preceding["period_start"][0] if preceding.num_rows else targets["period_start"][-1]).as_py()
            earlier = self._read_rows(
                f"""SELECT * FROM {table} WHERE period_start < ?
                    ORDER BY period_start DESC LIMIT ?""",
                (before, history_limit + 1 - preceding.num_rows),
                error_message=read_error, as_arrow=True,
            )
            preceding = pa.concat_tables((preceding, earlier))
            effective_request = replace(
                request, start=targets["period_start"][-1].as_py(), end=targets["trade_date"][0].as_py(),
            )
        self.executor.drop_table(table)
        self._tables.remove(table)

        def keys(rows):
            return tuple(zip(reversed(rows["period_start_date"].to_pylist()),
                             reversed(rows["trade_date"].to_pylist()), strict=True))

        description = describe_index_period(
            effective_request, self.context, keys(targets), keys(preceding), source_first, source_latest,
        )
        facts = SourceReadFacts()
        if request.include_source_facts:
            target_facts = targets.select(("period_start", "trade_date", *auxiliary)).to_pylist()
            facts = SourceReadFacts(
                target_bars=tuple(
                    TargetBarFacts(row["period_start"], row["trade_date"],
                                   *(float(row[name]) if row[name] is not None else None for name in auxiliary))
                    for row in reversed(target_facts)
                ),
                previous_target_date=older,
                first_available_period=first_period,
                latest_available_date=source_latest[1] if source_latest is not None else None,
            )
        if targets.num_rows:
            records = pa.concat_tables((targets, preceding.slice(0, description.selection.preceding_rows)))
            # Feed the same dates and price columns to the existing checked stream.
            positions = pa.array(range(records.num_rows - 1, -1, -1), type=pa.int32())
            batches = records.select(physical[1:]).take(positions).to_batches(max_chunksize=request.batch_rows)
            self.context.retained_price_batches = tuple(batches)
        return replace(description, source_projection=physical[1:], source_facts=facts)

    def _describe_index_period(self):
        request, config = self.requirement, self.context.config
        require_index_period(request, "dg")
        self._root = self.source._root()
        path = self.source._safe_path(self._root, Path(request.target.location["path_template"]))
        version = _file_version(path)
        physical, _ = index_period_projection(request)
        metadata, schema_error = self._open_metadata(path, _INDEX_PERIOD_SCHEMA, INDEX_PERIOD_KEYS,
                                                     price_projection=physical)
        first = latest = None
        targets, group_ranges = [], []
        output_limit = request.output_limit(config)
        history_capacity, _ = preceding_limit(config, request, 0)
        preceding = deque(maxlen=history_capacity + 1)
        target_start = period_request_start(request)
        last_period, last_period_end = period_bounds(request.end, request.period)
        for index in range(metadata.num_row_groups):
            self.control.check_active()
            group = metadata.row_group(index)
            if not self._may_match(group, INDEX_PERIOD_KEYS):
                continue
            self._check_group_bytes(group, INDEX_PERIOD_KEYS)
            group_first = group_last = None
            keys = self._index_period_keys(path, index)
            try:
                for key in keys:
                    label = check_period_key(key, request.period)
                    if latest is not None and key[0] <= latest[0]:
                        raise SourceContractError("DG index period source starts are duplicated or out of order")
                    first = first or key
                    latest = key
                    group_first = group_first or key[0]
                    group_last = key[0]
                    if label == last_period and label >= target_start:
                        check_index_period_cutoff(key[1], request, last_period_end)
                    if label < target_start:
                        preceding.append(key)
                    elif label <= last_period and len(targets) <= output_limit:
                        targets.append(key)
            finally:
                keys.close()
            if group_first is not None:
                group_ranges.append((index, group_first, group_last))
        if _file_version(path) != version:
            raise SourceReadError("The index period file changed during the request")
        if len(targets) > output_limit:
            raise ResourceLimitError("Target positions exceed max_output_rows")
        selected_groups = ()
        if targets:
            wanted, _ = preceding_limit(config, request, len(targets))
            first_key = preceding[max(0, len(preceding) - wanted)] if preceding and wanted else targets[0]
            selected_groups = tuple(index for index, start, end in group_ranges
                                    if end >= first_key[0] and start <= targets[-1][0])
            if schema_error is not None:
                raise SourceContractError(schema_error)
            for index in selected_groups:
                self._check_group_bytes(metadata.row_group(index), physical)
        self._close_metadata()
        return describe_index_period(request, self.context, targets, tuple(preceding), first, latest,
                                     path=path, row_groups=selected_groups, file_version=version)

    def _read_index_minute_partition(self, path, columns, cutoff, limit):
        self.control.check_active()
        path = self.source._safe_path(self._root, path)
        self.context.record_file(path, path.stat().st_size)
        rows = self._read_rows(
            f"""WITH selected AS (
                    SELECT CAST(regexp_extract(filename, '/trade_date=([0-9-]{{10}})/', 1) AS DATE)
                               AS partition_day,
                           {", ".join(columns)}, count(*) OVER (PARTITION BY trade_time) AS position_rows
                    FROM read_parquet(?, hive_partitioning=false, filename=true)
                    WHERE ts_code = ? AND trade_time <= ?
                )
                SELECT * FROM selected ORDER BY trade_time DESC LIMIT ?""",
            (str(path), self.requirement.ts_code, cutoff, limit),
            error_message="The DG index minute partition could not be read", as_arrow=True,
        )
        self.context.record_locator_rows(rows.num_rows)
        return rows

    def _select_index_minutes(self, paths, *, price_projection):
        request, config = self.requirement, self.context.config
        start, cutoff = request.start.replace(tzinfo=None), request.end.replace(tzinfo=None)
        first_partition = f"trade_date={start.date()}"
        output_limit = request.output_limit(config)
        pa, _, _, _ = _arrow()
        batches = []
        targets = preceding = 0
        target_start = target_end = read_start = None
        reached_origin = True

        for path in reversed(paths):
            history_limit, needs_origin = preceding_limit(config, request, targets)
            partition = path.parent.name
            if partition < first_partition:
                if not targets or (preceding == history_limit and not needs_origin):
                    reached_origin = False
                    break
                limit = history_limit - preceding + 1
            elif partition == first_partition:
                # This partition may contain both target and warmup rows.
                limit = config.max_input_rows - targets + 1
            else:
                limit = min(output_limit - targets, config.max_input_rows - targets) + 1

            rows = self._read_index_minute_partition(path, price_projection, cutoff, limit)
            stamps = rows["trade_time"].to_pylist()
            if not stamps:
                continue
            for stamp, day, partition_day, freq, duplicates in zip(
                stamps, rows["trade_date"].to_pylist(), rows["partition_day"].to_pylist(),
                rows["freq"].to_pylist(), rows["position_rows"].to_pylist(), strict=True,
            ):
                if duplicates != 1:
                    raise SourceContractError("DG index minute timestamps overlap")
                if day != partition_day:
                    raise SourceContractError("Source prices do not match their partition date")
                if freq != 5:
                    raise SourceContractError("Index minutes do not match their five-minute partition")
                if stamp.date() != partition_day or stamp.time() == time(9, 30):
                    raise SourceContractError("Invalid business timestamp in DG index minutes")
            if read_start is not None and stamps[0] >= read_start:
                raise SourceContractError("DG index minute timestamps overlap or are out of order")

            found_targets = sum(stamp >= start for stamp in stamps)
            targets += found_targets
            if targets > output_limit:
                raise ResourceLimitError("Target positions exceed max_output_rows")
            if not targets:
                continue
            history_limit, needs_origin = preceding_limit(config, request, targets)
            found_preceding = len(stamps) - found_targets
            available = history_limit - preceding
            if needs_origin and found_preceding > available:
                raise ResourceLimitError("The required warmup cannot fit without reaching the source origin")
            keep_preceding = min(found_preceding, available)
            preceding += keep_preceding
            if found_targets:
                target_end = target_end or stamps[0]
                target_start = stamps[found_targets - 1]
            keep = found_targets + keep_preceding
            if keep:
                read_start = stamps[keep - 1]
                order = pa.array(range(keep - 1, -1, -1), type=pa.int32())
                batches.append(rows.select(price_projection).take(order).to_batches(max_chunksize=request.batch_rows))
            if found_preceding > keep_preceding:
                # The extra row proves this finite warmup stopped before the source origin.
                reached_origin = False
                break

        if not targets:
            return PriceReadSelection(None, None, None, None, 0, 0, reached_origin, ())
        self.context.retained_price_batches = tuple(batch for group in reversed(batches) for batch in group)
        return PriceReadSelection(
            self._position(target_start), self._position(target_end),
            self._position(read_start), self._position(target_end),
            targets, preceding, reached_origin, (),
        )

    def _describe_index_minutes(self):
        request = self.requirement
        volume_unit = index_minute_volume_unit(request, "dg")
        self.control.check_active()
        self._root = self.source._root()
        paths = self.source._partition_paths(self._root, request, self.control)
        physical, standard = index_minute_projection(request.history.fields)
        price_projection = physical[1:]
        selection = self._select_index_minutes(paths, price_projection=price_projection)
        return SourceDescription(
            source_id=request.target.dataset_id, contract_version="1", input_adjustment="none",
            basis_rule=None, basis_date=None, basis_value=None,
            price_unit="index_point", volume_unit=volume_unit, amount_unit="CNY", timezone="Asia/Shanghai",
            period_label_rule="trade_time", history_origin_rule="earliest_available_formal_partition",
            available_through=None, supports_partial_period=False, supported_adjustment_paths=(("none", "none"),),
            converted=False, selection=selection, price_paths=(), factor_paths=(),
            source_projection=price_projection, standard_projection=standard,
        )

    def _describe_recent_index_minutes(self):
        request = self.requirement
        self._root = self.source._root()
        paths = self.source._partition_paths(self._root, request, self.control)
        _, standard = index_minute_projection(request.history.fields)
        columns = tuple(name for name, _ in standard)
        standard = tuple(
            (name, 'CAST(b."volume" AS DOUBLE)' if name == "volume" else expression)
            for name, expression in standard
        )
        sql = dg_recent_index_minute_sql(request.period, columns)
        daily_rows = EXPECTED_BARS_PER_SESSION[int(request.period.removesuffix("m"))]
        selection, facts, batches = self._select_recent_minutes(
            paths, columns, sql, daily_rows=daily_rows,
            error_message="The DG index minute batch could not be read",
        )
        self.context.retained_price_batches = batches if selection.target_rows else None
        return SourceDescription(
            source_id=request.target.dataset_id, contract_version="1", input_adjustment="none",
            basis_rule=None, basis_date=None, basis_value=None,
            price_unit="index_point", volume_unit="share", amount_unit="CNY", timezone="Asia/Shanghai",
            period_label_rule="trade_time", history_origin_rule="earliest_available_formal_partition",
            available_through=None, supports_partial_period=False, supported_adjustment_paths=(("none", "none"),),
            converted=False, selection=selection, source_projection=columns,
            standard_projection=standard, source_facts=facts,
        )

    def _describe_recent_stock_minutes(self):
        request = self.requirement
        self._root = self.source._root()
        paths = self.source._partition_paths(self._root, request, self.control)
        target_frequency = int(request.period.removesuffix("m"))
        location = self.context.config.dataset_locations[request.target.dataset_id]["dg"]
        base_frequency = int(location["partitions"]["freq"])
        sql, daily_rows = stock_minute_selection_sql(target_frequency, base_frequency)
        target_limit = request.latest_rows
        if request.start is not None:
            first_target = bisect_left(paths, f"trade_date={request.start.date()}", key=lambda path: path.parent.name)
            target_limit = min(target_limit, (len(paths) - first_target) * daily_rows)
        selection, facts, batches = self._select_recent_minutes(
            paths, ("trade_date", "trade_time", "exchange", "base_bars"), sql,
            daily_rows=daily_rows, source_filters=(base_frequency,), target_limit=target_limit,
            error_message="The DG stock minute batch could not be read",
        )
        columns = ("trade_date", "trade_time", *(field for field in DAILY_PRICE_FIELDS
                                                if field in request.history.fields))
        description = SourceDescription(
            source_id=request.target.dataset_id, contract_version="1", input_adjustment="none",
            basis_rule="latest_available_factor", basis_date=None, basis_value=None,
            price_unit="CNY", volume_unit="share", amount_unit="CNY", timezone="Asia/Shanghai",
            period_label_rule="trade_time", history_origin_rule="earliest_available_formal_partition",
            available_through=None, supports_partial_period=False, supported_adjustment_paths=(("none", "qfq"),),
            converted=True, selection=selection, source_projection=columns,
            standard_projection=tuple((column, f'b."{column}"') for column in columns),
            source_facts=replace(facts, scanned_file_count=self.context.source_files),
            delivered_adjustment="qfq",
        )
        if not selection.target_rows:
            return description
        factor_target = self.context.config.resolve_dataset_location("stock_adj_factor")
        factor_paths = self.source._dated_partitions(self._root, factor_target, date.max, self.control)
        description = replace(description, factor_paths=factor_paths)
        return self._adjust_recent_stock_minutes(description, batches, columns)

    def _adjust_recent_stock_minutes(self, description, batches, columns):
        pa, _, _, _ = _arrow()
        request = self.requirement
        windows = pa.Table.from_batches(batches)
        trade_dates = tuple(sorted(windows["trade_date"].unique().to_pylist()))
        registration = "ti_stock_minute_windows"
        selected = "ti_stock_minute_selected_rows"
        basis = "ti_stock_minute_basis"
        factors = "ti_stock_minute_factors"
        for name in (selected, basis, factors):
            self.executor.declare_table(name)
            self._tables.append(name)

        self._registrations.append(registration)
        self.executor.register_arrow(registration, windows)
        stats = self.executor.execute(SqlStep(
            "expand_stock_minute_windows", STOCK_MINUTE_SELECTED_ROWS_SQL, (), (registration,), (selected,),
            windows.num_rows,
        ))
        self.executor.unregister_arrow(registration)
        self._registrations.remove(registration)
        self.context.record_price_rows(0, additional_source_rows=stats.output_rows - windows.num_rows)
        description = self.source.prepare_basis(
            self.executor, description, request, table_name=basis, read_context=self.context, paths_root=self._root,
        )
        validate_adjustment_basis(description)
        self.source.prepare_factors(
            self.executor, description, request, trade_dates, table_name=factors, read_context=self.context, paths_root=self._root,
        )
        validate_adjustment_factors(self.executor, selected, factors)
        adjusted = self._read_rows(
            adjusted_stock_minute_sql(columns), (),
            error_message="The DG stock minute prices could not be converted and combined", as_arrow=True,
        )
        self.context.retained_price_batches = tuple(adjusted.to_batches(max_chunksize=request.batch_rows))
        return description

    def _select_recent_minutes(
        self, paths, columns, sql, *, daily_rows, error_message, source_filters=(), target_limit=None,
    ):
        request, config = self.requirement, self.context.config
        pa, _, _, _ = _arrow()
        start = request.start.replace(tzinfo=None) if request.start is not None else None
        cutoff = request.end.replace(tzinfo=None)
        remaining_files = len(paths)
        if target_limit is None:
            target_limit = request.latest_rows
        targets = history = 0
        target_start = target_end = read_start = None
        exchanges, batches = [], []
        has_more = crossed_start = omitted_older_rows = False
        while remaining_files:
            if not targets and start is not None and paths[remaining_files - 1].parent.name < f"trade_date={start.date()}":
                break
            history_limit, needs_origin = preceding_limit(config, request, targets)
            wanted_targets = 0 if crossed_start else target_limit - targets
            probe = not has_more and not crossed_start
            wanted = wanted_targets + max(history_limit - history + int(needs_origin), int(probe))
            if not wanted:
                break
            limit = min(wanted, config.max_input_rows - targets - history + 1)
            file_count = min((limit + daily_rows - 1) // daily_rows, request.batch_rows)
            first = max(0, remaining_files - file_count)
            batch_paths = paths[first:remaining_files]
            remaining_files = first
            for path in batch_paths:
                self.control.check_active()
                self.source._safe_path(self._root, path)
                self.context.record_file(path, path.stat().st_size)
            rows = self._read_rows(
                sql, (list(map(str, batch_paths)), request.ts_code, *source_filters, cutoff, limit),
                error_message=error_message, as_arrow=True,
            )
            self.context.record_locator_rows(rows.num_rows)
            if not rows.num_rows:
                continue

            stamps = rows["trade_time"].to_pylist()
            eligible = len(stamps) if start is None else sum(stamp >= start for stamp in stamps)
            new_targets = min(wanted_targets, eligible)
            crossed_start = crossed_start or eligible < len(stamps)
            has_more = has_more or eligible > new_targets
            if new_targets:
                target_end = target_end or stamps[0]
                target_start = stamps[new_targets - 1]
                targets += new_targets
                exchanges.extend(rows["exchange"].slice(0, new_targets).to_pylist())
            if not targets:
                break

            history_limit, needs_origin = preceding_limit(config, request, targets)
            available = len(stamps) - new_targets
            keep_history = min(available, history_limit - history)
            if needs_origin and available > keep_history:
                raise ResourceLimitError("The required warmup cannot fit without reaching the source origin")
            history += keep_history
            keep = new_targets + keep_history
            omitted_older_rows = omitted_older_rows or keep < len(stamps) or len(stamps) == limit
            if keep:
                read_start = stamps[keep - 1]
                order = pa.array(range(keep - 1, -1, -1), type=pa.int32())
                batches.append(rows.select(columns).take(order).to_batches(max_chunksize=request.batch_rows))

        reached_origin = not remaining_files and not omitted_older_rows
        if not targets:
            return PriceReadSelection(None, None, None, None, 0, 0, reached_origin, ()), SourceReadFacts(), ()
        return (
            PriceReadSelection(
                self._position(target_start), self._position(target_end),
                self._position(read_start), self._position(target_end), targets, history, reached_origin, (),
            ),
            SourceReadFacts(has_more=has_more, target_exchanges=tuple(reversed(exchanges))),
            tuple(batch for group in reversed(batches) for batch in group),
        )

    def _read_recent_daily_batch(self, paths, columns):
        for path in paths:
            self.control.check_active()
            self.source._safe_path(self._root, path)
            self.context.record_file(path, path.stat().st_size)
        sql = f"""
            SELECT {", ".join(columns)}
            FROM read_parquet(?, hive_partitioning=false)
            WHERE ts_code = ?
            ORDER BY trade_date DESC
            LIMIT ?
        """
        rows = self._read_rows(
            sql, (list(map(str, paths)), self.requirement.ts_code, len(paths)),
            error_message="The daily price batch could not be read",
        )
        self.context.record_locator_rows(len(rows))
        return rows

    def _read_rows(self, sql, bindings, *, error_message, as_arrow=False):
        from duckdb import Error, OutOfMemoryException

        self.control.check_active()
        try:
            cursor = self.executor.connection.execute(sql, bindings)
            if as_arrow:
                # Keep the Arrow table read available on the supported DuckDB 1.3 runtime.
                read_arrow_table = getattr(cursor, "to_arrow_table", None) or cursor.fetch_arrow_table
                rows = read_arrow_table()
            else:
                rows = cursor.fetchall()
        except OutOfMemoryException as exc:
            self.control.check_active()
            raise ResourceLimitError("DuckDB query memory limit was exceeded") from exc
        except Error as exc:
            self.control.check_active()
            raise SourceReadError(error_message) from exc
        finally:
            self.control._note_sql_returned()
        self.control.check_active()
        return rows

    def _read_recent_index_calendar(self, selection, previous_target_date):
        """Validate the dates actually read and return the same calendar for the response."""
        request = self.requirement
        origin = dg_index_daily_origin(request.ts_code)
        target_start = max(origin, request.start or origin)
        check_start = selection.read_start or target_start
        if selection.target_rows and selection.reached_source_origin:
            check_start = origin
        elif selection.target_rows < request.latest_rows:
            check_start = min(check_start, target_start)
        if previous_target_date is not None:
            check_start = min(check_start, previous_target_date)

        calendar = self.context.config.resolve_dataset_location("trade_calendar")
        path = self.source._safe_path(self._root, Path(calendar.location["path_template"]))
        self.context.record_file(path, path.stat().st_size)
        rows = self._read_rows(
            """SELECT trade_date, is_open, pretrade_date
               FROM read_parquet(?, hive_partitioning=false)
               WHERE exchange = ? AND trade_date BETWEEN ? AND ?
               ORDER BY trade_date""",
            (str(path), "SSE", min(check_start, request.end), request.end),
            error_message="The index daily trading calendar could not be read",
        )
        if check_start <= request.end:
            actual = tuple(day for batch in (self.context.source_state or ())
                           for day in batch.column("trade_date").to_pylist())
            if previous_target_date is not None and previous_target_date < selection.read_start:
                actual = (previous_target_date, *actual)
            # Beyond the published calendar, the page uses its last known open date.
            expected = tuple(scheduled_open_days(
                ((day, is_open) for day, is_open, _ in rows), check_start, rows[-1][0],
            )) if rows else ()
            if expected != actual:
                raise SourceReadError("读取数据失败", detail="数据缺失")
        return tuple(CalendarDayFacts(*row) for row in rows)

    def _select_recent_daily(self, paths, *, price_projection):
        request = self.requirement
        columns = price_projection + (
            ("pre_close", "change_amount", "pct_chg") if request.include_source_facts else ()
        )
        remaining = len(paths)
        target_floor = 0 if request.start is None else bisect_left(
            paths, f"trade_date={request.start}", key=lambda path: path.parent.name,
        )

        def read_previous(wanted, projection, floor=0):
            nonlocal remaining
            first = max(floor, remaining - min(wanted, request.batch_rows))
            rows = self._read_recent_daily_batch(paths[first:remaining], projection)
            remaining = first
            return rows

        target = []
        while remaining > target_floor and len(target) < request.latest_rows:
            target.extend(read_previous(request.latest_rows - len(target), columns, target_floor))
        if not target:
            return PriceReadSelection(None, None, None, None, 0, 0, not remaining, ()), SourceReadFacts()

        history_limit, needs_origin = preceding_limit(self.context.config, request, len(target))
        history = []
        previous_target_date = None
        while remaining:
            cursor_pending = request.include_source_facts and not history and remaining > target_floor
            wanted = max(history_limit - len(history) + int(needs_origin), int(cursor_pending))
            if not wanted:
                break
            rows = read_previous(wanted, price_projection)
            if cursor_pending and rows:
                day = rows[0][0]
                if request.start is None or day >= request.start:
                    previous_target_date = day
            history.extend(rows)
            if len(history) > history_limit:
                if needs_origin:
                    raise ResourceLimitError("The required warmup cannot fit without reaching the source origin")
                break

        reached_origin = not remaining and len(history) <= history_limit
        del history[history_limit:]
        target.reverse()
        history.reverse()
        pa, _, _, _ = _arrow()
        price_values = zip(*(row[:len(price_projection)] for row in (*history, *target)), strict=True)
        price_table = pa.Table.from_arrays(
            [pa.array(values, type=pa.date32() if name == "trade_date" else pa.float64())
             for name, values in zip(price_projection, price_values, strict=True)],
            names=price_projection,
        )
        self.context.source_state = tuple(price_table.to_batches(max_chunksize=request.batch_rows))
        selection = PriceReadSelection(
            target[0][0], target[-1][0], (history or target)[0][0], target[-1][0],
            len(target), len(history), reached_origin, (),
        )
        facts = SourceReadFacts()
        if request.include_source_facts:
            facts = SourceReadFacts(
                tuple(TargetBarFacts(row[0], row[0], *row[len(price_projection):]) for row in target),
                previous_target_date,
            )
        return selection, facts

    def describe(self):
        if self._closed or self._started:
            raise SourceContractError("A source locator can only describe one request")
        self._started = True
        pa, _, _, _ = _arrow()
        try:
            request = self.requirement
            if request.target.dataset_id in STOCK_PERIOD_DATASETS.values():
                return self._describe_stock_period()
            if request.period in INDEX_PERIOD_DATASETS:
                if request.latest_rows is not None:
                    return self._describe_recent_index_period()
                return self._describe_index_period()
            if request.period.endswith("m"):
                if request.target.dataset_id in DG_RECENT_INDEX_MINUTE_DATASETS.values():
                    return self._describe_recent_index_minutes()
                if request.target.dataset_id in DG_RECENT_STOCK_MINUTE_DATASETS.values():
                    return self._describe_recent_stock_minutes()
                return self._describe_index_minutes()
            adjustments = daily_adjustment_paths(request, "dg")
            self.control.check_active()
            self._root = self.source._root()
            paths = self.source._partition_paths(self._root, request, self.control)
            projection, standard = daily_price_projection(frozenset())
            price_projection, price_standard = daily_price_projection(request.history.fields)
            stock_daily = request.target.dataset_id == "stock_daily"
            source_facts = SourceReadFacts()
            if request.latest_rows is not None:
                # ts_code is only a filter. All requested price columns come from this query.
                price_projection = price_projection[1:]
                selection, source_facts = self._select_recent_daily(paths, price_projection=price_projection)
                if request.target.dataset_id == "index_daily":
                    calendar_days = self._read_recent_index_calendar(selection, source_facts.previous_target_date)
                    source_facts = replace(source_facts, calendar_days=calendar_days)
                paths = ()
            else:
                if not stock_daily:
                    self._stage_text = self.context.sql_template("stage_input.sql", control=self.control)
                paths, selection, groups = self._select(paths, DAILY_SCHEMA, projection, standard,
                                                        price_projection=price_projection)
                self._validate_selected_price_groups(groups)
                if stock_daily and selection.target_rows:
                    self.context.source_state = tuple(group.price_batch for group in groups)
            converted = request.target_adjustment == "qfq"
            factor_paths = ()
            if converted and selection.target_rows:
                factor_target = self.context.config.resolve_dataset_location("stock_adj_factor")
                factor_paths = tuple((day, self.source._safe_path(self._root, path)) for day, path in
                                     self.source._dated_partitions(self._root, factor_target, date.max, self.control))
            return SourceDescription(
                source_id=request.target.dataset_id, contract_version="1", input_adjustment="none",
                basis_rule="latest_available_factor" if converted else None, basis_date=None, basis_value=None,
                price_unit="index_point" if request.target.dataset_id == "index_daily" else "CNY",
                volume_unit="lot", amount_unit="thousand_CNY", timezone="Asia/Shanghai",
                period_label_rule="period_start",
                history_origin_rule="earliest_available_formal_partition", available_through=None,
                supports_partial_period=False, supported_adjustment_paths=adjustments, converted=converted,
                selection=selection, price_paths=paths, factor_paths=factor_paths,
                source_projection=price_projection, standard_projection=price_standard, source_facts=source_facts,
            )
        except TechnicalIndicatorError:
            raise
        except MemoryError as exc:
            raise ResourceLimitError("The price locator exceeded available memory") from exc
        except (OSError, pa.ArrowException) as exc:
            raise SourceReadError("The price range could not be located") from exc

    def close(self):
        if self._closed:
            return
        errors = []
        for name in tuple(reversed(self._registrations)):
            try:
                (self.executor.cleanup_unregister if self.control.cleanup_ready
                 else self.executor.unregister_arrow)(name)
                self._registrations.remove(name)
            except BaseException as exc:
                errors.append(exc)
        for closer in (self._close_key_reader, self._close_metadata):
            try:
                closer()
            except BaseException as exc:
                errors.append(exc)
        for name in tuple(reversed(self._tables)):
            try:
                (self.executor.cleanup_drop if self.control.cleanup_ready
                 else self.executor.drop_table)(name)
                self._tables.remove(name)
            except BaseException as exc:
                errors.append(exc)
        if errors:
            error = ResourceCleanupError("Source locator resources could not all be released")
            for exc in errors:
                error.add_note(f"{type(exc).__name__}: {exc}")
            raise error from errors[0]
        self._stage_text = None
        self._closed = True
