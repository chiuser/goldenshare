"""Locate a bounded price range and retain selected DG stock rows."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo

from goldenshare_technical_indicators.calculation.calculation import SqlStep
from goldenshare_technical_indicators.errors import (
    CalculationCancelledError, CalculationDeadlineError,
    ResourceCleanupError, ResourceLimitError, SourceContractError, SourceReadError,
    TechnicalIndicatorError,
)
from goldenshare_technical_indicators.sources.contracts import PriceReadSelection, SourceDescription
from goldenshare_technical_indicators.time_range import check_period_cutoff, range_filter

from ..technical_indicator_stock_daily import daily_adjustment_paths, daily_price_projection
from ..technical_indicator_index_minutes import index_minute_projection, index_minute_volume_unit
from ..technical_indicator_index_period import (
    INDEX_PERIOD_DATASETS, INDEX_PERIOD_KEYS, check_index_period_cutoff, check_period_key,
    describe_index_period, index_period_projection, period_bounds, period_request_start,
    preceding_limit, require_index_period,
)
from ..technical_indicator_stock_period import STOCK_PERIOD_DATASETS, describe_stock_period, require_stock_period
from .technical_indicator_contracts import DAILY_SCHEMA, MINUTE_SCHEMA, PERIOD_SCHEMA
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
            if request.period.endswith("m") and column.path_in_schema == "trade_time":
                end = request.end.replace(tzinfo=None) if isinstance(request.end, datetime) else request.end
                if stats.min > end:
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

        pa, ds, fs, _ = _arrow()
        request = self.requirement
        predicate = ds.field("ts_code") == request.ts_code
        minute = request.period.endswith("m")
        if minute:
            predicate &= ds.field("trade_time") <= pa.scalar(
                request.end.replace(tzinfo=None), type=pa.timestamp("us"))
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
        time_key = "trade_time" if request.period.endswith("m") else "period_start"
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
            if minute:
                if not pc.all(pc.fill_null(pc.equal(batch.column("freq"), 5), False)).as_py():
                    raise SourceContractError("Index minutes do not match their five-minute partition")
                for stamp in batch.column("trade_time").to_pylist():
                    if stamp.date() != partition_day or stamp.time() == time(9, 30):
                        raise SourceContractError("Invalid business timestamp in DG index minutes")
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
                    if request.period.endswith("m") and (summary["n"] != summary["distinct_positions"]
                            or last is not None and last >= summary["first_time"]):
                        raise SourceContractError("DG index minute keys are duplicated or out of order")
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
        daily = self.requirement.period == "day"
        stock_daily = self.requirement.target.dataset_id == "stock_daily"
        first_day = self.requirement.start if daily else self.requirement.start.date()
        first_target_partition = f"trade_date={first_day}"
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
                    if not daily and groups and group.last >= groups[-1].first:
                        raise SourceContractError("DG index minute row groups overlap or are out of order")
                    partition_rows += group.rows
                    if daily and partition_rows > 1:
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
                return self._describe_index_period()
            minute = request.period.endswith("m")
            if minute:
                volume_unit = index_minute_volume_unit(request, "dg")
                schema = (*MINUTE_SCHEMA, ("freq", "INTEGER"))
                project = index_minute_projection
                adjustments = (("none", "none"),)
            else:
                adjustments = daily_adjustment_paths(request, "dg")
                volume_unit, schema, project = "lot", DAILY_SCHEMA, daily_price_projection
            self.control.check_active()
            self._root = self.source._root()
            paths = self.source._partition_paths(self._root, request, self.control)
            projection, standard = project(frozenset())
            price_projection, price_standard = project(request.history.fields)
            stock_daily = request.target.dataset_id == "stock_daily"
            if not stock_daily:
                self._stage_text = self.context.sql_template("stage_input.sql", control=self.control)
            paths, selection, groups = self._select(paths, schema, projection, standard,
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
                price_unit="index_point" if minute or request.target.dataset_id == "index_daily" else "CNY",
                volume_unit=volume_unit,
                amount_unit="CNY" if minute else "thousand_CNY", timezone="Asia/Shanghai",
                period_label_rule="trade_time" if minute else "period_start",
                history_origin_rule="earliest_available_formal_partition", available_through=None,
                supports_partial_period=False, supported_adjustment_paths=adjustments, converted=converted,
                selection=selection, price_paths=paths, factor_paths=factor_paths,
                source_projection=price_projection, standard_projection=price_standard,
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
