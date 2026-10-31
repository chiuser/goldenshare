"""Bounded local Silver reader for the historical r4 comparison.

Source contracts are copied from the current DG paths/idx_factor_pro Silver and
trade-calendar contracts. Importing this module performs no I/O or DG imports.
Only reader_main opens the fixed real source; tests use temporary Parquet files.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, timedelta
import json
import math
import os
from pathlib import Path
import resource
import stat
import sys
import time


@dataclass(frozen=True, slots=True)
class LocalLakeSpec:
    source: str = "local-dg-silver"
    lake_root: str = "/Volumes/datasource/data_lake"
    market_relative: str = "silver/index/index_factor_pro/trade_date={date}/part-000.parquet"
    calendar_relative: str = "silver/calendar/trade_calendar/full/part-000.parquet"
    start_date: str = "2023-01-03"
    end_date: str = "2026-10-27"
    ts_code: str = "000001.SH"
    period: str = "day"
    input_count: int = 922
    calendar_count: int = 1394
    max_input_bars: int = 1000
    max_calendar_days: int = 2000
    max_market_bytes: int = 32 * 1024 * 1024
    max_calendar_bytes: int = 128 * 1024
    max_read_result_bytes: int = 1024 * 1024
    query_seconds: float = 3.0
    read_seconds: float = 8.0
    cleanup_seconds: float = 0.5
    duckdb_memory: str = "128MiB"
    duckdb_threads: int = 1

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not type(field.default) or value != field.default:
                raise ValueError(f"本地来源固定参数不能变更：{field.name}")


SPEC = LocalLakeSpec()
MARKET_COLUMNS = ("ts_code", "trade_date", "close", "macd_dif_bfq", "macd_dea_bfq", "macd_bfq")
CALENDAR_COLUMNS = ("exchange", "trade_date", "is_open")
QUERIES = ("SCHEMA", "MARKET", "CALENDAR")


def _existing_path(path, *, directory=False, missing_ok=False):
    """Inspect ancestors before the leaf without following symbolic links."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("本地读取路径必须是固定绝对路径")
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if missing_ok:
                return None
            raise ValueError("本地读取所需文件或目录缺失") from None
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("本地读取拒绝符号链接")
        want_dir = part != path or directory
        if not (stat.S_ISDIR(info.st_mode) if want_dir else stat.S_ISREG(info.st_mode)):
            raise ValueError("本地读取目录或普通文件类型错误")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def discover_files(*, root, start, end, check):
    """Bounded metadata discovery, never a whole-Lake glob or a deep file scan."""
    root = Path(root)
    _existing_path(root, directory=True)
    if type(start) is not date or type(end) is not date or not 0 <= (end - start).days < SPEC.max_calendar_days:
        raise ValueError("本地读取日期范围越界")
    market = []
    day = start
    market_bytes = 0
    while day <= end:
        check()
        path = root / SPEC.market_relative.format(date=day.isoformat())
        info = _existing_path(path, missing_ok=True)
        if info is not None:
            market.append((str(path), day, info))
            market_bytes += info[2]
            if len(market) > SPEC.max_input_bars or market_bytes > SPEC.max_market_bytes:
                raise OverflowError("本地行情文件数量或字节超限")
        day += timedelta(days=1)
    calendar = root / SPEC.calendar_relative
    calendar_info = _existing_path(calendar)
    if not market or calendar_info[2] > SPEC.max_calendar_bytes:
        raise ValueError("本地行情为空或日历文件超限")
    check()
    return {"market": tuple(market), "calendar": (str(calendar), calendar_info),
            "fileCount": len(market), "fileBytes": market_bytes, "calendarBytes": calendar_info[2]}


def _schema_matches(row, expected):
    _, _, physical, converted, logical, children = row
    if children is not None:
        return False
    if expected == "VARCHAR":
        return physical == "BYTE_ARRAY" and converted in (None, "UTF8") and logical in (None, "StringType()") and (converted == "UTF8" or logical == "StringType()")
    if expected == "DATE":
        return physical == "INT32" and converted in (None, "DATE") and logical in (None, "DateType()") and (converted == "DATE" or logical == "DateType()")
    return physical == expected and converted is None and logical is None


def _validate_schemas(rows, manifest, check):
    expected = {path: dict(zip(MARKET_COLUMNS, ("VARCHAR", "DATE", "DOUBLE", "DOUBLE", "DOUBLE", "DOUBLE")))
                for path, _, _ in manifest["market"]}
    expected[manifest["calendar"][0]] = dict(zip(CALENDAR_COLUMNS, ("VARCHAR", "DATE", "BOOLEAN")))
    seen = {path: set() for path in expected}
    for row in rows:
        check()
        path, name = row[:2]
        if path not in expected:
            raise ValueError("footer返回未请求的文件")
        if name not in expected[path]:
            continue
        if name in seen[path] or not _schema_matches(row, expected[path][name]):
            raise ValueError("本地Parquet字段类型或重复字段错误")
        seen[path].add(name)
    if any(seen[path] != set(columns) for path, columns in expected.items()):
        raise ValueError("本地Parquet缺少所需字段")


def _duckdb_connection():
    import duckdb
    return duckdb.connect(database=":memory:", config={
        "memory_limit": SPEC.duckdb_memory, "threads": str(SPEC.duckdb_threads),
        "max_temp_directory_size": "0B", "autoinstall_known_extensions": "false",
        "autoload_known_extensions": "false",
    })


def read_tables(*, root=SPEC.lake_root, start=None, end=None, check=lambda: None,
                query_event=lambda kind, query: None, connect=None):
    """Read a fixed projection; injected roots/connections belong to unit fixtures."""
    start = date.fromisoformat(SPEC.start_date) if start is None else start
    end = date.fromisoformat(SPEC.end_date) if end is None else end
    manifest = discover_files(root=root, start=start, end=end, check=check)
    paths = [path for path, _, _ in manifest["market"]]
    path_days = {path: day for path, day, _ in manifest["market"]}
    connection = None
    original = None

    def query(name, sql, parameters):
        check()
        query_event("QUERY_START", name)
        deadline = time.monotonic() + SPEC.query_seconds
        values = connection.execute(sql, parameters).fetchall()
        if time.monotonic() >= deadline:
            raise TimeoutError("本地查询超过3秒")
        check()
        query_event("QUERY_DONE", name)
        return values

    try:
        check()
        connection = (connect or _duckdb_connection)()
        check()
        schema = query("SCHEMA", "SELECT file_name,name,type,converted_type,logical_type,num_children FROM parquet_schema(?) WHERE name IN ('ts_code','trade_date','close','macd_dif_bfq','macd_dea_bfq','macd_bfq','exchange','is_open')", [paths + [manifest["calendar"][0]]])
        _validate_schemas(schema, manifest, check)
        market = query("MARKET", """SELECT ts_code,trade_date,close,macd_dif_bfq,macd_dea_bfq,macd_bfq,filename
          FROM read_parquet(?,hive_partitioning=false,union_by_name=false,filename=true)
          WHERE ts_code=? AND trade_date BETWEEN ? AND ? ORDER BY trade_date LIMIT 1001""",
          [paths, SPEC.ts_code, start, end])
        if len(market) > SPEC.max_input_bars:
            raise OverflowError("本地行情超过1000行")
        market_rows = []
        previous = None
        for code, day, close, dif, dea, hist, filename in market:
            check()
            if (code != SPEC.ts_code or type(day) is not date or not start <= day <= end
                    or filename not in path_days or path_days[filename] != day
                    or previous is not None and day <= previous):
                raise ValueError("本地行情对象、分区或日期错误")
            values = (close, dif, dea, hist)
            if any(type(value) is not float or not math.isfinite(value) for value in values) or close <= 0:
                raise ValueError("本地行情必须为有限原始DOUBLE且收盘为正")
            market_rows.append((code, day.isoformat(), *values))
            previous = day
        calendar = query("CALENDAR", """SELECT exchange,trade_date,is_open
          FROM read_parquet(?,hive_partitioning=false,union_by_name=false)
          WHERE exchange='SSE' AND trade_date BETWEEN ? AND ? ORDER BY trade_date LIMIT 2001""",
          [manifest["calendar"][0], start, end])
        if len(calendar) > SPEC.max_calendar_days:
            raise OverflowError("本地日历超过2000行")
        calendar_rows = []
        previous = None
        for exchange, day, is_open in calendar:
            check()
            if (exchange != "SSE" or type(day) is not date or type(is_open) is not bool
                    or not start <= day <= end or previous is not None and day <= previous):
                raise ValueError("本地日历对象、日期或BOOLEAN错误")
            calendar_rows.append((exchange, day.isoformat(), is_open))
            previous = day
        check()
        after = discover_files(root=root, start=start, end=end, check=check)
        if after != manifest:
            raise ValueError("本地输入在读取期间变化，拒绝混用")
    except BaseException as exc:
        original = exc
        raise
    finally:
        if connection is not None:
            try:
                connection.close()
            except BaseException as exc:
                if original is None:
                    raise
                original.add_note(f"本地读取连接关闭：{type(exc).__name__}")
    check()
    return {"marketRows": market_rows, "calendarRows": calendar_rows,
            "fileCount": manifest["fileCount"], "fileBytes": manifest["fileBytes"],
            "calendarBytes": manifest["calendarBytes"], "connectionClosed": True}


def _strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("重复JSON字段")
            result[key] = value
        return result
    def bad_constant(value):
        raise ValueError("JSON非有限数值")
    return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs, parse_constant=bad_constant)


def _read_request():
    def exact(length):
        chunks = bytearray()
        while len(chunks) < length:
            value = os.read(0, length - len(chunks))
            if not value:
                raise ValueError("读取请求不完整")
            chunks.extend(value)
        return bytes(chunks)
    length = int.from_bytes(exact(8), "big")
    if not 1 <= length <= 4096:
        raise OverflowError("读取请求长度超限")
    body = exact(length)
    if os.read(0, 1):
        raise ValueError("读取请求有额外正文")
    request = _strict_json(body)
    if (type(request) is not dict or set(request) != {"kind", "protocolVersion", "source", "readDeadline", "maxWorkerMemoryBytes"}
            or request["kind"] != "READ_INPUT" or type(request["protocolVersion"]) is not int or request["protocolVersion"] != 1
            or request["source"] != SPEC.source
            or type(request["readDeadline"]) not in (int, float) or not math.isfinite(request["readDeadline"])
            or type(request["maxWorkerMemoryBytes"]) is not int or not 0 < request["maxWorkerMemoryBytes"] <= 1024 * 1024 * 1024):
        raise ValueError("本地读取请求身份或字段错误")
    return request


def reader_main():
    request = None
    sending = False
    sent_any = False
    terminal_sent = False
    try:
        request = _read_request()
        deadline = request["readDeadline"] - SPEC.cleanup_seconds

        def peak():
            return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

        def check():
            if time.monotonic() >= deadline:
                raise TimeoutError("本地读取超过原时限")
            if peak() > request["maxWorkerMemoryBytes"]:
                raise MemoryError("本地读取进程峰值超限")

        def send(kind, **fields):
            nonlocal sending, sent_any, terminal_sent
            check()
            message = {"kind": kind, "protocolVersion": 1, "source": SPEC.source, "pid": os.getpid(), **fields}
            body = json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
            limit = SPEC.max_read_result_bytes if kind == "RESULT" else 4096
            if len(body) > limit:
                raise OverflowError("本地读取消息超限")
            data = len(body).to_bytes(8, "big") + body
            check()
            sending, sent_any = True, False
            offset = 0
            while offset < len(data):
                check()
                offset += os.write(1, data[offset:offset + 65536])
                sent_any = True
            sending = False
            if kind == "DONE":
                terminal_sent = True
            else:
                check()

        send("HELLO", peakMemoryBytes=peak())
        def query_event(kind, query):
            send(kind, query=query, peakMemoryBytes=peak())
        payload = read_tables(check=check, query_event=query_event)
        send("RESULT", payload=payload)
        send("DONE", peakMemoryBytes=peak())
        return 0
    except BaseException as error:
        if request is not None and not terminal_sent and not (sending and sent_any):
            try:
                error_kind = ("TIMEOUT" if isinstance(error, TimeoutError) else "MEMORY" if isinstance(error, MemoryError)
                              else "SIZE" if isinstance(error, OverflowError) else "INPUT" if isinstance(error, ValueError) else "INTERNAL")
                message = {"kind": "ERROR", "protocolVersion": 1, "source": SPEC.source, "pid": os.getpid(),
                           "exceptionType": type(error).__name__, "errorKind": error_kind}
                body = json.dumps(message, allow_nan=False, separators=(",", ":")).encode()
                packet = len(body).to_bytes(8, "big") + body
                offset = 0
                while offset < len(packet):
                    offset += os.write(1, packet[offset:offset + 65536])
            except BaseException:
                pass
        return 1


if __name__ == "__main__":
    sys.exit(reader_main())
