"""Request-scoped, forward-only Lake prices; SQL owns every numeric conversion.

The existing page Readers are deliberately not used: their paging, independent
connections and row-quality checks do not implement the kernel input contract.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
import os
from pathlib import Path
import re
import sys

from src.foundation.technical_indicators.calculation.calculation import SqlStep
from src.foundation.technical_indicators.configuration import KernelConfig
from src.foundation.technical_indicators.errors import (
    ResourceCleanupError, ResourceLimitError, SourceContractError, SourceReadError,
    TechnicalIndicatorError,
)
from src.foundation.technical_indicators.sources.contracts import SourceBatch, SourceDescription

from .technical_indicator_contracts import (
    FACTOR_SCHEMA, LakePriceContract, price_contract, source_capabilities, source_projection,
)


_DATE_PART = re.compile(r"^(?:trade_date|week_end)=(\d{4}-\d{2}-\d{2})$")
_YEAR_PART = re.compile(r"^year=(\d{4})$")
_MONTH_PART = re.compile(r"^month=(\d{4}-\d{2})$")
_TABLE = re.compile(r"^ti_[a-z0-9_]+$")
_FORBIDDEN_ROOTS = (Path("/Volumes/datasource/data_lake_staging"),
                    Path("/Volumes/datasource/goldenshare-tushare-lake"))


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
    types = {"VARCHAR": pa.string(), "DATE": pa.date32(), "TIMESTAMP": pa.timestamp("us"),
             "DOUBLE": pa.float64(), "DECIMAL(18,4)": pa.decimal128(18, 4),
             "DECIMAL(20,4)": pa.decimal128(20, 4)}
    return actual == types[expected]


class LakeTechnicalIndicatorPriceSource:
    """Shareable immutable configuration, with no mutable request/read state."""

    def __init__(self, config: KernelConfig):
        _arrow()  # Capability assembly fails clearly, never downloads a dependency.
        self._config = config

    @property
    def capabilities(self):
        return source_capabilities()

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

    def _partition_paths(self, root, base, request, control, *, factors=False):
        self._safe_path(root, base)
        control.check_active()
        if not base.exists():
            return ()
        result = []
        try:
            with os.scandir(base) as entries:
                for entry in entries:
                    control.check_active()
                    name = entry.name
                    pattern = _DATE_PART if factors or request.period not in ("month",) else _MONTH_PART
                    if request.period.endswith("m") and request.security_type == "stock" and not factors:
                        pattern = _YEAR_PART
                    match = pattern.fullmatch(name)
                    if match is None:
                        continue
                    label = match.group(1)
                    if pattern is _YEAR_PART:
                        period_start = date(int(label), 1, 1)
                    elif pattern is _MONTH_PART:
                        period_start = date.fromisoformat(label + "-01")
                    else:
                        period_start = date.fromisoformat(label)
                        if request.period == "week" and not factors:
                            from datetime import timedelta
                            period_start -= timedelta(days=period_start.weekday())
                    end = request.end.date() if isinstance(request.end, datetime) else request.end
                    before = request.before.date() if isinstance(request.before, datetime) else request.before
                    # Factors include future/earliest candidates: display paging must
                    # never select the daily adjustment denominator.
                    if not factors:
                        if end is not None and period_start > end:
                            continue
                        if before is not None and (period_start > before or
                                (period_start == before and not request.period.endswith("m"))):
                            continue
                    path = self._safe_path(root, base / name / "part-000.parquet")
                    if path.is_file():
                        result.append((period_start, path))
                    control.check_active()
            return tuple(sorted(result))
        except TechnicalIndicatorError:
            raise
        except (OSError, ValueError) as exc:
            raise SourceReadError("The declared source partitions cannot be enumerated") from exc

    def _inspect(self, path, projection, schema, control, read_context):
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
            for group_index in range(metadata.num_row_groups):
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

    def describe(self, request, requirement, *, control, read_context):
        contract = price_contract(request)
        control.check_active()
        root = self._root()
        control.check_active()
        base = root / contract.relative_root
        if request.period.endswith("m"):
            base /= "freq=" + request.period[:-1]
            if request.security_type == "stock":
                base /= "ts_code=" + request.ts_code
        price_paths = tuple(path for _, path in self._partition_paths(root, base, request, control))
        projection, standard = source_projection(contract, requirement.history.fields, request.adjustment)
        for path in price_paths:
            self._inspect(path, projection, contract.schema, control, read_context)
        conversion = contract.input_adjustment != request.adjustment
        factor_paths = self._partition_paths(root, root / "silver/quote/adj_factor", request, control, factors=True) if conversion else ()
        basis_rule = ("latest_available_factor" if request.adjustment == "qfq" else "earliest_available_factor") if conversion else (
            "latest_published_factor" if request.adjustment == "qfq" else None)
        return SourceDescription(
            source_id=contract.source_id, contract_version="1", input_adjustment=contract.input_adjustment,
            basis_rule=basis_rule, basis_date=None, basis_value=None, price_unit="CNY" if request.security_type == "stock" else "index_point",
            volume_unit=contract.volume_unit, amount_unit=contract.amount_unit, timezone="Asia/Shanghai",
            period_label_rule="trade_time" if contract.period_kind == "minute" else "period_start",
            history_origin_rule="earliest_available_formal_partition", available_through=None,
            supports_partial_period=contract.period_kind in ("week", "month"),
            supported_adjustment_paths=contract.adjustment_paths, converted=conversion,
            price_paths=price_paths, factor_paths=factor_paths,
            source_projection=projection, standard_projection=standard,
        )

    def open(self, executor, description, requirement, *, read_context):
        return _LakePriceStream(description, requirement, executor.control, read_context)

    def prepare_basis(self, executor, description, requirement, *, table_name, read_context):
        name = _table_name(table_name)
        if not description.converted:
            return description
        candidates = description.factor_paths if requirement.request.adjustment == "hfq" else reversed(description.factor_paths)
        for _, path in candidates:
            self._inspect(path, tuple(name for name, _ in FACTOR_SCHEMA), FACTOR_SCHEMA, executor.control, read_context)
            stats = executor.execute(SqlStep("prepare_basis", f"""CREATE OR REPLACE TEMP TABLE {name} AS
                SELECT trade_date AS basis_date, CAST(adj_factor AS DOUBLE) AS basis_value
                FROM read_parquet(?, hive_partitioning=false) WHERE ts_code=?
                ORDER BY trade_date {'ASC' if requirement.request.adjustment == 'hfq' else 'DESC'} LIMIT 1""",
                (str(path), requirement.request.ts_code), (), (name,), 0))
            if stats.output_rows:
                basis = executor.scalar(f"SELECT struct_pack(basis_date:=basis_date,basis_value:=basis_value) FROM {name}", ())
                return replace(description, basis_date=basis["basis_date"], basis_value=basis["basis_value"])
        raise SourceContractError("The declared daily conversion has no available basis row")

    def prepare_factors(self, executor, description, requirement, trade_dates, *, table_name, read_context):
        name = _table_name(table_name)
        selected_dates = frozenset(trade_dates)
        selected = tuple(path for day, path in description.factor_paths if day in selected_dates)
        for path in selected:
            self._inspect(path, tuple(field for field, _ in FACTOR_SCHEMA), FACTOR_SCHEMA, executor.control, read_context)
        if selected and trade_dates:
            paths_sql = "[" + ",".join("?" for _ in selected) + "]"
            dates_sql = ",".join("?" for _ in trade_dates)
            sql = f"""CREATE TEMP TABLE {name} AS SELECT trade_date, CAST(adj_factor AS DOUBLE) AS adj_factor
                FROM read_parquet({paths_sql}, hive_partitioning=false) WHERE ts_code=? AND trade_date IN ({dates_sql})"""
            bindings = (*map(str, selected), requirement.request.ts_code, *trade_dates)
        else:
            sql = f"CREATE TEMP TABLE {name} AS SELECT CAST(NULL AS DATE) trade_date, CAST(NULL AS DOUBLE) adj_factor WHERE false"
            bindings = ()
        executor.execute(SqlStep("prepare_factors", sql, bindings, (), (name,), 0))


class _LakePriceStream:
    """Exactly one file reader and one outstanding Arrow batch per request."""

    def __init__(self, description, requirement, control, read_context):
        self._description, self._requirement = description, requirement
        self._control, self._context = control, read_context
        self._files = iter(description.price_paths)
        self._fragment = self._scanner = self._reader = self._current_batch = None
        self._exhausted = self._closed = self._failed = False
        self._delivered = 0

    def _open_file(self, path):
        pa, ds, fs, _ = _arrow()
        request = self._requirement.request
        predicate = ds.field("ts_code") == request.ts_code
        if request.period.endswith("m"):
            if request.end is not None:
                predicate &= ds.field("trade_time") <= pa.scalar(request.end.replace(tzinfo=None), type=pa.timestamp("us"))
            if request.before is not None:
                predicate &= ds.field("trade_time") < pa.scalar(request.before.replace(tzinfo=None), type=pa.timestamp("us"))
        elif request.period == "day":
            if request.end is not None:
                predicate &= ds.field("trade_date") <= request.end
            if request.before is not None:
                predicate &= ds.field("trade_date") < request.before
        # Week/month upper bounds select candidate partitions; source Friday
        # labels are never compared to a Tuesday request in Arrow.
        self._fragment = ds.ParquetFileFormat().make_fragment(str(path), filesystem=fs.LocalFileSystem())
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

    def next_batch(self, max_rows):
        if self._closed or self._failed:
            raise SourceContractError("A closed or failed source stream cannot advance")
        if self._current_batch is not None:
            raise SourceContractError("The current source batch must be released before advancing")
        if max_rows != self._requirement.batch_rows:
            raise SourceContractError("The source batch size is fixed for the request")
        if self._exhausted:
            return None
        batch = None
        try:
            while True:
                self._control.check_active()
                if self._reader is None:
                    path = next(self._files, None)
                    if path is None:
                        self._exhausted = True
                        return None
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
                    del batch
                    continue
                self._context.record_price_rows(batch.num_rows)
                first = self._delivered + 1
                self._delivered += batch.num_rows
                self._current_batch = batch
                return SourceBatch(batch, first, self._delivered, None, batch.num_rows,
                                   self._context.source_files, self._context.source_file_bytes)
        except TechnicalIndicatorError:
            batch = None
            self._failed = True
            raise
        except Exception as exc:
            batch = None
            self._failed = True
            raise SourceReadError("The source stream did not complete normally") from exc

    def release_current_batch(self):
        self._current_batch = None

    def close(self):
        if self._closed:
            return
        self.release_current_batch()
        try:
            self._close_reader()
        except Exception as exc:
            self._failed = True
            raise ResourceCleanupError("The source reader did not close") from exc
        self._files = iter(())
        self._closed = True
