"""LLD §06.8 and D2 correction: real temporary Arrow/SQL, no formal-data access.

The literal minute schema follows DG's GOLD_STK_MINS_QFQ_SCHEMA and the existing
Foundation major_index_mins_contract. Period SQL uses in-memory Arrow with
literal producer types; it does not claim weekly/monthly file integration.
The original tests use three tiny canonical files.  The separately selected
D2 correction nodes reuse the approved 32768-row diagnostic fixture and create
four minute, 21 daily and 21 factor temporary Parquet files once, according to
the approved 10022 price / 21 factor record budget.  Source/schema and SQL are
real; isolated stop signals do not claim full cancellation or formal-Lake proof.
"""

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.foundation.config.settings import Settings
from src.foundation.clients.local_lake.technical_indicator_contracts import price_contract, source_projection
from src.foundation.clients.local_lake.technical_indicator_price_source import LakeTechnicalIndicatorPriceSource
from src.foundation.technical_indicators import CalculationInstance, CalculationRequest
from src.foundation.technical_indicators.calculation.history import HistoryRequirement
from src.foundation.technical_indicators.configuration import KernelConfig
from src.foundation.technical_indicators.errors import (
    CalculationCancelledError, ResourceCleanupError, ResourceLimitError,
    SourceContractError, SourceUnsupportedError,
)
from src.foundation.technical_indicators.sources.contracts import PriceReadSelection, ReadRequirement
from src.foundation.technical_indicators.sources.read_context import SourceReadContext


def _config(root, **kwargs):
    config = KernelConfig.from_settings(Settings(_env_file=None))
    return replace(config, goldenshare_lake_root=str(root), batch_rows=2,
                   max_input_rows=1500000, max_source_files=5000,
                   max_projected_row_group_bytes=33554432, **kwargs)


class _Control:
    """Only stop signaling is isolated; real Arrow/DuckDB are not replaced."""
    stopped = False
    cleanup_ready = False
    clock = staticmethod(__import__("time").monotonic)

    def _note_sql_returned(self):
        pass

    def check_active(self):
        if self.stopped:
            raise CalculationCancelledError("literal test cancellation")


def _request(**kwargs):
    return CalculationRequest(**(dict(
        security_type="index", ts_code="000001.SH", period="1m", adjustment="none",
        calculations=(CalculationInstance("price", "price", {}),),
    ) | kwargs))


def _requirement(request, fields=frozenset(("close",)), batch_rows=2):
    return ReadRequirement(request, HistoryRequirement(fields, 0, None, True, (), "No initial NULL"),
                           batch_rows, None, request.end)


def _describe(source, requirement, *, control, read_context):
    """Exercise the real locator using a request-owned, short-lived executor.

    Only this old direct-source helper owns the metadata connection; the full
    service continues to create its sole connection itself. No helper runs at
    import time or is used by the new phase's acceptance fixture.
    """
    from src.foundation.technical_indicators.executor import DuckDBExecutor
    control.config = source._config
    connection = duckdb.connect(":memory:", config={"threads": 1, "memory_limit": "128MiB",
                                                    "max_temp_directory_size": "0B"})
    executor = DuckDBExecutor(connection, control)
    locator = source.create_locator(executor, requirement, read_context=read_context)
    try:
        description = locator.describe()
        locator.close()
        return description
    except BaseException as primary:
        if isinstance(control, _Control):
            control.cleanup_ready = True
        else:
            for error in control.stop_monitor():
                primary.add_note(f"Locator control cleanup: {error}")
        try:
            locator.close()
        except BaseException as error:
            primary.add_note(f"Locator cleanup: {error}")
        raise
    finally:
        connection.close()


@pytest.fixture(scope="module")
def minute_files(tmp_path_factory):
    root = tmp_path_factory.mktemp("ti_three_canonical_files").resolve()
    # Independent literal canonical schema, including unused index vwap.
    schema = pa.schema([
        ("ts_code", pa.string()), ("freq", pa.int32()), ("trade_date", pa.date32()),
        ("trade_time", pa.timestamp("us")), ("open", pa.float64()),
        ("high", pa.float64()), ("low", pa.float64()), ("close", pa.float64()),
        ("vol", pa.float64()), ("amount", pa.float64()), ("exchange", pa.string()), ("vwap", pa.float64()),
    ])
    paths = []
    for day, prices in ((date(2025, 12, 31), (10.0, 11.0)),
                        (date(2026, 1, 2), ()), (date(2026, 1, 5), (12.0, 13.0, 14.0))):
        rows = [dict(ts_code="000001.SH", freq=1, trade_date=day,
                     trade_time=datetime.combine(day, datetime.min.time()).replace(hour=9, minute=31 + i),
                     open=value, high=value, low=value, close=value, vol=100.0, amount=1000.0,
                     exchange="SSE", vwap=value) for i, value in enumerate(prices)]
        rows.append(dict(ts_code="399001.SZ", freq=1, trade_date=day,
                         trade_time=datetime.combine(day, datetime.min.time()).replace(hour=9, minute=31),
                         open=100.0, high=100.0, low=100.0, close=100.0, vol=200.0, amount=2000.0,
                         exchange="SZSE", vwap=100.0))
        path = root / "gold/quote/major_index_mins/freq=1" / f"trade_date={day}" / "part-000.parquet"
        path.parent.mkdir(parents=True)
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
        paths.append(path)
    assert sum(path.stat().st_size for path in paths) < 8 * 1024 * 1024
    return root, tuple(paths)


def test_real_forward_stream_interleaves_sql_without_restarting_or_empty_file_eof(minute_files):
    root, paths = minute_files
    config = _config(root)
    request = _request(start=datetime(2026, 1, 5, tzinfo=ZoneInfo("Asia/Shanghai")))
    requirement = _requirement(request)
    context, control = SourceReadContext(config), _Control()
    source = LakeTechnicalIndicatorPriceSource(config)
    description = _describe(source, requirement, control=control, read_context=context)
    assert description.price_paths == (paths[0], paths[2])
    assert description.source_projection == ("ts_code", "trade_date", "trade_time", "close")
    assert description.available_through is None
    stream = source.open(SimpleNamespace(control=control), description, requirement, read_context=context)
    values, positions = [], []
    con = duckdb.connect(":memory:", config={"threads": 1, "memory_limit": "128MiB", "max_temp_directory_size": "0B"})
    try:
        while (batch := stream.next_batch(2)) is not None:
            assert batch.selected_rows <= 2
            assert batch.physical_rows is None
            assert batch.source_files == 3  # cumulative metadata/data visits
            assert batch.source_file_bytes == sum(path.stat().st_size for path in paths)
            with pytest.raises(SourceContractError, match="released"):
                stream.next_batch(2)
            con.register("ti_source_batch", batch.columns)
            con.execute("CREATE TEMP TABLE ti_copy AS SELECT close FROM ti_source_batch")
            con.unregister("ti_source_batch")
            values.extend(row[0] for row in con.execute("SELECT close FROM ti_copy").fetchall())
            con.execute("DROP TABLE ti_copy")
            positions.extend(range(batch.source_first_position, batch.source_last_position + 1))
            stream.release_current_batch()
        assert stream.next_batch(2) is None
        assert values == [10.0, 11.0, 12.0, 13.0, 14.0]
        assert positions == [1, 2, 3, 4, 5]
        assert context.source_rows == 5
        # start is for output only: December is required input, never discarded.
        assert description.price_paths[0].parent.name == "trade_date=2025-12-31"
    finally:
        stream.close()
        stream.close()
        con.close()
    with pytest.raises(SourceContractError, match="closed"):
        stream.next_batch(2)


def test_filtered_end_and_before_share_original_prefix(minute_files):
    root, _ = minute_files
    config = _config(root)
    request = _request(end=datetime(2026, 1, 5, 9, 33, tzinfo=ZoneInfo("Asia/Shanghai")),
                       before=datetime(2026, 1, 5, 9, 32, tzinfo=ZoneInfo("Asia/Shanghai")))
    requirement = _requirement(request)
    context, control = SourceReadContext(config), _Control()
    source = LakeTechnicalIndicatorPriceSource(config)
    description = _describe(source, requirement, control=control, read_context=context)
    stream = source.open(SimpleNamespace(control=control), description, requirement, read_context=context)
    values = []
    try:
        while (batch := stream.next_batch(2)) is not None:
            values.extend(batch.columns.column("close").to_pylist())
            stream.release_current_batch()
    finally:
        stream.close()
    assert values == [10.0, 11.0, 12.0]


def test_cancellation_and_file_count_fail_before_data_reader(minute_files, monkeypatch):
    root, _ = minute_files
    config = _config(root)
    source = LakeTechnicalIndicatorPriceSource(config)
    control, request = _Control(), _request()
    context = SourceReadContext(replace(config, max_source_files=2))
    with pytest.raises(ResourceLimitError, match="max_source_files"):
        _describe(source, _requirement(request), control=control, read_context=context)
    assert context.source_files == 2
    original = source._inspect
    visited = []

    def cancel_after_first(path, *args, **kwargs):
        original(path, *args, **kwargs)
        visited.append(path)
        control.stopped = True

    monkeypatch.setattr(source, "_inspect", cancel_after_first)
    with pytest.raises(CalculationCancelledError):
        _describe(source, _requirement(request), control=control, read_context=SourceReadContext(config))
    assert len(visited) == 1


def test_row_group_protection_and_unsupported_paths_are_not_empty_success(minute_files):
    root, _ = minute_files
    config = replace(_config(root), max_projected_row_group_bytes=1)
    source = LakeTechnicalIndicatorPriceSource(config)
    request = _request()
    with pytest.raises(ResourceLimitError, match="row group"):
        _describe(source, _requirement(request), control=_Control(), read_context=SourceReadContext(config))
    for request in (_request(adjustment="qfq"), _request(period="day"),
                    _request(security_type="stock", adjustment="none")):
        with pytest.raises(SourceUnsupportedError):
            _describe(source, _requirement(request), control=_Control(), read_context=SourceReadContext(config))


def test_daily_and_period_projections_use_literal_producer_types_in_memory():
    con = duckdb.connect(":memory:", config={"threads": 1})
    try:
        for period in ("day", "week", "month"):
            request = _request(security_type="stock", ts_code="600000.SH", period=period, adjustment="qfq")
            contract = price_contract(request)
            physical, standard = source_projection(contract, frozenset(("close", "volume", "amount")), "qfq")
            if period == "day":
                table = pa.table({"ts_code": ["600000.SH"], "trade_date": pa.array([date(2026, 10, 20)], type=pa.date32()),
                                  "close": [10.0], "vol": [12.0], "amount": [34.0]})
            else:
                table = pa.table({"ts_code": ["600000.SH"], "trade_date": ["20261023"], "end_date": ["20261020"],
                                  "close_qfq": pa.array([Decimal("5.0000")], type=pa.decimal128(18, 4)),
                                  "vol": pa.array([Decimal("12.0000")], type=pa.decimal128(20, 4)),
                                  "amount": pa.array([Decimal("34.0000")], type=pa.decimal128(20, 4))})
            assert set(physical) == set(table.column_names)
            con.register("ti_literal_source", table)
            projection = ",".join(f'{sql} AS "{name}"' for name, sql in standard)
            row = con.execute("SELECT " + projection + " FROM ti_literal_source b").fetchone()
            if period == "day":
                assert row == (date(2026, 10, 20),) * 4 + (10.0, 12.0, 34.0)
            elif period == "week":
                assert row == (date(2026, 10, 23), date(2026, 10, 19), date(2026, 10, 23), date(2026, 10, 20), 5.0, 12.0, 34.0)
            else:
                assert row == (date(2026, 10, 23), date(2026, 10, 1), date(2026, 10, 31), date(2026, 10, 20), 5.0, 12.0, 34.0)
            con.unregister("ti_literal_source")
    finally:
        con.close()


def test_close_failure_retains_unreleased_reader_for_final_cleanup():
    """No data read: the resource-failure substitute proves cleanup ownership."""
    from src.foundation.clients.local_lake.technical_indicator_price_source import _LakePriceStream

    class FailingReader:
        fail = True
        calls = 0

        def close(self):
            self.calls += 1
            if self.fail:
                raise OSError("literal close failure")

    stream = _LakePriceStream(SimpleNamespace(price_paths=(), selection=PriceReadSelection(None, None, None, None, 0, 0, False, ())), SimpleNamespace(batch_rows=2), _Control(), object())
    reader = FailingReader()
    stream._reader = reader
    with pytest.raises(ResourceCleanupError):
        stream.close()
    assert stream._reader is reader
    assert not stream._closed
    assert stream._failed
    reader.fail = False
    stream.close()
    assert reader.calls == 2
    assert stream._reader is None
    assert stream._closed
    stream.close()
    assert reader.calls == 2


# D2 correction acceptance, LLD 06.6 / 18.1 / 19.11.  This fixture declares
# producer fields literally: asset_column_schemas.py GOLD_STK_MINS_QFQ_SCHEMA
# (around line 500), SILVER_STOCK_DAILY_SCHEMA (587), SILVER_ADJ_FACTOR_SCHEMA
# (623).  It never imports the producer to manufacture its own expected values.
# Only the named new nodes below are intended for this bounded acceptance run.
from time import monotonic
import json


_ASSEMBLY_DATES = (
    date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 9),
    date(2026, 1, 12), date(2026, 1, 13), date(2026, 1, 14), date(2026, 1, 15), date(2026, 1, 16),
    date(2026, 1, 19), date(2026, 1, 20), date(2026, 1, 21), date(2026, 1, 22), date(2026, 1, 23),
    date(2026, 1, 26), date(2026, 1, 27), date(2026, 1, 28), date(2026, 1, 29), date(2026, 1, 30),
    date(2026, 2, 2),
)
_ASSEMBLY_FIXTURE_CACHE = {}
_ASSEMBLY_NEW_RECORDS = {"price":0,"factor":0}


@pytest.fixture(scope="session")
def batch_assembly_files(tmp_path_factory):
    """Shared by the three explicitly selected modules; build only once.

    New price records: 10001 minute + 21 daily = 10022.  The additional 21
    factor records are not price input rows and are recorded separately.
    Numeric generation and Parquet writing use real DuckDB SQL, not Python
    price arithmetic.  The zero-row annual file is a real empty file.
    """
    root = (tmp_path_factory.getbasetemp() / "ti_d2_batch_assembly").resolve()
    if root in _ASSEMBLY_FIXTURE_CACHE:
        return _ASSEMBLY_FIXTURE_CACHE[root]
    manifest = root / "fixture_manifest.json"
    if manifest.exists():
        result = SimpleNamespace(root=root,
            minute_paths=tuple(root / item for item in json.loads(manifest.read_text())["minute_paths"]),
            day_paths=tuple(root / f"silver/quote/stock_daily/trade_date={day}/part-000.parquet"
                            for day in _ASSEMBLY_DATES),
            factor_paths=tuple(root / f"silver/quote/adj_factor/trade_date={day}/part-000.parquet"
                               for day in _ASSEMBLY_DATES))
        _ASSEMBLY_FIXTURE_CACHE[root] = result
        return result
    if root.exists():
        raise RuntimeError("An incomplete assembly fixture must not be silently overwritten")
    root.mkdir()
    minute_paths = []
    con = duckdb.connect(":memory:", config={"threads": 1, "memory_limit": "128MiB",
                                             "max_temp_directory_size": "0B"})
    try:
        for year, rows, offset in ((2020, 5000, 0), (2021, 0, 0), (2022, 5000, 5000), (2023, 1, 10000)):
            path = root / f"gold/quote/stk_mins_qfq/freq=1/ts_code=600000.SH/year={year}/part-000.parquet"
            path.parent.mkdir(parents=True)
            con.execute("""COPY (
                WITH numbered AS (
                  SELECT i, CAST($start_day AS DATE) + CAST(floor(i/240) AS INTEGER) AS day,
                         CAST(i + $offset + 1 AS DOUBLE) AS price FROM range($row_count) r(i)
                ), bars AS (
                  SELECT *, CAST(day AS TIMESTAMP) + CASE WHEN i%240<120
                    THEN INTERVAL 9 HOUR + INTERVAL 31 MINUTE + (i%240)*INTERVAL 1 MINUTE
                    ELSE INTERVAL 13 HOUR + INTERVAL 1 MINUTE + (i%240-120)*INTERVAL 1 MINUTE END AS bar_time
                  FROM numbered
                ) SELECT '600000.SH'::VARCHAR AS ts_code, 1::INTEGER AS freq,
                    day::DATE AS trade_date, bar_time::TIMESTAMP AS trade_time,
                    price AS open, price+0.1 AS high, price-0.1 AS low, price AS close,
                    100.0::DOUBLE AS vol, 1000.0::DOUBLE AS amount, 'SSE'::VARCHAR AS exchange
                  FROM bars ORDER BY bar_time
                ) TO $target (FORMAT PARQUET, ROW_GROUP_SIZE 8192)""",
                {"start_day": date(year, 1, 2), "offset": offset,
                 "row_count": rows, "target": str(path)})
            minute_paths.append(path)
        day_paths, factor_paths = [], []
        for number, day in enumerate(_ASSEMBLY_DATES):
            path = root / f"silver/quote/stock_daily/trade_date={day}/part-000.parquet"
            path.parent.mkdir(parents=True)
            con.execute("""COPY (SELECT '600000.SH'::VARCHAR AS ts_code, $day::DATE AS trade_date,
                10.0::DOUBLE AS open, 11.0::DOUBLE AS high, 9.0::DOUBLE AS low,
                10.0::DOUBLE AS close, 10.0::DOUBLE AS pre_close,
                0.0::DOUBLE AS change_amount, 0.0::DOUBLE AS pct_chg,
                100.0::DOUBLE AS vol, 1000.0::DOUBLE AS amount)
                TO $target (FORMAT PARQUET)""", {"day": day, "target": str(path)})
            factor_path = root / f"silver/quote/adj_factor/trade_date={day}/part-000.parquet"
            factor_path.parent.mkdir(parents=True)
            con.execute("""COPY (SELECT '600000.SH'::VARCHAR AS ts_code,
                $day::DATE AS trade_date, $factor::DOUBLE AS adj_factor)
                TO $target (FORMAT PARQUET)""", {"day": day,
                    "factor": 1.0 if number < 10 else 2.0, "target": str(factor_path)})
            day_paths.append(path)
            factor_paths.append(factor_path)
    finally:
        con.close()
    manifest.write_text(json.dumps({"minute_paths": [str(p.relative_to(root)) for p in minute_paths],
        "created_price_rows": 10022, "created_factor_rows": 21, "created_total_records":10043}, sort_keys=True))
    result = SimpleNamespace(root=root, minute_paths=tuple(minute_paths), day_paths=tuple(day_paths),
                             factor_paths=tuple(factor_paths))
    _ASSEMBLY_FIXTURE_CACHE[root] = result
    _ASSEMBLY_NEW_RECORDS.update(price=10022,factor=21)
    return result


class AssemblyReadTrace:
    """Count actual native returned rows, including a rejected last read."""
    def __init__(self):
        self.actual_read_rows = 0
        self.reader_opens = []
        self.readers = []
        self.physical_batches = []
        self.close_attempts = []
        self.fail_close_paths = set()
        self.after_read = None
        self.copy_calls = self.copied_bytes = None
        self.peak_owned_arrow_bytes = None
        self.delivered_sizes = []
        self.sql_logical_rows = 0

    def observe_owned(self, stream):
        current, pending = stream._current_batch, stream._pending_batch
        self.peak_owned_arrow_bytes = max(self.peak_owned_arrow_bytes or 0,
            (0 if current is None else current.nbytes) + (0 if pending is None else pending.nbytes))


class _AssemblyReader:
    def __init__(self, reader, trace, path):
        self.reader, self.trace, self.path = reader, trace, str(path)
        self.closed = False

    def read_next_batch(self):
        batch = self.reader.read_next_batch()
        self.trace.actual_read_rows += batch.num_rows
        self.trace.physical_batches.append(batch.num_rows)
        if self.trace.after_read is not None:
            self.trace.after_read(batch)
        return batch

    def close(self):
        self.trace.close_attempts.append(self.path)
        if self.path in self.trace.fail_close_paths:
            raise OSError("injected assembly reader close failure")
        self.reader.close()
        self.reader = None
        self.closed = True


def track_assembly_reader(stream, trace, monkeypatch):
    original = stream._open_file

    def open_file(path):
        original(path)
        trace.reader_opens.append(str(path))
        reader = _AssemblyReader(stream._reader, trace, path)
        trace.readers.append(reader)
        stream._reader = reader

    monkeypatch.setattr(stream, "_open_file", open_file)


def track_compact_copies(trace, monkeypatch):
    original = pa.concat_arrays
    trace.copy_calls = trace.copied_bytes = 0

    def copied(arrays, *args, **kwargs):
        result = original(arrays, *args, **kwargs)
        trace.copy_calls += 1
        trace.copied_bytes += result.nbytes
        assert result.offset == 0
        for source_array in arrays:
            input_buffers = {b.address for b in source_array.buffers() if b is not None and b.size}
            assert not input_buffers.intersection(b.address for b in result.buffers() if b is not None and b.size)
        return result

    monkeypatch.setattr(pa, "concat_arrays", copied)


def assembly_config(files, *, limit=1500000):
    return replace(KernelConfig.from_settings(Settings(_env_file=None)),
        goldenshare_lake_root=str(files.root), batch_rows=8192, max_input_rows=limit)


def assembly_source(files, *, daily=False, adjustment=None, control=None, limit=1500000, open_stream=True):
    cfg = assembly_config(files,limit=limit)
    request = CalculationRequest("stock", "600000.SH", "day" if daily else "1m",
        (CalculationInstance("price", "price", {}),), adjustment=adjustment or ("none" if daily else "qfq"))
    history = HistoryRequirement(frozenset(("open", "high", "low", "close", "volume", "amount")),
                                 0, None, True, (), "No indicator is calculated")
    requirement = ReadRequirement(request, history, 8192, None, None)
    context, control = SourceReadContext(cfg), control or _Control()
    source = LakeTechnicalIndicatorPriceSource(cfg)
    description = _describe(source, requirement, control=control, read_context=context)
    stream = source.open(SimpleNamespace(control=control), description, requirement, read_context=context) if open_stream else None
    return cfg, request, requirement, context, control, source, description, stream


def assembly_metrics(record_property, case, trace, context, started, *, real_controls=0,
                     delivered=(), sql_rows=0, cleanup=(), expected=None, **extra):
    payload = dict(case=case, actual_read_rows=trace.actual_read_rows,
        real_control_objects=real_controls, delivered_sizes=list(trace.delivered_sizes or delivered), source_rows=context.source_rows,
        reader_opens=trace.reader_opens, physical_batch_sizes=trace.physical_batches,
        source_files=context.source_files, source_file_bytes=context.source_file_bytes,
        reader_close_attempts=trace.close_attempts, reader_closed=[r.closed for r in trace.readers],
        compact_copy_calls=trace.copy_calls, compact_copy_bytes=trace.copied_bytes,
        peak_owned_arrow_bytes=trace.peak_owned_arrow_bytes,
        sql_logical_rows=trace.sql_logical_rows if trace.sql_logical_rows else sql_rows,
        fixture_created_price_rows=_ASSEMBLY_NEW_RECORDS["price"],
        fixture_created_factor_rows=_ASSEMBLY_NEW_RECORDS["factor"],
        cleanup=list(cleanup), elapsed_ms=(monotonic()-started)*1000, expected=expected, **extra)
    record_property("d2_batch_metrics", json.dumps(payload, default=str, sort_keys=True))
    _ASSEMBLY_NEW_RECORDS.update(price=0,factor=0)


def consume_assembly_stream(stream, trace, context, expected_sizes, *, position_column=None):
    con = duckdb.connect(":memory:", config={"threads": 1, "memory_limit": "128MiB",
                                             "max_temp_directory_size": "0B"})
    delivered, observations, sql_rows = [], [], 0
    try:
        for number, expected_size in enumerate(expected_sizes):
            batch = stream.next_batch(8192)
            if batch is not None:trace.delivered_sizes.append(batch.selected_rows)
            assert batch is not None and batch.selected_rows == expected_size
            assert batch.source_first_position == (1 if not delivered else sum(delivered)+1)
            assert batch.source_last_position == sum(delivered)+expected_size
            assert batch.columns.num_rows == expected_size
            trace.observe_owned(stream)
            con.register("ti_assembly_arrow", batch.columns)
            trace.sql_logical_rows += expected_size
            con.execute("CREATE TEMP TABLE ti_assembly_copy AS SELECT * FROM ti_assembly_arrow")
            con.unregister("ti_assembly_arrow")
            pending = stream._pending_batch
            stream.release_current_batch()
            assert stream._current_batch is None and stream._pending_batch is pending
            key = position_column or "close"
            trace.sql_logical_rows += expected_size
            observations.append(con.execute(f'SELECT count(*),min("{key}"),max("{key}") FROM ti_assembly_copy').fetchone())
            sql_rows += expected_size*2
            con.execute("DROP TABLE ti_assembly_copy")
            delivered.append(expected_size)
            if number == 0 and expected_sizes == (8192, 1809):
                assert context.source_rows == 10000 and trace.actual_read_rows == 10000
                assert stream._delivered == 8192 and pending is not None and pending.num_rows == 1808
                assert len(trace.reader_opens) == 2  # empty file skipped during key location; last file is not prefetched
        assert stream.next_batch(8192) is None
        assert stream.next_batch(8192) is None
        assert stream._delivered == sum(expected_sizes)
        return delivered, observations, sql_rows
    finally:
        con.close()


def test_existing_fixture_delivers_four_full_batches(monkeypatch, record_property):
    from scripts.diagnostics.technical_indicator_d2_acceptance import (
        FIXTURE, inspect_fixture, validate_fixture, create_fixture_reader,
    )
    from src.foundation.clients.local_lake.technical_indicator_price_source import _LakePriceStream
    started, trace = monotonic(), AssemblyReadTrace()
    metadata = inspect_fixture(FIXTURE)
    validate_fixture(metadata)  # exact count/footer/resource checks precede the data reader
    cfg = replace(KernelConfig.from_settings(Settings(_env_file=None)), batch_rows=8192)
    context = SourceReadContext(cfg)
    context.record_file(FIXTURE, metadata["bytes"])
    request = _request(security_type="stock", ts_code="600000.SH", adjustment="qfq")
    requirement = ReadRequirement(request, HistoryRequirement(frozenset(("close",)),0,None,True,(),"fixture"),8192,None,None)
    description = SimpleNamespace(price_paths=(), selection=PriceReadSelection(None, None, None, None, 0, 0, False, ()))
    stream = _LakePriceStream(description, requirement, _Control(), context)
    reader = _AssemblyReader(create_fixture_reader(FIXTURE), trace, FIXTURE)
    trace.reader_opens.append(str(FIXTURE)); trace.readers.append(reader)
    stream._reader = reader
    delivered, sql_rows = [], 0
    track_compact_copies(trace, monkeypatch)
    try:
        delivered, observations, sql_rows = consume_assembly_stream(stream, trace, context,
            (8192,8192,8192,8192), position_column="i")
        assert observations == [(8192,0,8191),(8192,8192,16383),(8192,16384,24575),(8192,24576,32767)]
        assert context.source_rows == trace.actual_read_rows == 32768
    finally:
        stream.close()
        assembly_metrics(record_property,"existing_fixture",trace,context,started,
            delivered=delivered,sql_rows=sql_rows,expected={"sizes":[8192,8192,8192,8192],"input":32768})


def test_assembly_crosses_files_and_consumes_pending_once(batch_assembly_files, monkeypatch, record_property):
    started, trace = monotonic(), AssemblyReadTrace()
    *_, context, control, source, description, stream = assembly_source(batch_assembly_files)
    track_assembly_reader(stream,trace,monkeypatch); track_compact_copies(trace,monkeypatch)
    delivered, sql_rows = [], 0
    try:
        assert description.price_paths == tuple(batch_assembly_files.minute_paths[i] for i in (0, 2, 3))
        delivered, observations, sql_rows = consume_assembly_stream(stream,trace,context,(8192,1809))
        assert observations == [(8192,1.0,8192.0),(1809,8193.0,10001.0)]
        assert context.source_rows == trace.actual_read_rows == 10001
        assert trace.reader_opens == [str(batch_assembly_files.minute_paths[i]) for i in (0, 2, 3)]
        assert trace.copy_calls > 0
        assert trace.peak_owned_arrow_bytes < 64*1024*1024
    finally:
        stream.close()
        assembly_metrics(record_property,"cross_files",trace,context,started,
            delivered=delivered,sql_rows=sql_rows,expected={"sizes":[8192,1809],"pending":1808,"input":10001})


def test_daily_files_deliver_one_final_batch(batch_assembly_files, monkeypatch, record_property):
    started, trace = monotonic(), AssemblyReadTrace()
    *_, context, control, source, description, stream = assembly_source(batch_assembly_files,daily=True)
    track_assembly_reader(stream,trace,monkeypatch); track_compact_copies(trace,monkeypatch)
    delivered, sql_rows = [], 0
    try:
        assert description.price_paths == batch_assembly_files.day_paths
        delivered, observations, sql_rows = consume_assembly_stream(stream,trace,context,(21,))
        assert observations == [(21,10.0,10.0)]
        assert context.source_rows == trace.actual_read_rows == 21
        assert stream._pending_batch is None
    finally:
        stream.close()
        assembly_metrics(record_property,"daily_final",trace,context,started,
            delivered=delivered,sql_rows=sql_rows,expected={"sizes":[21],"input":21})


def test_stop_while_assembling_discards_partial_batch(batch_assembly_files, monkeypatch, record_property):
    started, trace = monotonic(), AssemblyReadTrace()
    *_, context, control, source, description, stream = assembly_source(batch_assembly_files,daily=True)
    track_assembly_reader(stream,trace,monkeypatch)
    trace.after_read = lambda batch: setattr(control,"stopped",True) if trace.actual_read_rows==21 else None
    try:
        with pytest.raises(CalculationCancelledError):stream.next_batch(8192)
        assert trace.actual_read_rows == 21 and stream._delivered == 0
        assert stream._current_batch is stream._pending_batch is None
        assert stream._failed
    finally:
        stream.close()
        assembly_metrics(record_property,"assembling_cancel",trace,context,started,
            expected={"max_input":21,"delivered":0,"error":"CalculationCancelledError"})


def test_input_limit_rejects_before_copy_or_delivery(batch_assembly_files, monkeypatch, record_property):
    started, trace = monotonic(), AssemblyReadTrace()
    *_, context, control, source, description, stream = assembly_source(batch_assembly_files,daily=True)
    # Range selection now checks capacity before opening prices. This old unit
    # explicitly targets the separate read-before-copy protection, so lower
    # only its accounting allowance after a valid selection has been made.
    context.config = replace(context.config, max_input_rows=20)
    track_assembly_reader(stream,trace,monkeypatch)
    original, copied_after_limit = pa.concat_arrays, []
    def copy_checked(arrays,*args,**kwargs):
        if trace.actual_read_rows>20:copied_after_limit.append(True)
        return original(arrays,*args,**kwargs)
    monkeypatch.setattr(pa,"concat_arrays",copy_checked)
    try:
        with pytest.raises(ResourceLimitError,match="max_input_rows"):stream.next_batch(8192)
        assert trace.actual_read_rows == 21 and context.source_rows == 20
        assert not copied_after_limit and stream._delivered == 0
        assert stream._current_batch is stream._pending_batch is None
    finally:
        stream.close()
        assembly_metrics(record_property,"input_limit",trace,context,started,
            expected={"actual_input":21,"accepted_input":20,"delivered":0})


def test_copy_failure_releases_local_batches(batch_assembly_files, monkeypatch, record_property):
    started, trace = monotonic(), AssemblyReadTrace()
    *_, context, control, source, description, stream = assembly_source(batch_assembly_files,daily=True)
    track_assembly_reader(stream,trace,monkeypatch)
    original = pa.concat_arrays
    def fail_copy(arrays,*args,**kwargs):
        if trace.actual_read_rows==10:raise MemoryError("injected compact-copy allocation failure")
        return original(arrays,*args,**kwargs)
    monkeypatch.setattr(pa,"concat_arrays",fail_copy)
    try:
        with pytest.raises(ResourceLimitError) as error:stream.next_batch(8192)
        assert isinstance(error.value.__cause__,MemoryError)
        assert trace.actual_read_rows == 10 and stream._failed and stream._delivered == 0
        assert stream._current_batch is stream._pending_batch is None
    finally:
        stream.close()
        assembly_metrics(record_property,"copy_failure",trace,context,started,
            expected={"max_input":10,"delivered":0,"error":"ResourceLimitError"})


def test_concat_failure_releases_local_batches(batch_assembly_files, monkeypatch, record_property):
    started, trace = monotonic(), AssemblyReadTrace()
    *_, context, control, source, description, stream = assembly_source(batch_assembly_files,daily=True)
    stream._files = iter(description.price_paths[:11])
    track_assembly_reader(stream,trace,monkeypatch)
    def fail_concat(*args,**kwargs):raise pa.ArrowInvalid("injected incompatible assembly schema")
    monkeypatch.setattr(pa,"concat_batches",fail_concat)
    try:
        with pytest.raises(SourceContractError) as error:stream.next_batch(8192)
        assert isinstance(error.value.__cause__,pa.ArrowInvalid)
        assert trace.actual_read_rows == 11 and stream._failed and stream._delivered == 0
        assert stream._current_batch is stream._pending_batch is None
    finally:
        stream.close()
        assembly_metrics(record_property,"concat_failure",trace,context,started,
            expected={"max_input":11,"delivered":0,"error":"SourceContractError"})


def test_close_failure_keeps_reader_for_final_cleanup(batch_assembly_files, monkeypatch, record_property):
    started, trace = monotonic(), AssemblyReadTrace()
    *_, context, control, source, description, stream = assembly_source(batch_assembly_files,daily=True)
    track_assembly_reader(stream,trace,monkeypatch)
    trace.fail_close_paths.add(str(description.price_paths[-1]))
    try:
        with pytest.raises(ResourceCleanupError):stream.next_batch(8192)
        retained = stream._reader
        assert retained is not None and not retained.closed
        assert stream._failed and not stream._closed and stream._delivered == 0
        assert stream._current_batch is stream._pending_batch is None
        with pytest.raises(ResourceCleanupError):stream.close()
        assert stream._reader is retained and not stream._closed
        trace.fail_close_paths.clear()
        stream.close()
        assert stream._reader is None and stream._closed and retained.closed
        attempts = len(trace.close_attempts)
        stream.close()
        assert len(trace.close_attempts)==attempts
        assert trace.actual_read_rows==21
    finally:
        trace.fail_close_paths.clear()
        stream.close()
        assembly_metrics(record_property,"close_failure",trace,context,started,
            expected={"max_input":21,"delivered":0,"error":"ResourceCleanupError","retry_close":True},
            injected_cleanup_error="reader close retained until successful close")
