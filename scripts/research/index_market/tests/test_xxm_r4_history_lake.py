"""HC20—24: actual temporary Parquet, not formal Lake or algorithms.

Independent fixture contract: DG run_contracts/idx_factor_pro.py declares
VARCHAR/DATE/DOUBLE Silver fields; asset_column_schemas.py declares the SSE
VARCHAR/DATE/BOOLEAN fields. Values below are manually chosen literal samples.
"""
from dataclasses import FrozenInstanceError
from datetime import date
import importlib
import json
import math
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.research.index_market.xxm import r4_history_lake as m


START = date(2023, 1, 3)
END = date(2023, 1, 5)
MARKET_SCHEMA = pa.schema([
    ("ts_code", pa.string()), ("trade_date", pa.date32()), ("close", pa.float64()),
    ("macd_dif_bfq", pa.float64()), ("macd_dea_bfq", pa.float64()), ("macd_bfq", pa.float64()),
    ("extra_indicator", pa.float64()),
])
CALENDAR_SCHEMA = pa.schema([("exchange", pa.string()), ("trade_date", pa.date32()),
                             ("is_open", pa.bool_()), ("pretrade_date", pa.date32())])


def market_path(root, day):
    return root / f"silver/index/index_factor_pro/trade_date={day.isoformat()}/part-000.parquet"


def write_market(path, day, *, value=None, schema=None):
    rows = [{"ts_code": "000001.SH", "trade_date": day, "close": 100.123456789,
             "macd_dif_bfq": -0.0, "macd_dea_bfq": -0.0, "macd_bfq": 0.0,
             "extra_indicator": 55.0},
            {"ts_code": "399001.SZ", "trade_date": day, "close": 200.0,
             "macd_dif_bfq": 1.0, "macd_dea_bfq": 1.0, "macd_bfq": 0.0,
             "extra_indicator": 44.0}]
    if value:
        rows[0].update(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema or MARKET_SCHEMA), path)


@pytest.fixture
def lake(tmp_path):
    root = tmp_path.resolve()
    for day in (START, END):
        write_market(market_path(root, day), day)
    calendar = root / m.SPEC.calendar_relative
    calendar.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist([
        {"exchange": "SSE", "trade_date": START, "is_open": True, "pretrade_date": date(2022, 12, 30)},
        {"exchange": "SSE", "trade_date": date(2023, 1, 4), "is_open": False, "pretrade_date": START},
        {"exchange": "SSE", "trade_date": END, "is_open": True, "pretrade_date": START},
        {"exchange": "OTHER", "trade_date": START, "is_open": False, "pretrade_date": START},
    ], schema=CALENDAR_SCHEMA), calendar)
    return root


def read(lake, **kwargs):
    return m.read_tables(root=lake, start=START, end=END, **kwargs)


def test_hc20_real_temporary_parquet_projection_values_and_order(lake):
    queries = []
    result = read(lake, query_event=lambda kind, query: queries.append((kind, query)))
    assert result["marketRows"] == [
        ("000001.SH", "2023-01-03", 100.123456789, -0.0, -0.0, 0.0),
        ("000001.SH", "2023-01-05", 100.123456789, -0.0, -0.0, 0.0),
    ]
    assert result["calendarRows"] == [("SSE", "2023-01-03", True), ("SSE", "2023-01-04", False), ("SSE", "2023-01-05", True)]
    assert result["fileCount"] == 2 and result["connectionClosed"] is True
    assert all(type(v) is float for row in result["marketRows"] for v in row[2:])
    assert math.copysign(1, result["marketRows"][0][3]) == -1
    assert queries == [(kind, query) for query in ("SCHEMA", "MARKET", "CALENDAR")
                       for kind in ("QUERY_START", "QUERY_DONE")]


@pytest.mark.parametrize("field,new_type", [("trade_date", pa.string()), ("trade_date", pa.timestamp("us")),
                                           ("close", pa.int64()), ("close", pa.decimal128(10, 2)),
                                           ("macd_dif_bfq", pa.float32())])
def test_hc21_later_partition_schema_drift_is_not_implicitly_cast(lake, field, new_type):
    path = market_path(lake, END)
    schema = MARKET_SCHEMA.set(MARKET_SCHEMA.get_field_index(field), pa.field(field, new_type))
    if pa.types.is_decimal(new_type):
        from decimal import Decimal
        # Both rows must satisfy the deliberately wrong decimal column.
        rows = pa.Table.from_pylist([{"ts_code": "000001.SH", "trade_date": END,
            "close": Decimal("100.00"), "macd_dif_bfq": 0.0, "macd_dea_bfq": 0.0,
            "macd_bfq": 0.0, "extra_indicator": 55.0}], schema=schema)
        pq.write_table(rows, path)
    elif pa.types.is_string(new_type):
        table = pq.read_table(path, partitioning=None).set_column(1, "trade_date", pa.array(["2023-01-05"] * 2, pa.string()))
        pq.write_table(table, path)
    elif pa.types.is_timestamp(new_type):
        table = pq.read_table(path, partitioning=None).cast(schema)
        pq.write_table(table, path)
    else:
        table = pq.read_table(path, partitioning=None).cast(schema, safe=False)
        pq.write_table(table, path)
    with pytest.raises(ValueError, match="字段类型"):
        read(lake)


def test_hc21_missing_column_rejected(lake):
    path = market_path(lake, END)
    table = pq.read_table(path, partitioning=None).drop(["macd_dif_bfq"])
    pq.write_table(table, path)
    with pytest.raises(ValueError, match="缺少所需字段"):
        read(lake)


def test_hc21_duplicate_required_column_rejected(lake):
    path = market_path(lake, END)
    table = pq.read_table(path, partitioning=None)
    pq.write_table(table.append_column("close", pa.array([3.0, 4.0])), path)
    with pytest.raises(ValueError, match="重复字段"):
        read(lake)


def test_hc21_internal_date_does_not_use_partition_name(lake):
    write_market(market_path(lake, END), START)
    with pytest.raises(ValueError, match="分区或日期"):
        read(lake)


@pytest.mark.parametrize("bad", ["nan", "infinity", "null", "zero", "negative", "duplicate"])
def test_hc21_invalid_values_and_duplicate_dates_rejected(lake, bad):
    path = market_path(lake, END)
    if bad == "duplicate":
        table = pq.read_table(path, partitioning=None)
        pq.write_table(pa.concat_tables([table, table.slice(0, 1)]), path)
    else:
        values = {"macd_dif_bfq": float("nan") if bad == "nan" else float("inf")} if bad in ("nan", "infinity") else {"close": None if bad == "null" else 0.0 if bad == "zero" else -1.0}
        write_market(path, END, value=values)
    with pytest.raises(ValueError):
        read(lake)


@pytest.mark.parametrize("target", ["file", "directory", "calendar"])
def test_hc21_symlink_rejected_without_following(lake, target):
    if target == "directory":
        path = market_path(lake, END).parent
        alternate = path.with_name("outside")
        path.rename(alternate)
        path.symlink_to(alternate, target_is_directory=True)
    else:
        path = market_path(lake, END) if target == "file" else lake / m.SPEC.calendar_relative
        alternate = path.with_name("outside.parquet")
        path.rename(alternate)
        path.symlink_to(alternate)
    with pytest.raises(ValueError, match="符号链接"):
        read(lake)


def test_hc21_missing_calendar_and_empty_market_reject(lake):
    (lake / m.SPEC.calendar_relative).unlink()
    with pytest.raises(ValueError, match="缺失"):
        read(lake)
    with pytest.raises(ValueError):
        m.discover_files(root=lake, start=END, end=START, check=lambda: None)


@pytest.mark.parametrize("change", ["modify", "replace", "add", "remove"])
def test_hc22_input_file_changes_rejected(lake, change):
    def event(kind, query):
        if (kind, query) != ("QUERY_DONE", "CALENDAR"):
            return
        path = market_path(lake, END)
        if change == "modify":
            info = path.stat()
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1))
        elif change == "replace":
            path.unlink()
            write_market(path, END)
        elif change == "add":
            write_market(market_path(lake, date(2023, 1, 4)), date(2023, 1, 4))
        else:
            path.unlink()
    with pytest.raises(ValueError, match="读取期间变化"):
        read(lake, query_event=event)


def test_hc22_connection_closed_before_result_and_on_query_failure(lake):
    events = []
    class Wrapper:
        def __init__(self): self.real = m._duckdb_connection()
        def execute(self, sql, args):
            events.append("execute")
            return self.real.execute(sql, args)
        def close(self):
            events.append("close")
            self.real.close()
    result = read(lake, connect=Wrapper)
    assert result["connectionClosed"] is True and events[-1] == "close"
    events.clear()
    class BadQuery(Wrapper):
        def execute(self, sql, args): raise LookupError("independent injected error")
    with pytest.raises(LookupError): read(lake, connect=BadQuery)
    assert events == ["close"]


def test_hc22_close_failure_cannot_return_success_or_replace_query_error(lake):
    class BadClose:
        def __init__(self): self.real = m._duckdb_connection()
        def execute(self, sql, args): return self.real.execute(sql, args)
        def close(self):
            self.real.close()
            raise RuntimeError("literal close failure")
    with pytest.raises(RuntimeError, match="close failure"):
        read(lake, connect=BadClose)
    class Both(BadClose):
        def execute(self, sql, args): raise LookupError("first")
    with pytest.raises(LookupError, match="first") as caught:
        read(lake, connect=Both)
    assert "RuntimeError" in caught.value.__notes__[0]


def test_hc20_24_configuration_is_memory_only_no_auto_extensions_or_spill():
    connection = m._duckdb_connection()
    try:
        actual = dict(connection.execute("SELECT name,value FROM duckdb_settings() WHERE name IN ('memory_limit','threads','max_temp_directory_size','autoinstall_known_extensions','autoload_known_extensions')").fetchall())
        assert actual["threads"] == "1"
        assert actual["max_temp_directory_size"] == "0 bytes"
        assert actual["autoinstall_known_extensions"] == actual["autoload_known_extensions"] == "false"
        assert actual["memory_limit"] == "128.0 MiB"
    finally:
        connection.close()


def test_hc24_import_does_not_import_duckdb_or_touch_source(monkeypatch):
    import builtins
    original = builtins.__import__
    def guarded(name, *args, **kw):
        if name.split(".")[0] in {"duckdb", "orchestrator", "dagster", "src"}:
            raise AssertionError(name)
        return original(name, *args, **kw)
    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(Path, "lstat", lambda p: (_ for _ in ()).throw(AssertionError("read")))
    importlib.reload(m)


def test_hc24_source_spec_fixed_and_request_json_rejects_duplicates_nonfinite():
    with pytest.raises(ValueError): m.LocalLakeSpec(lake_root="/tmp/other")
    with pytest.raises(FrozenInstanceError): m.SPEC.lake_root = "/tmp/other"
    with pytest.raises(ValueError): m._strict_json(b'{"a":1,"a":2}')
    with pytest.raises(ValueError): m._strict_json(b'{"a":NaN}')


def test_hc21_file_count_and_byte_limits_precede_any_sql(tmp_path):
    root = tmp_path.resolve()
    calendar = root / m.SPEC.calendar_relative
    calendar.parent.mkdir(parents=True)
    calendar.write_bytes(b'x')
    from datetime import timedelta
    for index in range(1001):
        path = market_path(root, START + timedelta(days=index))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x')
    with pytest.raises(OverflowError, match="数量或字节"):
        m.discover_files(root=root, start=START, end=START + timedelta(days=1000), check=lambda: None)
    first = market_path(root, START)
    with first.open('wb') as handle:
        handle.truncate(32 * 1024 * 1024 + 1)
    with pytest.raises(OverflowError, match="数量或字节"):
        m.discover_files(root=root, start=START, end=START, check=lambda: None)


def test_hc21_calendar_size_limit_precedes_any_sql(lake):
    with (lake / m.SPEC.calendar_relative).open('wb') as handle:
        handle.truncate(128 * 1024 + 1)
    with pytest.raises(ValueError, match="日历文件超限"):
        read(lake)


@pytest.mark.parametrize('which', ['MARKET', 'CALENDAR'])
def test_hc21_row_count_probe_rejects_without_truncation(lake, which):
    path = market_path(lake, START) if which == 'MARKET' else lake / m.SPEC.calendar_relative
    table = pq.read_table(path, partitioning=None).slice(0, 1)
    pq.write_table(pa.concat_tables([table] * (1001 if which == 'MARKET' else 2001)), path)
    with pytest.raises(OverflowError, match='超过'):
        read(lake)


def test_hc21_calendar_boolean_must_not_be_integer(lake):
    path = lake / m.SPEC.calendar_relative
    table = pq.read_table(path, partitioning=None)
    table = table.set_column(2, 'is_open', table.column('is_open').cast(pa.int8()))
    pq.write_table(table, path)
    with pytest.raises(ValueError, match='字段类型'):
        read(lake)


def _install_request_pipe(monkeypatch, request):
    import time
    request = {'kind': 'READ_INPUT', 'protocolVersion': 1, 'source': 'local-dg-silver',
               'readDeadline': time.monotonic() + 8, 'maxWorkerMemoryBytes': 256 * 1024 * 1024, **request}
    body = json.dumps(request, allow_nan=False, separators=(',', ':')).encode()
    pending = bytearray(len(body).to_bytes(8, 'big') + body)
    output = bytearray()
    def read_pipe(fd, n):
        assert fd == 0
        value = bytes(pending[:min(n, 13)])
        del pending[:len(value)]
        return value
    def write_pipe(fd, data):
        assert fd == 1
        value = data[:29]
        output.extend(value)
        return len(value)
    monkeypatch.setattr(m.os, 'read', read_pipe)
    monkeypatch.setattr(m.os, 'write', write_pipe)
    return output


def _messages(output):
    result = []
    while output:
        length = int.from_bytes(output[:8], 'big')
        assert len(output) >= length + 8
        result.append(json.loads(output[8:8 + length]))
        del output[:length + 8]
    return result


def test_hc23_reader_complete_frame_sequence_and_closed_result(monkeypatch, lake):
    output = _install_request_pipe(monkeypatch, {})
    original = m.read_tables
    monkeypatch.setattr(m, 'read_tables', lambda **kw: original(root=lake, start=START, end=END, **kw))
    assert m.reader_main() == 0
    messages = _messages(output)
    assert [x['kind'] for x in messages] == ['HELLO', 'QUERY_START', 'QUERY_DONE', 'QUERY_START',
                                           'QUERY_DONE', 'QUERY_START', 'QUERY_DONE', 'RESULT', 'DONE']
    assert [x['query'] for x in messages if x['kind'] == 'QUERY_START'] == ['SCHEMA', 'MARKET', 'CALENDAR']
    assert messages[-2]['payload']['connectionClosed'] is True
    assert all(x['source'] == 'local-dg-silver' and x['pid'] == os.getpid() for x in messages)
    assert all(type(x['peakMemoryBytes']) is int for x in messages if 'peakMemoryBytes' in x)


def test_hc23_authorized_one_gib_request_is_accepted_before_read(monkeypatch):
    _install_request_pipe(monkeypatch, {'maxWorkerMemoryBytes': 1024 * 1024 * 1024})
    assert m._read_request()['maxWorkerMemoryBytes'] == 1024 * 1024 * 1024


def test_hc23_reader_failure_has_no_result_or_original_exception_text(monkeypatch):
    output = _install_request_pipe(monkeypatch, {})
    def failure(**kw):
        raise LookupError('SQL and secret path must not leak')
    monkeypatch.setattr(m, 'read_tables', failure)
    assert m.reader_main() == 1
    messages = _messages(output)
    assert [x['kind'] for x in messages] == ['HELLO', 'ERROR']
    assert messages[-1]['exceptionType'] == 'LookupError'
    assert 'SQL' not in str(messages) and 'secret' not in str(messages)


@pytest.mark.parametrize('changes', [{'protocolVersion': True}, {'source': 'remote'}, {'path': '/tmp'},
                                    {'readDeadline': True}, {'maxWorkerMemoryBytes': True},
                                    {'maxWorkerMemoryBytes': 0},
                                    {'maxWorkerMemoryBytes': 1024 * 1024 * 1024 + 1}])
def test_hc23_request_rejects_extra_or_bad_fields_before_read(monkeypatch, changes):
    output = _install_request_pipe(monkeypatch, changes)
    monkeypatch.setattr(m, 'read_tables', lambda **kw: (_ for _ in ()).throw(AssertionError('must not read')))
    assert m.reader_main() == 1 and output == b''
