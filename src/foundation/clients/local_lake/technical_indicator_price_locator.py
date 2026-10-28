"""Find one request's price range using bounded key batches, never OHLC values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo

from src.foundation.technical_indicators.calculation.calculation import SqlStep
from src.foundation.technical_indicators.errors import (
    ResourceCleanupError, ResourceLimitError, SourceContractError, SourceReadError,
    TechnicalIndicatorError,
)
from src.foundation.technical_indicators.sources.contracts import PriceReadSelection, SourceDescription
from src.foundation.technical_indicators.time_range import check_period_cutoff, range_filter

from .technical_indicator_contracts import price_contract, source_projection
from .technical_indicator_price_source import _arrow, _matches_type


@dataclass(frozen=True, slots=True)
class _Group:
    path: Path
    index: int
    rows: int
    targets: int
    first: object
    last: object


class LakePriceLocator:
    """Own only current metadata/keys and the small selected file/group list."""

    FIXED_SQL_STEPS = MappingProxyType({
        "locate_count": "WITH eligible AS (SELECT * FROM ti_locator_times WHERE {upper}) "
            "SELECT struct_pack(n := count(*), targets := count(*) FILTER (WHERE {target}), "
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
        self._metadata_reader = self._reader = self._scanner = self._fragment = None
        self._tables, self._registrations = [], []
        self._stage_text = None
        self._closed = self._started = False

    def _position(self, value):
        if self.requirement.request.period.endswith("m") and isinstance(value, datetime):
            return value.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return value

    def _close_metadata(self):
        if self._metadata_reader is not None:
            try:
                self._metadata_reader.close()
            except Exception as exc:
                raise ResourceCleanupError("The price locator metadata handle did not close") from exc
            self._metadata_reader = None

    def _open_metadata(self, path, contract, projection):
        pa, _, _, pq = _arrow()
        self.control.check_active()
        self.context.record_file(path, path.stat().st_size)
        self._metadata_reader = pq.ParquetFile(path)
        expected = dict(contract.schema)
        actual = self._metadata_reader.schema_arrow
        for name in projection:
            if (name not in actual.names or name not in expected
                    or not _matches_type(pa, actual.field(name).type, expected[name])):
                raise SourceContractError("The projected source schema does not match its declared contract")
        self.control.check_active()
        return self._metadata_reader.metadata

    def _may_match(self, group, projection):
        """Use only reliable typed metadata; missing statistics require keys."""
        request = self.requirement.request
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
            if ((request.period.endswith("m") and column.path_in_schema == "trade_time")
                    or (request.period == "day" and column.path_in_schema == "trade_date")):
                for value, strict in ((request.end, False), (request.before, True)):
                    if value is not None:
                        if isinstance(value, datetime):
                            value = value.replace(tzinfo=None)
                        if stats.min > value or (strict and stats.min == value):
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
        pa, ds, fs, _ = _arrow()
        request = self.requirement.request
        predicate = ds.field("ts_code") == request.ts_code
        if request.period.endswith("m") or request.period == "day":
            field = "trade_time" if request.period.endswith("m") else "trade_date"
            for value, strict in ((request.end, False), (request.before, True)):
                if value is not None:
                    if isinstance(value, datetime):
                        value = pa.scalar(value.replace(tzinfo=None), type=pa.timestamp("us"))
                    predicate &= ds.field(field) < value if strict else ds.field(field) <= value
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
            self._registrations.append("ti_locator_keys")
            self.executor.register_arrow("ti_locator_keys", batch)
            self.executor.declare_table("ti_locator_times")
            self._tables.append("ti_locator_times")
            self.executor.execute(SqlStep("locate_stage", text, (0,), ("ti_locator_keys",),
                                          ("ti_locator_times",), batch.num_rows))
            self.executor.unregister_arrow("ti_locator_keys")
            self._registrations.remove("ti_locator_keys")
            check_period_cutoff(self.executor, "ti_locator_times", request)
            yield time_key
            self.executor.drop_table("ti_locator_times")
            self._tables.remove("ti_locator_times")
            batch = None
        self._close_key_reader()

    def _count_group(self, path, index, projection, standard):
        request = self.requirement.request
        upper, upper_bindings = range_filter(request, include_start=False)
        target, target_bindings = range_filter(request)
        rows = targets = 0
        first = last = None
        for time_key in self._key_batches(path, index, projection, standard):
            sql = self.FIXED_SQL_STEPS["locate_count"].format(
                upper=upper, target=target, time_key=time_key)
            summary = self.executor.scalar(sql, upper_bindings + target_bindings)
            rows += summary["n"]
            targets += summary["targets"]
            if summary["n"]:
                if first is None:
                    first = summary["first_time"]
                last = summary["last_time"]
        return _Group(path, index, rows, targets, first, last)

    def _bounds(self, group, ranks, projection, standard):
        """Second key pass for at most two ordinal positions in this group."""
        found, preceding = {}, 0
        upper, bindings = range_filter(self.requirement.request, include_start=False)
        target, target_bindings = range_filter(self.requirement.request)
        for time_key in self._key_batches(group.path, group.index, projection, standard):
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
        if set(found) != set(ranks):
            raise SourceContractError("The second key read could not reproduce the selected boundary")
        return found

    def _select(self, paths, contract, projection, standard):
        request, history = self.requirement.request, self.requirement.history
        maximum = self.source._config.max_input_rows
        groups, rows, targets = [], 0, 0
        candidates_exhausted = False
        complete = False
        # Paths hold only partition descriptions. Older footers are opened only
        # if the newer groups did not already provide the necessary history.
        for path_index in range(len(paths) - 1, -1, -1):
            path = paths[path_index]
            metadata = self._open_metadata(path, contract, projection)
            for index in range(metadata.num_row_groups - 1, -1, -1):
                self.control.check_active()
                group_metadata = metadata.row_group(index)
                if not self._may_match(group_metadata, projection):
                    continue
                self._check_group_bytes(group_metadata, projection)
                group = self._count_group(path, index, projection, standard)
                if group.rows:
                    groups.append(group)
                    rows += group.rows
                    targets += group.targets
                target_known = targets >= request.limit or group.rows > group.targets
                actual = min(targets, request.limit)
                needs_origin = history.requires_source_origin or (
                    target_known and history.warmup_rows + actual > maximum)
                if needs_origin and rows > maximum:
                    raise ResourceLimitError("The required warmup cannot fit without reaching the source origin")
                if target_known and (actual == 0 or (
                        not needs_origin and rows >= actual + history.warmup_rows)):
                    complete = True
                    candidates_exhausted = path_index == 0 and index == 0
                    break
            self._close_metadata()
            metadata = group_metadata = None
            if complete:
                break
        else:
            candidates_exhausted = True
        actual = min(targets, request.limit)
        if not actual:
            return (), PriceReadSelection(None, None, None, None, 0, 0, candidates_exhausted, ())
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
        return selected_paths, selection

    def describe(self):
        if self._closed or self._started:
            raise SourceContractError("A source locator can only describe one request")
        self._started = True
        pa, _, _, _ = _arrow()
        try:
            request = self.requirement.request
            contract = price_contract(request)
            self.control.check_active()
            root = self.source._root()
            base = root / contract.relative_root
            if request.period.endswith("m"):
                base /= "freq=" + request.period[:-1]
                if request.security_type == "stock":
                    base /= "ts_code=" + request.ts_code
            paths = tuple(path for _, path in self.source._partition_paths(root, base, request, self.control))
            projection, standard = source_projection(contract, frozenset(), request.adjustment)
            self._stage_text = (Path(__file__).parents[2] / "technical_indicators/sources/sql/stage_input.sql").read_text()
            paths, selection = self._select(paths, contract, projection, standard)
            projection, standard = source_projection(contract, self.requirement.history.fields, request.adjustment)
            for path, indices in zip(paths, selection.row_groups):
                self.source._inspect(path, projection, contract.schema, self.control, self.context, row_groups=indices)
            conversion = contract.input_adjustment != request.adjustment
            factor_paths = self.source._partition_paths(root, root / "silver/quote/adj_factor",
                request, self.control, factors=True) if conversion and selection.target_rows else ()
            basis_rule = (("latest_available_factor" if request.adjustment == "qfq" else "earliest_available_factor")
                if conversion else ("latest_published_factor" if request.adjustment == "qfq" else None))
            return SourceDescription(
                source_id=contract.source_id, contract_version="1", input_adjustment=contract.input_adjustment,
                basis_rule=basis_rule, basis_date=None, basis_value=None,
                price_unit="CNY" if request.security_type == "stock" else "index_point",
                volume_unit=contract.volume_unit, amount_unit=contract.amount_unit, timezone="Asia/Shanghai",
                period_label_rule="trade_time" if contract.period_kind == "minute" else "period_start",
                history_origin_rule="earliest_available_formal_partition", available_through=None,
                supports_partial_period=contract.period_kind in ("week", "month"),
                supported_adjustment_paths=contract.adjustment_paths, converted=conversion,
                selection=selection, price_paths=paths, factor_paths=factor_paths,
                source_projection=projection, standard_projection=standard,
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
