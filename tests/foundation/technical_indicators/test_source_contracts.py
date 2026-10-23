"""LLD §06.8: three tiny canonical files, no service or formal-data access.

The literal minute schema follows DG's GOLD_STK_MINS_QFQ_SCHEMA and the existing
Foundation major_index_mins_contract. Period SQL uses in-memory Arrow with
literal producer types; it does not claim weekly/monthly file integration.
Only this module's tmp_path_factory fixture creates three Parquet files.
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
from src.foundation.technical_indicators.sources.contracts import ReadRequirement
from src.foundation.technical_indicators.sources.read_context import SourceReadContext


def _config(root, **kwargs):
    config = KernelConfig.from_settings(Settings(_env_file=None))
    return replace(config, goldenshare_lake_root=str(root), batch_rows=2,
                   max_input_rows=1500000, max_source_files=5000,
                   max_projected_row_group_bytes=33554432, **kwargs)


class _Control:
    """Only stop signaling is isolated; real Arrow/DuckDB are not replaced."""
    stopped = False

    def check_active(self):
        if self.stopped:
            raise CalculationCancelledError("literal test cancellation")


def _request(**kwargs):
    return CalculationRequest(**(dict(
        security_type="index", ts_code="000001.SH", period="1m", adjustment="none",
        calculations=(CalculationInstance("price", "price", {}),),
    ) | kwargs))


def _requirement(request, fields=frozenset(("close",)), batch_rows=2):
    return ReadRequirement(request, HistoryRequirement(fields, 0, True, (), "No initial NULL"),
                           batch_rows, None, request.end)


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
    description = source.describe(request, requirement, control=control, read_context=context)
    assert description.price_paths == paths
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
    description = source.describe(request, requirement, control=control, read_context=context)
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
        source.describe(request, _requirement(request), control=control, read_context=context)
    assert context.source_files == 2
    original = source._inspect
    visited = []

    def cancel_after_first(path, *args):
        original(path, *args)
        visited.append(path)
        control.stopped = True

    monkeypatch.setattr(source, "_inspect", cancel_after_first)
    with pytest.raises(CalculationCancelledError):
        source.describe(request, _requirement(request), control=control, read_context=SourceReadContext(config))
    assert len(visited) == 1


def test_row_group_protection_and_unsupported_paths_are_not_empty_success(minute_files):
    root, _ = minute_files
    config = replace(_config(root), max_projected_row_group_bytes=1)
    source = LakeTechnicalIndicatorPriceSource(config)
    request = _request()
    with pytest.raises(ResourceLimitError, match="row group"):
        source.describe(request, _requirement(request), control=_Control(), read_context=SourceReadContext(config))
    for request in (_request(adjustment="qfq"), _request(period="day"),
                    _request(security_type="stock", adjustment="none")):
        with pytest.raises(SourceUnsupportedError):
            source.describe(request, _requirement(request), control=_Control(), read_context=SourceReadContext(config))


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

    stream = _LakePriceStream(SimpleNamespace(price_paths=()), SimpleNamespace(batch_rows=2), _Control(), object())
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
