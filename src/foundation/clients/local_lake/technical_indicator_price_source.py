"""Request-scoped, forward-only Lake prices; SQL owns every numeric conversion.

The existing page Readers are deliberately not used: their paging, independent
connections and row-quality checks do not implement the kernel input contract.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import deque
from contextlib import closing
from dataclasses import replace
from datetime import date
import os
from pathlib import Path
import re
import sys

from goldenshare_technical_indicators.calculation.calculation import SqlStep
from goldenshare_technical_indicators.configuration import KernelConfig
from goldenshare_technical_indicators.errors import (
    ResourceCleanupError, ResourceLimitError, SourceContractError, SourceReadError,
    TechnicalIndicatorError,
)
from goldenshare_technical_indicators.sources.contracts import SourceBatch, SourceDescription
from goldenshare_technical_indicators.sources.read_context import SourceReadContext

from ..technical_indicator_index_period import (
    INDEX_PERIOD_DATASETS, INDEX_PERIOD_KEYS, INDEX_PERIOD_PAGE_FIELDS,
    check_period_key, index_period_positions, period_bounds,
)
from ..technical_indicator_stock_daily import (
    dg_index_daily_origin, full_day_suspension, scheduled_open_days, scheduled_stock_days,
)
from ..technical_indicator_stock_period import STOCK_PERIOD_DATASETS, StockPeriodStream
from .technical_indicator_contracts import (
    FACTOR_SCHEMA,
)


_DATE_PART = re.compile(r"^trade_date=(\d{4}-\d{2}-\d{2})$")
_TABLE = re.compile(r"^ti_[a-z0-9_]+$")
_FORBIDDEN_ROOTS = (Path("/Volumes/datasource/data_lake_staging"),
                    Path("/Volumes/datasource/goldenshare-tushare-lake"))
_INDEX_PERIOD_PAGE_SCHEMA = (
    ("ts_code", "VARCHAR"), ("period_start_date", "DATE"), ("trade_date", "DATE"),
    ("pre_close", "DECIMAL(18,4)"), ("change_amount", "DECIMAL(18,4)"), ("pct_chg", "DECIMAL(12,4)"),
)


def _arrow():
    try:
        import pyarrow as pa
        import pyarrow.dataset as ds
        import pyarrow.fs as fs
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SourceContractError("The configured price source requires PyArrow") from exc
    return pa, ds, fs, pq


def _table_name(name):
    if not isinstance(name, str) or not _TABLE.fullmatch(name):
        raise SourceContractError("Source SQL requires a controlled internal table name")
    return name


def _matches_type(pa, actual, expected):
    types = {"VARCHAR": pa.string(), "DATE": pa.date32(), "TIMESTAMP": pa.timestamp("us"), "INTEGER": pa.int32(),
             "DOUBLE": pa.float64(), "DECIMAL(10,4)": pa.decimal128(10, 4),
             "DECIMAL(12,4)": pa.decimal128(12, 4), "DECIMAL(18,4)": pa.decimal128(18, 4),
             "DECIMAL(20,4)": pa.decimal128(20, 4), "DECIMAL(20,6)": pa.decimal128(20, 6),
             "DECIMAL(20,7)": pa.decimal128(20, 7)}
    return actual == types[expected]


def _stock_batches(reader, columns, ts_code, control, *, batch_rows, row_groups=None):
    """Read one symbol from an already-open Parquet reader."""
    import pyarrow.compute as pc

    control.check_active()
    for batch in reader.iter_batches(batch_size=batch_rows, row_groups=row_groups,
                                     columns=columns, use_threads=False):
        control.check_active()
        selected = batch.filter(pc.equal(batch.column("ts_code"), ts_code))
        if selected.num_rows:
            yield selected.select(columns)
        control.check_active()


class LakeTechnicalIndicatorPriceSource:
    """Shareable immutable configuration, with no mutable request/read state."""

    def __init__(self, config: KernelConfig):
        _arrow()  # Capability assembly fails clearly, never downloads a dependency.
        self._config = config

    def _root(self):
        if not self._config.goldenshare_lake_root:
            raise SourceContractError("The Lake root has not been configured")
        try:
            root = Path(self._config.goldenshare_lake_root).expanduser().resolve()
            if any(root == old or root.is_relative_to(old) for old in _FORBIDDEN_ROOTS):
                raise SourceContractError("A retired Lake root or staging cannot supply prices")
            if not root.is_dir():
                raise SourceReadError("The configured Lake root is not readable")
            return root
        except OSError as exc:
            raise SourceReadError("The configured Lake root cannot be inspected") from exc

    @staticmethod
    def _safe_path(root, path):
        resolved = path.resolve()
        if resolved != path or not resolved.is_relative_to(root):
            raise SourceContractError("The declared Lake source path contains a symbolic link or escapes its root")
        return resolved

    def _partition_paths(self, root, requirement, control):
        through = requirement.end.date() if requirement.period.endswith("m") else requirement.end
        start = dg_index_daily_origin(requirement.ts_code) if requirement.target.dataset_id == "index_daily" else None
        return tuple(path for _, path in self._dated_partitions(root, requirement.target, through, control, start=start))

    def _dated_partitions(self, root, target, through, control, *, start=None):
        template = Path(target.location["path_template"])
        base = template.parent.parent
        self._safe_path(root, base)
        control.check_active()
        result = []
        try:
            with os.scandir(base) as entries:
                for entry in entries:
                    control.check_active()
                    match = _DATE_PART.fullmatch(entry.name)
                    if match is None:
                        continue
                    partition_day = date.fromisoformat(match.group(1))
                    if partition_day <= through and (start is None or partition_day >= start):
                        path = Path(str(template).replace("{trade_date}", partition_day.isoformat()))
                        if path.is_file():
                            result.append((partition_day, path))
            return tuple(sorted(result))
        except TechnicalIndicatorError:
            raise
        except (OSError, ValueError) as exc:
            raise SourceReadError("The declared source partitions cannot be enumerated") from exc

    def daily_page_dates(self, dataset, ts_code, *, start, end, limit, control, read_context, before=None):
        root = self._root()
        target = self._config.resolve_dataset_location(dataset)
        dates = []
        for day, _ in reversed(self._dated_partitions(root, target, end, control, start=start)):
            if before is not None and day >= before:
                continue
            rows = self.daily_rows(dataset, ts_code, (day,), ("trade_date",),
                                   control=control, read_context=read_context)
            if day in rows:
                dates.append(day)
                if len(dates) == limit:
                    break
        return tuple(reversed(dates))

    def daily_rows(self, dataset, ts_code, dates, fields, *, control, read_context):
        root = self._root()
        target = self._config.resolve_dataset_location(dataset)
        columns = ("trade_date", *(field for field in fields if field != "trade_date"))
        result = {}
        for day in dates:
            control.check_active()
            if dataset == "stock_daily_basic":
                path = Path(target.location["path_template"].replace("{trade_date}", day.isoformat()))
                try:
                    self._safe_path(root, path).stat()
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise SourceReadError("Cannot inspect stock daily basic partition") from exc
                expected = day.strftime("%Y%m%d")
            else:
                expected = day
            rows = self._fact_rows(root, dataset, columns, [("ts_code", "=", ts_code)],
                                   control, read_context, day=day)
            if len(rows) > 1 or (rows and rows[0][0] != expected):
                raise SourceContractError(f"Unexpected daily rows in {dataset} for {ts_code} on {day}")
            if rows:
                result[day] = dict(zip(columns, rows[0]))
        return result

    def index_period_page(self, session, period, ts_code, *, start, end, limit, control):
        _, ds, _, _ = _arrow()
        within_bounds = (ds.field("period_start_date") <= end) & (ds.field("trade_date") <= end)
        if start is not None:
            within_bounds &= ((ds.field("period_start_date") >= period_bounds(start, period)[0])
                              & (ds.field("trade_date") >= start))
        with closing(self._index_period_rows(period, ts_code, INDEX_PERIOD_PAGE_FIELDS, control,
                                             bounds=within_bounds)) as rows:
            return list(reversed(deque(rows, maxlen=limit)))

    def index_period_boundary(self, session, period, ts_code, *, latest, control):
        with closing(self._index_period_rows(period, ts_code, INDEX_PERIOD_KEYS, control)) as rows:
            if latest:
                return next(iter(deque(rows, maxlen=1)), None)
            return next(rows, None)

    def _index_period_rows(self, period, ts_code, columns, control, *, bounds=None):
        _, ds, fs, _ = _arrow()
        root = self._root()
        target = self._config.resolve_dataset_location(INDEX_PERIOD_DATASETS[period])
        path = self._safe_path(root, Path(target.location["path_template"]))
        read_context = SourceReadContext(self._config)
        self._inspect(path, columns, _INDEX_PERIOD_PAGE_SCHEMA, control, read_context)
        filters = ds.field("ts_code") == ts_code
        if bounds is not None:
            filters &= bounds
        last_period = None
        try:
            fragment = ds.ParquetFileFormat().make_fragment(str(path), filesystem=fs.LocalFileSystem())
            scanner = ds.Scanner.from_fragment(
                fragment, columns=list(columns), filter=filters, batch_size=self._config.batch_rows,
                batch_readahead=0, fragment_readahead=0, use_threads=False, cache_metadata=False,
                fragment_scan_options=ds.ParquetFragmentScanOptions(pre_buffer=False, use_buffered_stream=False),
            )
            with scanner.to_reader() as reader:
                for batch in reader:
                    control.check_active()
                    values = tuple(batch.column(name) for name in columns)
                    for index in range(batch.num_rows):
                        row = dict(zip(columns, (column[index].as_py() for column in values), strict=True))
                        label = check_period_key((row["period_start_date"], row["trade_date"]), period)
                        if last_period is not None and label <= last_period:
                            raise SourceContractError("DG index period rows are duplicated or out of order")
                        last_period = label
                        yield row
            control.check_active()
        except TechnicalIndicatorError:
            raise
        except (OSError, ValueError) as exc:
            raise SourceReadError(f"Cannot read {target.dataset_id} for {ts_code}") from exc

    def _inspect(self, path, projection, schema, control, read_context, *, row_groups=None):
        """Footer-only protection; never reads or audits individual values."""
        pa, _, _, pq = _arrow()
        control.check_active()
        reader = None
        try:
            read_context.record_file(path, path.stat().st_size)
            control.check_active()
            reader = pq.ParquetFile(path)
            actual = reader.schema_arrow
            expected = dict(schema)
            for name in projection:
                if name not in actual.names or name not in expected or not _matches_type(pa, actual.field(name).type, expected[name]):
                    raise SourceContractError("The projected source schema does not match its declared contract")
            metadata = reader.metadata
            for group_index in (range(metadata.num_row_groups) if row_groups is None else row_groups):
                control.check_active()
                group = metadata.row_group(group_index)
                projected_bytes = sum(group.column(i).total_uncompressed_size
                                      for i in range(group.num_columns)
                                      if group.column(i).path_in_schema in projection)
                if projected_bytes > self._config.max_projected_row_group_bytes:
                    raise ResourceLimitError(
                        f"Projected row group bytes {projected_bytes} exceed initial protection "
                        f"{self._config.max_projected_row_group_bytes}")
            control.check_active()
        except TechnicalIndicatorError:
            raise
        except MemoryError as exc:
            raise ResourceLimitError("Source metadata exceeded available memory") from exc
        except Exception as exc:
            raise SourceReadError("Source metadata cannot be read") from exc
        finally:
            if reader is not None:
                primary = sys.exc_info()[1]
                try:
                    reader.close()
                except Exception as exc:
                    if primary is not None:
                        primary.add_note(f"Source metadata cleanup also failed: {type(exc).__name__}")
                    else:
                        raise ResourceCleanupError("Source metadata handle did not close") from exc

    def create_locator(self, executor, requirement, *, read_context):
        from .technical_indicator_price_locator import LakePriceLocator
        return LakePriceLocator(self, executor, requirement, read_context=read_context)

    def open(self, executor, description, requirement, *, read_context):
        if requirement.target.dataset_id in STOCK_PERIOD_DATASETS.values():
            return StockPeriodStream(description, requirement, read_context, executor.control)
        return _LakePriceStream(description, requirement, executor.control, read_context)

    def _fact_rows(self, root, identifier, columns, filters, control, read_context, *, day=None):
        target = self._config.resolve_dataset_location(identifier)
        path = target.location["path_template"]
        if day is not None:
            path = path.replace("{trade_date}", day.isoformat())
        path = self._safe_path(root, Path(path))
        _, _, _, pq = _arrow()
        try:
            control.check_active()
            read_context.record_file(path, path.stat().st_size)
            with pq.ParquetFile(path) as source:
                for group in range(source.metadata.num_row_groups):
                    footer = source.metadata.row_group(group)
                    projected = sum(footer.column(i).total_uncompressed_size for i in range(footer.num_columns)
                                    if footer.column(i).path_in_schema in columns)
                    if projected > self._config.max_projected_row_group_bytes:
                        raise ResourceLimitError("Projected stock fact row group exceeds its byte limit")
                if identifier == "stock_suspend_daily":
                    ((_, _, ts_code),) = filters
                    projected_columns = ("ts_code", *columns)
                    for name in projected_columns:
                        source.schema_arrow.field(name)
                    return [tuple(row[name] for name in columns)
                            for batch in _stock_batches(source, projected_columns, ts_code, control,
                                                        batch_rows=self._config.batch_rows)
                            for row in batch.to_pylist()]
            table = pq.read_table(path, columns=list(columns), filters=filters, partitioning=None)
            control.check_active()
            return [tuple(row[name] for name in columns) for row in table.to_pylist()]
        except TechnicalIndicatorError:
            raise
        except Exception as exc:
            raise SourceReadError(f"Cannot read daily facts from {identifier}") from exc

    def expected_positions(self, requirement, selection, *, read_context, control):
        if requirement.period == "day" and requirement.latest_rows is not None:
            for batch in read_context.source_state:
                yield from batch.column("trade_date").to_pylist()
            return
        if requirement.target.dataset_id in STOCK_PERIOD_DATASETS.values():
            yield from read_context.source_state.positions
            return
        root = self._root()
        if requirement.period in INDEX_PERIOD_DATASETS:
            dates = read_context.source_state
            calendar = self._fact_rows(root, "trade_calendar", ("exchange", "trade_date", "is_open"),
                [("exchange", "=", "SSE"), ("trade_date", ">=", dates.calendar_start),
                 ("trade_date", "<=", dates.calendar_end)], control, read_context)
            yield from index_period_positions(sorted((day, flag) for _, day, flag in calendar), dates,
                                              requirement.period)
            return
        start, end = min(requirement.start, selection.read_start), requirement.end
        index = requirement.target.dataset_id == "index_daily"
        if index:
            origin = dg_index_daily_origin(requirement.ts_code)
            start = origin if selection.reached_source_origin else max(start, origin)
        calendar = self._fact_rows(root, "trade_calendar", ("trade_date", "is_open"),
                                   [("exchange", "=", "SSE"), ("trade_date", ">=", start),
                                    ("trade_date", "<=", end)], control, read_context)
        if index:
            yield from scheduled_open_days(sorted(calendar), start, end)
            return
        lifecycle = self._fact_rows(root, "stock_lifecycle", ("list_date", "delist_date"),
                                    [("ts_code", "=", requirement.ts_code)], control, read_context)
        for day in scheduled_stock_days(sorted(calendar), lifecycle, start, end):
            records = self._fact_rows(root, "stock_suspend_daily", ("trade_date", "suspend_type", "suspend_timing"),
                                      [("ts_code", "=", requirement.ts_code)], control, read_context, day=day)
            if any(stamp != day for stamp, _, _ in records):
                raise SourceContractError("Stock suspension facts do not match their partition date")
            if not full_day_suspension((kind, timing) for _, kind, timing in records):
                yield day

    def prepare_basis(self, executor, description, requirement, *, table_name, read_context):
        name = _table_name(table_name)
        if not description.converted:
            return description
        candidates = description.factor_paths if requirement.target_adjustment == "hfq" else reversed(description.factor_paths)
        for day, path in candidates:
            self._inspect(path, tuple(name for name, _ in FACTOR_SCHEMA), FACTOR_SCHEMA, executor.control, read_context)
            stats = executor.execute(SqlStep("prepare_basis", f"""CREATE OR REPLACE TEMP TABLE {name} AS
                SELECT trade_date AS basis_date, CAST(adj_factor AS DOUBLE) AS basis_value,
                       count(*) OVER () AS basis_rows
                FROM read_parquet(?, hive_partitioning=false) WHERE ts_code=?
                ORDER BY trade_date {'ASC' if requirement.target_adjustment == 'hfq' else 'DESC'} LIMIT 1""",
                (str(path), requirement.ts_code), (), (name,), 0))
            if stats.output_rows:
                basis = executor.scalar(
                    f"SELECT struct_pack(basis_date:=basis_date,basis_value:=basis_value,basis_rows:=basis_rows) FROM {name}"
                )
                if basis["basis_rows"] != 1 or basis["basis_date"] != day:
                    raise SourceContractError(f"Invalid adjustment factor basis partition for {day}")
                resolved = replace(description, basis_date=basis["basis_date"], basis_value=basis["basis_value"])
                read_context.remember_basis(resolved, requirement, path)
                return resolved
        raise SourceContractError("The declared daily conversion has no available basis row")

    def prepare_factors(self, executor, description, requirement, trade_dates, *, table_name, read_context):
        name = _table_name(table_name)
        selected_dates = frozenset(trade_dates)
        paths = description.factor_paths
        if trade_dates:
            first = bisect_left(paths, trade_dates[0], key=lambda item: item[0])
            last = bisect_right(paths, trade_dates[-1], key=lambda item: item[0])
            selected = tuple(path for day, path in paths[first:last] if day in selected_dates)
        else:
            selected = ()
        basis = read_context.reusable_basis(description, requirement, selected_dates, selected)
        unread = tuple(path for path in selected if basis is None or path != basis[0])
        for path in unread:
            self._inspect(path, tuple(field for field, _ in FACTOR_SCHEMA), FACTOR_SCHEMA, executor.control, read_context)
        if unread and trade_dates:
            paths_sql = "[" + ",".join("?" for _ in unread) + "]"
            dates_sql = ",".join("?" for _ in trade_dates)
            select_sql = f"""SELECT trade_date, CAST(adj_factor AS DOUBLE) AS adj_factor
                FROM read_parquet({paths_sql}, hive_partitioning=false) WHERE ts_code=? AND trade_date IN ({dates_sql})"""
            bindings = (*map(str, unread), requirement.ts_code, *trade_dates)
            if basis is not None:
                select_sql += " UNION ALL SELECT CAST(? AS DATE), CAST(? AS DOUBLE)"
                bindings += (basis[1], basis[2])
            sql = f"CREATE TEMP TABLE {name} AS " + select_sql
        elif basis is not None:
            sql = f"CREATE TEMP TABLE {name} AS SELECT CAST(? AS DATE) trade_date, CAST(? AS DOUBLE) adj_factor"
            bindings = (basis[1], basis[2])
        else:
            sql = f"CREATE TEMP TABLE {name} AS SELECT CAST(NULL AS DATE) trade_date, CAST(NULL AS DOUBLE) adj_factor WHERE false"
            bindings = ()
        executor.execute(SqlStep("prepare_factors", sql, bindings, (), (name,), 0))


def _file_version(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


class _LakePriceStream:
    """Fill each delivery across files; retain only one already-read remainder."""

    def __init__(self, description, requirement, control, read_context):
        self._description, self._requirement = description, requirement
        self._control, self._context = control, read_context
        self._period_dates = read_context.source_state if requirement.period in INDEX_PERIOD_DATASETS else None
        self._files = iter(description.price_paths)
        self._row_groups = dict(zip(description.price_paths, description.selection.row_groups))
        self._fragment = self._scanner = self._reader = self._current_batch = None
        self._pending_batch = self._current_path = None
        self._exhausted = self._closed = self._failed = False
        self._delivered = 0
        batches = read_context.retained_price_batches
        read_context.retained_price_batches = None
        if requirement.period == "day" and (
            requirement.target.dataset_id == "stock_daily" or requirement.latest_rows is not None
        ):
            batches = read_context.source_state
            read_context.source_state = None
        if batches is not None:
            pa, _, _, _ = _arrow()
            self._reader = pa.RecordBatchReader.from_batches(batches[0].schema, batches)
            self._files = iter(())

    def _check_period_file(self):
        if self._period_dates is not None and self._period_dates.file_version is not None and (
                _file_version(self._description.price_paths[0]) != self._period_dates.file_version):
            raise SourceReadError("The index period file changed during the request")

    def _open_file(self, path):
        pa, ds, fs, _ = _arrow()
        self._check_period_file()
        self._current_path = path
        predicate = ds.field("ts_code") == self._requirement.ts_code
        selection = self._description.selection
        if self._period_dates is not None:
            predicate &= ds.field("period_start_date") >= self._period_dates.keys[0][0]
            predicate &= ds.field("period_start_date") <= self._period_dates.keys[-1][0]
        elif self._requirement.period.endswith("m"):
            predicate &= ds.field("trade_time") >= selection.read_start.replace(tzinfo=None)
            predicate &= ds.field("trade_time") <= selection.read_end.replace(tzinfo=None)
        else:
            predicate &= ds.field("trade_date") >= selection.read_start
            predicate &= ds.field("trade_date") <= selection.read_end
        self._fragment = ds.ParquetFileFormat().make_fragment(
            str(path), filesystem=fs.LocalFileSystem(), row_groups=list(self._row_groups[path]))
        self._scanner = ds.Scanner.from_fragment(
            self._fragment, columns=list(self._description.source_projection), filter=predicate,
            batch_size=self._requirement.batch_rows, batch_readahead=0, fragment_readahead=0,
            fragment_scan_options=ds.ParquetFragmentScanOptions(pre_buffer=False, use_buffered_stream=False),
            use_threads=False, cache_metadata=False)
        self._reader = self._scanner.to_reader()

    def _close_reader(self):
        if self._reader is not None:
            self._reader.close()
        self._reader = self._scanner = self._fragment = None
        self._current_path = None

    def _copy_rows(self, batch, offset, length):
        """Copy selected columns so a small slice does not retain a file buffer."""
        pa, _, _, _ = _arrow()
        selected = columns = column = result = None
        try:
            self._control.check_active()
            selected = batch.slice(offset, length)
            columns = []
            for column in selected.columns:
                self._control.check_active()
                columns.append(pa.concat_arrays([column]))
                self._control.check_active()
            result = pa.RecordBatch.from_arrays(columns, schema=selected.schema)
            self._control.check_active()
            return result
        except MemoryError as exc:
            raise ResourceLimitError("Copying the source batch exceeded available memory") from exc
        except (pa.ArrowInvalid, pa.ArrowTypeError, TypeError, ValueError) as exc:
            raise SourceContractError("Source columns could not form a compact batch") from exc
        finally:
            batch = selected = columns = column = result = None

    def next_batch(self, max_rows):
        if self._closed or self._failed:
            raise SourceContractError("A closed or failed source stream cannot advance")
        if self._current_batch is not None:
            raise SourceContractError("The current source batch must be released before advancing")
        if max_rows != self._requirement.batch_rows:
            raise SourceContractError("The source batch size is fixed for the request")
        if self._exhausted:
            return None
        batch = piece = assembled = result = None
        pieces = []
        assembled_rows = 0
        try:
            while assembled_rows < max_rows:
                self._control.check_active()
                if self._pending_batch is not None:
                    # This compact remainder was charged on its first read.
                    piece, self._pending_batch = self._pending_batch, None
                    pieces.append(piece)
                    assembled_rows += piece.num_rows
                    piece = None
                    continue
                if self._reader is None:
                    path = next(self._files, None)
                    if path is None:
                        self._exhausted = True
                        break
                    self._open_file(path)
                    self._control.check_active()
                try:
                    batch = self._reader.read_next_batch()
                except StopIteration:
                    try:
                        self._close_reader()
                    except Exception as exc:
                        raise ResourceCleanupError("The completed source reader did not close") from exc
                    continue
                self._control.check_active()
                if not batch.num_rows:
                    batch = None
                    continue
                self._context.record_price_rows(batch.num_rows)
                if batch.num_rows > max_rows:
                    raise SourceContractError("The file reader exceeded the request batch size")
                take = min(max_rows - assembled_rows, batch.num_rows)
                piece = self._copy_rows(batch, 0, take)
                if take < batch.num_rows:
                    self._pending_batch = self._copy_rows(batch, take, batch.num_rows-take)
                pieces.append(piece)
                assembled_rows += take
                batch = piece = None
            self._check_period_file()
            if not assembled_rows:
                return None
            self._control.check_active()
            if len(pieces) == 1:
                assembled = pieces[0]
            else:
                pa, _, _, _ = _arrow()
                try:
                    assembled = pa.concat_batches(pieces)
                except MemoryError as exc:
                    raise ResourceLimitError("Combining source batches exceeded available memory") from exc
                except (pa.ArrowInvalid, pa.ArrowTypeError, TypeError, ValueError) as exc:
                    raise SourceContractError("Source batch schemas could not be combined") from exc
            pieces.clear()
            self._control.check_active()
            if self._period_dates is not None:
                keys = list(zip(assembled.column("period_start_date").to_pylist(),
                                assembled.column("trade_date").to_pylist(), strict=True))
                self._period_dates.check_delivery(self._delivered, keys)
            result = SourceBatch(assembled, self._delivered+1,
                                 self._delivered+assembled_rows, None, assembled_rows,
                                 self._context.source_files, self._context.source_file_bytes)
            self._current_batch = assembled
            self._delivered += assembled_rows
            return result
        except BaseException as exc:
            self._failed = True
            self._current_batch = self._pending_batch = None
            pieces.clear()
            batch = piece = assembled = result = None
            self._files = iter(())
            try:
                self._close_reader()
            except BaseException as cleanup:
                exc.add_note(f"Source reader cleanup failed: {type(cleanup).__name__}: {cleanup}")
            if isinstance(exc, TechnicalIndicatorError) or not isinstance(exc, Exception):
                raise
            if isinstance(exc, MemoryError):
                raise ResourceLimitError("The source reader exceeded available memory") from exc
            raise SourceReadError("The source stream did not complete normally") from exc
        finally:
            pieces.clear()
            batch = piece = assembled = result = None

    def release_current_batch(self):
        self._current_batch = None

    def close(self):
        if self._closed:
            return
        self.release_current_batch()
        self._pending_batch = None
        self._files = iter(())
        try:
            self._close_reader()
        except Exception as exc:
            self._failed = True
            raise ResourceCleanupError("The source reader did not close") from exc
        self._closed = True
