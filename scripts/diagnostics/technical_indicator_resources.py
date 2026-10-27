"""D4's single bounded resource acceptance entry (LLD 12.4, 17.1--17.4).

Importing this module performs no I/O, calculation, thread creation or assembly.
The owner creates one 4000-row Parquet fixture; each fixed case runs in a new
process, sharing only that owned fixture and its saved accounting. This is not
a production API or a generic benchmark. No automatic retry is supported.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
from time import monotonic
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/technical_indicator_kernel_d4_20261027"
REFERENCE = ROOT / "reports/technical_indicator_kernel_d3_20261025/independent_reference.json"
RESUME_PLAN = REPORT / "resume_plan_20261027.json"
NODES = ("single_http", "dual_http", "shutdown_and_normal", "read_cancel_and_normal",
         "slow_send", "disconnect", "encoding_failure")
REQUEST_COUNTS = (1, 2, 2, 2, 1, 1, 1)
MA_PERIODS = (5, 10, 20, 30, 60, 90, 250)


def _read(path):
    return json.loads(path.read_text())


def _write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


def _error(error):
    return {"type": type(error).__name__, "message": str(error),
            "cause_type": type(error.__cause__).__name__ if error.__cause__ else None}


def _request():
    from src.foundation.technical_indicators import CalculationInstance, CalculationRequest

    items = (CalculationInstance("macd", "macd", {}), CalculationInstance("kdj", "kdj", {}),
             *(CalculationInstance("ma" + str(n), "ma", {"period": n}) for n in MA_PERIODS),
             CalculationInstance("boll", "boll", {}))
    return CalculationRequest("stock", "600000.SH", "1m", items, adjustment="qfq", limit=1000)


def _validate_result(result, reference):
    """Compare to the saved independent reference, never to another new call."""
    assert result.range.count == len(result.times) == 1000 and result.msg == ""
    assert result.series.adjustment == "qfq" and result.series.ts_code == "600000.SH"
    assert result.statistics.source_rows == 1500
    assert result.statistics.price_conversion_batches == 0
    assert result.times[0] == _time_for(3001) and result.times[-1] == _time_for(4000)
    assert all(left < right for left, right in zip(result.times, result.times[1:]))
    values = {item.instance_id: dict(item.fields) for item in result.calculations}
    assert set(values) == {"macd", "kdj", "boll", *("ma" + str(n) for n in MA_PERIODS)}
    expected = []
    for name, columns in (("macd", ("dif", "dea", "hist")), ("kdj", ("k", "d", "j"))):
        assert set(values[name]) == set(columns)
        for index, field in enumerate(columns, 1):
            expected.append((values[name][field], tuple(row[index] for row in reference[name][3000:4000])))
    for index, n in enumerate(MA_PERIODS, 4):
        assert set(values["ma" + str(n)]) == {"value"}
        expected.append((values["ma" + str(n)]["value"],
                         tuple(row[index] for row in reference["windows"][3000:4000])))
    assert set(values["boll"]) == {"middle", "upper", "lower"}
    for field, index in (("middle", 11), ("upper", 13), ("lower", 14)):
        expected.append((values["boll"][field], tuple(row[index] for row in reference["windows"][3000:4000])))
    # Materialize each reference projection immediately: a later loop variable
    # must not silently change which independently saved column is compared.
    for actual, wanted in expected:
        assert len(actual) == 1000
        for got, want in zip(actual, wanted, strict=True):
            if want is None:
                assert got is None
            else:
                assert got is not None and abs(got - want) <= 1e-8 + 1e-10 * abs(want)
    for item in result.calculations:
        assert item.algorithm_version and isinstance(item.parameters, tuple)


def _time_for(position):
    # This is only fixture time metadata, not indicator arithmetic.
    day, minute = divmod(position - 1, 240)
    base = datetime(2026, 1, 2, tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(days=day)
    return base + (timedelta(hours=9, minutes=31 + minute) if minute < 120
                   else timedelta(hours=13, minutes=1 + minute - 120))


def _prepare_source(root, progress):
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = root / "gold/quote/stk_mins_qfq/freq=1/ts_code=600000.SH/year=2026/part-000.parquet"
    path.parent.mkdir(parents=True, exist_ok=False)
    progress["fixture"] = {"status": "running", "root": str(root), "file": str(path)}
    con = duckdb.connect(":memory:", config={"threads": 1, "memory_limit": "128MiB",
                                           "max_temp_directory_size": "0B"})
    started = monotonic()
    try:
        # The formula is the previously accepted four-thousand-row producer;
        # only its date is aligned to the explicitly approved 2026 partition.
        progress["input_rows"] += 4000
        progress["sql_logical_rows"] += 4000
        _write(REPORT / "progress.json", progress)
        con.execute("""CREATE TEMP TABLE d4_bars AS
          WITH numbered AS (SELECT i::BIGINT AS seq,10000+3*(i%11)-5*(i%7) AS cents,
            DATE '2026-01-02'+CAST(floor((i-1)/240) AS INTEGER) AS day,
            (i-1)%240 AS minute_index FROM range(1,4001) t(i))
          SELECT *,CAST(day AS TIMESTAMP)+CASE WHEN minute_index<120
            THEN INTERVAL 9 HOUR+INTERVAL 31 MINUTE+minute_index*INTERVAL 1 MINUTE
            ELSE INTERVAL 13 HOUR+INTERVAL 1 MINUTE+(minute_index-120)*INTERVAL 1 MINUTE
            END AS bar_time FROM numbered ORDER BY seq""")
        progress["sql_logical_rows"] += 4000
        _write(REPORT / "progress.json", progress)
        copied = con.execute("""COPY (SELECT '600000.SH'::VARCHAR AS ts_code,
          day::DATE AS trade_date,bar_time::TIMESTAMP AS trade_time,
          cents/100.0 AS "open",(cents+100)/100.0 AS "high",(cents-100)/100.0 AS "low",
          cents/100.0 AS "close",100.0::DOUBLE AS vol,1000.0::DOUBLE AS amount
          FROM d4_bars ORDER BY seq) TO $target (FORMAT PARQUET, ROW_GROUP_SIZE 8192)""",
          {"target": str(path)}).fetchall()
        assert copied == [(4000,)]
        schema = pa.schema([("ts_code", pa.string()), ("trade_date", pa.date32()),
                            ("trade_time", pa.timestamp("us")),
                            *((n, pa.float64()) for n in ("open", "high", "low", "close", "vol", "amount"))])
        with pq.ParquetFile(path) as reader:
            assert reader.schema_arrow == schema
            assert reader.metadata.num_rows == 4000 and reader.metadata.num_row_groups == 1
            date_stats = reader.metadata.row_group(0).column(1).statistics
            assert date_stats.min.year == date_stats.max.year == 2026
        progress["fixture"].update(status="passed", file_bytes=path.stat().st_size,
                                    schema="canonical minute contract", row_groups=1)
    except BaseException as error:
        progress["fixture"].update(status="failed", error=_error(error))
        raise
    finally:
        con.close()
        progress["fixture"]["connection_closed"] = True
        progress["fixture"]["elapsed_seconds"] = monotonic() - started
        _write(REPORT / "progress.json", progress)
    assert progress["fixture"]["elapsed_seconds"] <= 5


class _Gate:
    def __init__(self, loop):
        import anyio
        self.loop = loop
        self.entered = anyio.Event()
        self.release = threading.Event()
        self.used = False

    def reached(self):
        if not self.used:
            self.used = True
            self.loop.call_soon_threadsafe(self.entered.set)
            if not self.release.wait(5):
                raise AssertionError("The fixed D4 read/compute gate was not released")


class _Node:
    def __init__(self, name, root):
        self.name, self.root = name, root
        self.path = REPORT / ("node_" + name + "_resume_01.json")
        assert not self.path.exists(), "Do not rerun a previously attempted D4 node"
        self.started = monotonic()
        self.lock = threading.RLock()
        self.calls = []
        self.controls = []
        self.gates = []
        self.runtimes = []
        self.record = {"name": name, "status": "running", "calls": self.calls,
                       "real_controls": 0, "price_rows": 0, "locator_rows": 0,
                       "sql_logical_rows": 0, "health": [], "actual_file_read_bytes": None,
                       "actual_file_read_bytes_reason": "No reliable per-request OS I/O byte counter",
                       "native_SQL_interrupt_evidence": "reused D2; not newly claimed by this case"}
        self.record["independent_reference_sha256"] = hashlib.sha256(REFERENCE.read_bytes()).hexdigest()
        self.references = _read(REFERENCE)
        self.save()

    def save(self):
        with self.lock:
            self.record["elapsed_seconds"] = monotonic() - self.started
            self.record["price_rows"] = sum(c.get("price_rows", 0) for c in self.calls)
            self.record["locator_rows"] = sum(c.get("locator_rows", 0) for c in self.calls)
            self.record["sql_logical_rows"] = sum(c.get("sql_logical_rows", 0) for c in self.calls)
            # Each thread updates its own call. Copy each dictionary atomically
            # before JSON walks it, so another call adding a diagnostic field
            # cannot change that dictionary's size midway through encoding.
            snapshot = dict(self.record)
            snapshot["calls"] = [dict(call) for call in self.calls]
            _write(self.path, snapshot)

    def call_for(self, control):
        return self.calls[self.controls.index(control)]

    def budget(self):
        count = REQUEST_COUNTS[NODES.index(self.name)]
        assert len(self.controls) <= count
        assert self.record["price_rows"] <= count * 1500
        assert self.record["locator_rows"] <= count * 8000
        assert self.record["sql_logical_rows"] <= count * 80315
        assert monotonic() - self.started <= 30

    @contextmanager
    def observe_execution(self):
        import anyio
        import duckdb
        from src.app.runtime.technical_indicators import execution
        from src.foundation.technical_indicators.errors import OutputEncodingError

        original_control = execution.ExecutionControl
        original_service = execution.TechnicalIndicatorService
        original_encode = execution.encode_response_utf8
        state = self

        class ObservedControl(original_control):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.d4_stopped = anyio.Event()
                self.d4_loop = __import__("asyncio").get_running_loop()
                with state.lock:
                    state.controls.append(self)
                    state.calls.append({"status": "created", "arrived_at": self.arrived_at,
                                        "work_until": self.work_until, "target_finish": self.target_finish})
                    state.record["real_controls"] += 1
                    state.save()
                    state.budget()

            def request_stop(self, reason):
                super().request_stop(reason)
                self.d4_loop.call_soon_threadsafe(self.d4_stopped.set)

        class ObservedService(original_service):
            def _open_execution(self, control):
                connection, executor = super()._open_execution(control)
                self.d4_connection, self.d4_executor = connection, executor
                try:
                    started = monotonic()
                    settings = connection.execute("SELECT current_setting('temp_directory'), "
                        "current_setting('max_temp_directory_size'), current_setting('threads'), "
                        "current_setting('memory_limit')").fetchone()
                    entry = state.call_for(control)
                    entry["actual_connection_settings"] = dict(zip(
                        ("temp_directory", "max_temp_directory_size", "threads", "memory_limit"), settings))
                    entry["metadata_setting_query_seconds"] = monotonic() - started
                    entry["metadata_setting_query_price_logical_rows"] = 0
                    assert re.fullmatch(r"0(?:\.0*)?\s*(?:[kmgtpe]i?b|bytes?)?",
                                        str(settings[1]), re.IGNORECASE), settings
                    assert int(settings[2]) == 1
                except BaseException as error:
                    # The caller has not yet received this open connection.
                    # A diagnostic metadata failure must not lose its owner.
                    cleanup = original_service._close_execution(self, control, connection)
                    for item in cleanup:
                        error.add_note(f"Diagnostic setup cleanup: {type(item).__name__}: {item}")
                    state.call_for(control)["setup_connection_closed"] = not cleanup
                    raise
                return connection, executor

            def calculate(self, request):
                entry = state.call_for(self.control)
                entry["worker_thread"] = threading.get_ident()
                try:
                    result = super().calculate(request)
                    _validate_result(result, state.references)
                    entry["calculation_result_verified"] = True
                    entry["status"] = "calculated"
                    return result
                except BaseException as error:
                    entry.update(status="calculation_error", error=_error(error))
                    raise
                finally:
                    state.save()

            def _close_execution(self, control, connection, **kwargs):
                errors = super()._close_execution(control, connection, **kwargs)
                executor = getattr(self, "d4_executor", None)
                entry = state.call_for(control)
                entry["sql_logical_rows"] = executor.sql_processed_rows if executor is not None else 0
                entry["steps"] = [dict(name=s.step_name, rows=s.logical_input_rows,
                                       output_rows=s.output_rows, failed=s.failed)
                                  for s in executor.statistics] if executor is not None else []
                entry["live_tables"] = sorted(executor._live_tables) if executor is not None else []
                entry["live_arrow"] = sorted(executor._live_arrow) if executor is not None else []
                entry.update(stop_reason=control.stop_reason, stop_requested_at=control.stop_requested_at,
                             sql_returned_at=control.sql_returned_at, resources_released_at=control.resources_released_at,
                             monitor_join_ms=control.monitor_join_elapsed_ms,
                             stop_monitor_ms=control.stop_monitor_elapsed_ms,
                             interrupt_count=control.interrupt_count, monitor_finished=control.monitor is None,
                             cleanup_errors=[_error(e) for e in errors])
                if connection is not None:
                    entry["sql_logical_rows"] += 1
                    try:
                        connection.execute("SELECT 1")
                    except duckdb.ConnectionException:
                        entry["connection_closed"] = True
                    else:
                        raise AssertionError("A D4 request left its connection open")
                state.save()
                assert not entry["live_tables"] and not entry["live_arrow"]
                assert not errors and control.cleanup_ready and control.resources_released_at is not None
                return errors

        def broken_encode(payload, **kwargs):
            # Exercise the real JSON encoder's raw TypeError -> OutputEncodingError
            # path after the actual result has been generated and independently checked.
            try:
                return original_encode({"unsupported": object()}, **kwargs)
            except OutputEncodingError as error:
                assert isinstance(error.__cause__, TypeError)
                raise

        execution.ExecutionControl = ObservedControl
        execution.TechnicalIndicatorService = ObservedService
        if self.name == "encoding_failure":
            execution.encode_response_utf8 = broken_encode
        try:
            yield
        finally:
            execution.ExecutionControl = original_control
            execution.TechnicalIndicatorService = original_service
            execution.encode_response_utf8 = original_encode

    def wrap_source(self, source, gate=None):
        state = self
        original_create, original_open = source.create_locator, source.open

        def create(executor, requirement, *, read_context):
            entry = state.call_for(executor.control)
            old = read_context.record_price_rows

            def record(rows):
                entry["price_rows"] = entry.get("price_rows", 0) + rows
                return old(rows)

            read_context.record_price_rows = record
            actual = original_create(executor, requirement, read_context=read_context)

            class Locator:
                def describe(self):
                    description = actual.describe()
                    entry["locator_rows"] = read_context.locator_rows
                    entry["selected_preceding_rows"] = description.selection.preceding_rows
                    entry["selected_target_rows"] = description.selection.target_rows
                    entry["source_files"] = read_context.source_files
                    entry["source_file_bytes"] = read_context.source_file_bytes
                    return description

                def close(self):
                    try:
                        return actual.close()
                    finally:
                        # describe can fail after delivering keys. Charge its
                        # actual context even when it never returned a description.
                        entry["locator_rows"] = read_context.locator_rows
                        entry["source_files"] = read_context.source_files
                        entry["source_file_bytes"] = read_context.source_file_bytes
                        entry["locator_closed"] = actual._closed
                        state.save()

            return Locator()

        def open_stream(executor, description, requirement, *, read_context):
            actual = original_open(executor, description, requirement, read_context=read_context)
            entry = state.call_for(executor.control)

            class Stream:
                def next_batch(self, count):
                    batch = actual.next_batch(count)
                    if batch is not None:
                        entry.setdefault("batches", []).append(batch.selected_rows)
                        if gate is not None:
                            gate.reached()
                    return batch

                def release_current_batch(self):
                    return actual.release_current_batch()

                def close(self):
                    actual.close()
                    entry["stream_closed"] = actual._closed
                    entry["reader_refs_cleared"] = all(getattr(actual, name) is None for name in
                        ("_reader", "_scanner", "_fragment", "_current_batch", "_pending_batch"))
                    state.save()

            return Stream()

        source.create_locator, source.open = create, open_stream

    def runtime(self, gate=None):
        from src.app.runtime.technical_indicators.composition import create_runtime
        from src.foundation.config.settings import Settings

        runtime = create_runtime(Settings(_env_file=None, GOLDENSHARE_LAKE_ROOT=str(self.root)))
        self.wrap_source(runtime.source, gate)
        self.runtimes.append(runtime)
        original_release = runtime.admission.release

        def release(lease):
            entry = self.call_for(lease.control)
            assert entry.get("connection_closed") and entry.get("monitor_finished")
            assert not entry.get("live_tables") and not entry.get("live_arrow")
            original_release(lease)
            entry["lease_released_at"] = monotonic()
            entry["lease_released"] = True
            self.save()

        runtime.admission.release = release
        return runtime

    async def http(self, runtime, outcome, *, disconnect=None, sending=None, allow_send=None):
        import anyio
        from src.app.runtime.technical_indicators.execution import execute_http

        disconnect = disconnect or anyio.Event()
        sent = []

        async def receive():
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body" and sending is not None:
                sending.set()
                await allow_send.wait()
            sent.append(message)

        try:
            await execute_http(runtime, _request(), arrived_at=monotonic(), receive=receive, send=send)
            assert [message["type"] for message in sent] == ["http.response.start", "http.response.body"]
            assert sent[0]["status"] == 200 and not sent[1].get("more_body", False)
            body = sent[1]["body"]
            payload = json.loads(body)
            assert payload["range"]["count"] == len(payload["times"]) == 1000
            assert len(payload["calculations"]) == 10 and payload["msg"] == ""
            assert len(body) <= 5000000
            outcome.update(status="passed", output_bytes=len(body), response_messages=2)
        except BaseException as error:
            outcome.update(status="error", error=error, sent_messages=len(sent))
        finally:
            sent.clear()

    async def library(self, runtime, outcome, *, cancel_scope=None):
        from src.app.runtime.technical_indicators.execution import execute_library

        async def invoke():
            try:
                result = await execute_library(runtime, _request(), arrived_at=monotonic())
                _validate_result(result, self.references)
                outcome.update(status="passed", output_rows=result.range.count)
            except BaseException as error:
                outcome.update(status="error", error=error)

        if cancel_scope is not None:
            with cancel_scope:
                await invoke()
        else:
            await invoke()

    async def run(self):
        import asyncio
        import anyio
        from src.foundation.technical_indicators.errors import CalculationCancelledError, OutputEncodingError

        outcomes = []
        try:
            with self.observe_execution():
                if self.name == "single_http":
                    runtime = self.runtime()
                    outcome = {}; outcomes.append(outcome)
                    await self.http(runtime, outcome)
                    assert outcome["status"] == "passed", outcome
                elif self.name == "dual_http":
                    # Two independent sources use the same immutable fixture;
                    # one runtime/source remains genuinely shared by both calls.
                    gates = [_Gate(asyncio.get_running_loop()), _Gate(asyncio.get_running_loop())]
                    self.gates.extend(gates)
                    runtime = self.runtime()
                    original_open = runtime.source.open
                    assigned = 0

                    def gated_open(executor, description, requirement, *, read_context):
                        nonlocal assigned
                        actual = original_open(executor, description, requirement, read_context=read_context)
                        with self.lock:
                            gate = gates[assigned]
                            assigned += 1
                        original_next = actual.next_batch

                        def next_batch(count):
                            batch = original_next(count)
                            if batch is not None:
                                gate.reached()
                            return batch

                        actual.next_batch = next_batch
                        return actual

                    runtime.source.open = gated_open
                    outcomes.extend(({}, {}))
                    async with anyio.create_task_group() as group:
                        group.start_soon(self.http, runtime, outcomes[0])
                        group.start_soon(self.http, runtime, outcomes[1])
                        for gate in gates:
                            with anyio.fail_after(5):
                                await gate.entered.wait()
                        assert len(runtime.admission.active_leases) == 2
                        for _ in range(3):
                            started = monotonic()
                            # An isolated same-loop ASGI health path performs no I/O.
                            messages = []
                            async def health_send(message):
                                messages.append(message)
                            async def health_receive():
                                raise AssertionError("The no-body health request does not read input")
                            async def health_app(scope, receive, send):
                                assert scope["type"] == "http" and scope["path"] == "/health"
                                await send({"type": "http.response.start", "status": 200, "headers": []})
                                await send({"type": "http.response.body", "body": b"ok", "more_body": False})
                            await health_app({"type": "http", "path": "/health"}, health_receive, health_send)
                            elapsed = monotonic() - started
                            assert elapsed <= .2 and len(messages) == 2
                            self.record["health"].append({"elapsed_ms": elapsed * 1000, "status": 200})
                        for gate in gates:
                            gate.release.set()
                    assert all(item["status"] == "passed" for item in outcomes), outcomes
                    assert len({c["worker_thread"] for c in self.calls}) == 2
                elif self.name in ("shutdown_and_normal", "read_cancel_and_normal"):
                    gate = _Gate(asyncio.get_running_loop()); self.gates.append(gate)
                    runtime = self.runtime(gate)
                    outcome = {}; outcomes.append(outcome)
                    scope = anyio.CancelScope()
                    async with anyio.create_task_group() as group:
                        async def first():
                            await self.library(runtime, outcome, cancel_scope=scope)
                        group.start_soon(first)
                        with anyio.fail_after(5):
                            await gate.entered.wait()
                        if self.name == "shutdown_and_normal":
                            group.start_soon(runtime.aclose)
                        else:
                            scope.cancel()
                        with anyio.fail_after(5):
                            await self.controls[0].d4_stopped.wait()
                        assert runtime.admission.active_leases
                        gate.release.set()
                    assert outcome["status"] == "error"
                    assert isinstance(outcome["error"], (CalculationCancelledError, anyio.get_cancelled_exc_class()))
                    assert self.calls[0].get("lease_released")
                    normal_runtime = self.runtime() if self.name == "shutdown_and_normal" else runtime
                    normal = {}; outcomes.append(normal)
                    await self.library(normal_runtime, normal)
                    assert normal["status"] == "passed", normal
                elif self.name == "slow_send":
                    runtime = self.runtime()
                    sending, allow = anyio.Event(), anyio.Event()
                    outcome = {}; outcomes.append(outcome)
                    async with anyio.create_task_group() as group:
                        async def invoke():
                            await self.http(runtime, outcome, sending=sending, allow_send=allow)
                        group.start_soon(invoke)
                        with anyio.fail_after(5):
                            await sending.wait()
                        assert len(runtime.admission.active_leases) == 1
                        assert self.calls[0].get("connection_closed") and not self.calls[0].get("lease_released")
                        await anyio.sleep(0)
                        assert runtime.admission.active_leases
                        allow.set()
                    assert outcome["status"] == "passed", outcome
                elif self.name == "disconnect":
                    gate = _Gate(asyncio.get_running_loop()); self.gates.append(gate)
                    runtime = self.runtime(gate)
                    disconnect = anyio.Event()
                    outcome = {}; outcomes.append(outcome)
                    async with anyio.create_task_group() as group:
                        async def invoke():
                            await self.http(runtime, outcome, disconnect=disconnect)
                        group.start_soon(invoke)
                        with anyio.fail_after(5):
                            await gate.entered.wait()
                        disconnect.set()
                        with anyio.fail_after(5):
                            await self.controls[0].d4_stopped.wait()
                        assert runtime.admission.active_leases
                        gate.release.set()
                    assert outcome["status"] == "error" and outcome["sent_messages"] == 0
                    assert isinstance(outcome["error"], (CalculationCancelledError, anyio.get_cancelled_exc_class()))
                elif self.name == "encoding_failure":
                    runtime = self.runtime()
                    outcome = {}; outcomes.append(outcome)
                    await self.http(runtime, outcome)
                    error = outcome.get("error")
                    assert isinstance(error, OutputEncodingError) and isinstance(error.__cause__, TypeError)
                    assert outcome["sent_messages"] == 0
                    seen, pending, cleared = set(), [error], 0
                    while pending:
                        current = pending.pop()
                        if id(current) in seen:
                            continue
                        seen.add(id(current))
                        pending.extend(e for e in (current.__cause__, current.__context__) if e is not None)
                        tb = current.__traceback__
                        while tb is not None:
                            if tb.tb_frame.f_code.co_filename.endswith("technical_indicators/output/encoding.py"):
                                assert tb.tb_frame.f_locals == {}
                                cleared += 1
                            tb = tb.tb_next
                    assert cleared
                    self.record["ended_encoding_error_frames_cleared"] = cleared
                else:
                    raise AssertionError("Unknown D4 node")
        finally:
            for gate in self.gates:
                gate.release.set()
            with anyio.CancelScope(shield=True):
                for runtime in self.runtimes:
                    await runtime.aclose()
                    assert not runtime.admission.active_leases
            self.record["outcomes"] = [{k: (_error(v) if isinstance(v, BaseException) else v)
                                        for k, v in item.items()} for item in outcomes]
            for item in outcomes:
                item.clear()
            self.save()
        assert len(self.calls) == REQUEST_COUNTS[NODES.index(self.name)]
        assert all(c.get("connection_closed") and c.get("monitor_finished") and
                   c.get("lease_released") and c.get("locator_closed") and c.get("stream_closed") and
                   c.get("reader_refs_cleared") for c in self.calls)
        assert all(c.get("selected_preceding_rows") == 500 and c.get("selected_target_rows") == 1000
                   for c in self.calls)
        assert all(c.get("price_rows") == 1500 and c.get("locator_rows") == 8000 for c in self.calls)
        self.budget()


def _run_node(name, root):
    import anyio

    state = _Node(name, root)
    state.record.update(pid=os.getpid(), node_working_directory=str(Path.cwd()),
                        starting_threads=[t.name for t in threading.enumerate()],
                        memory_validation="not_measured_estimate_only_by_administrator_decision",
                        memory_estimate_basis="LLD 16.2; 1500 input / 1000 output / 16 numeric fields",
                        memory_estimate_request_MiB=256,
                        memory_estimate_dual_MiB=512)
    try:
        anyio.run(state.run, backend="asyncio")
        state.record.update(ending_threads=[t.name for t in threading.enumerate()],
                            actual_computed_disk_write_bytes=None,
                            actual_computed_disk_write_bytes_reason="No reliable per-request OS disk write byte counter",
                            computed_temporary_disk_evidence="actual private connection max_temp_directory_size=0; owned/node directory inspection; D2 low-memory evidence reused")
        temporary_files = sorted({str(path) for base in (root, Path.cwd())
                                  for pattern in ("duckdb_temp*", "*.tmp/duckdb*")
                                  for path in base.rglob(pattern) if path.is_file()})
        state.record["observed_computed_temporary_files"] = temporary_files
        assert temporary_files == []
        state.record["status"] = "passed"
    except BaseException as error:
        state.record.update(status="failed_stop_without_retry", error=_error(error),
                            ending_threads=[t.name for t in threading.enumerate()])
        raise
    finally:
        state.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", choices=NODES)
    parser.add_argument("--owned-root", type=Path)
    arguments = parser.parse_args()
    if arguments.node is not None:
        assert arguments.owned_root is not None and arguments.owned_root.is_dir()
        _run_node(arguments.node, arguments.owned_root)
        return
    assert arguments.owned_root is None
    plan, progress, resume = _read(REPORT / "plan.json"), _read(REPORT / "progress.json"), _read(RESUME_PLAN)
    baseline_path = REPORT / resume["baseline_file"]
    assert hashlib.sha256(baseline_path.read_bytes()).hexdigest() == resume["baseline_sha256"]
    baseline = _read(baseline_path)
    assert resume["status"] == "approved_before_implementation"
    assert hashlib.sha256((REPORT / "progress.json").read_bytes()).hexdigest() == resume["progress_sha256_before_resume"]
    assert not progress.get("resume_execution_started"), "Do not restart an attempted D4 resumption"
    assert progress["status"] == "paused_after_first_real_attempt"
    assert progress["diagnostic_status"] == "failed_stop_without_retry"
    assert plan["real_nodes"] == resume["real_nodes"] == list(NODES)
    assert plan["real_request_counts"] == resume["real_request_counts"] == list(REQUEST_COUNTS)
    assert all(progress[key] == baseline[key] == value for key, value in
               (("input_rows", 4000), ("locator_rows", 0), ("sql_logical_rows", 8000), ("real_controls", 0)))
    assert progress["owned_root_removed"] and not baseline["calls"]
    assert set(plan["light_test_nodes"]) <= set(progress["completed_nodes"])
    assert all(n["status"] == "passed" for n in progress["light_nodes"])
    historical = _read(REPORT / "node_single_http.json")
    assert historical["status"] == "failed_before_node_record" and historical["real_controls"] == 0
    assert not any((REPORT / ("node_" + name + "_resume_01.json")).exists() for name in NODES)
    for file, digest in {**resume["protected_code_sha256"], **resume["protected_app_and_light_sha256"],
                         **resume["execution_code_sha256"]}.items():
        assert hashlib.sha256((ROOT / file).read_bytes()).hexdigest() == digest, file
    started = monotonic()
    prior_seconds = baseline["program_seconds"] + resume["preexecution_static_seconds"]
    progress.update(status="resumed_real_running", diagnostic_status="resumed_running",
                    resume_execution_started=True, resume_nodes=[], resume_program_seconds=0,
                    resume_authorization=resume["authorization"],
                    memory_validation_status="not_measured_estimate_only_by_administrator_decision")
    temporary = TemporaryDirectory(prefix="ti_d4_resume_", dir="/private/tmp")
    owned = Path(temporary.name)
    progress["owned_root"] = str(owned)
    progress["owned_root_removed"] = False
    _write(REPORT / "progress.json", progress)
    try:
        _prepare_source(owned, progress)
        for name in NODES:
            node_started = monotonic()
            node_working_directory = owned / ("work_" + name)
            node_working_directory.mkdir()
            command = [sys.executable, "-m", "scripts.diagnostics.technical_indicator_resources",
                       "--node", name, "--owned-root", str(owned)]
            environment = dict(os.environ, PYTHONPATH=str(ROOT))
            process = subprocess.Popen(command, cwd=node_working_directory, env=environment,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            timeout = False
            try:
                output, _ = process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                timeout = True
                # Keep ownership until actual exit, even when the target is missed.
                output, _ = process.communicate()
            elapsed = monotonic() - node_started
            (REPORT / ("node_" + name + "_resume_01_output.txt")).write_text(output)
            node_path = REPORT / ("node_" + name + "_resume_01.json")
            actual = _read(node_path) if node_path.exists() else {
                "name": name, "status": "failed_before_node_record", "real_controls": 0,
                "price_rows": 0, "locator_rows": 0, "sql_logical_rows": 0}
            actual.update(program_elapsed_seconds=elapsed, returncode=process.returncode,
                          program_timeout=timeout)
            _write(node_path, actual)
            progress["input_rows"] += actual["price_rows"]
            progress["locator_rows"] += actual["locator_rows"]
            progress["sql_logical_rows"] += actual["sql_logical_rows"]
            progress["real_controls"] += actual["real_controls"]
            node_record = {"name": name, "status": actual["status"], "record": node_path.name}
            progress["real_nodes"].append(node_record)
            progress["resume_nodes"].append(node_record)
            progress["resume_program_seconds"] = monotonic() - started
            progress["program_seconds"] = prior_seconds + progress["resume_program_seconds"]
            _write(REPORT / "progress.json", progress)
            assert not timeout and process.returncode == 0 and actual["status"] == "passed", actual
            for field, limit in resume["cumulative_execution_upper_bounds"].items():
                assert progress[field] <= limit <= plan["including_reserve_budget"][field], (field, progress[field], limit)
            assert elapsed <= resume["per_program_seconds_limit"]
            assert progress["program_seconds"] <= resume["total_seconds_limit"]
        assert progress["real_controls"] == 10
        progress.update(status="resumed_real_passed_pending_final_audit", diagnostic_status="passed")
    except BaseException as error:
        progress.update(status="failed_stop_without_retry", diagnostic_status="failed_stop_without_retry",
                        resume_error=_error(error))
        raise
    finally:
        temporary.cleanup()
        progress["owned_root_removed"] = not owned.exists()
        progress["resume_program_seconds"] = monotonic() - started
        progress["real_program_seconds"] = baseline["real_program_seconds"] + progress["resume_program_seconds"]
        progress["program_seconds"] = prior_seconds + progress["resume_program_seconds"]
        progress["time_remaining_seconds"] = resume["total_seconds_limit"] - progress["program_seconds"]
        over_total = progress["program_seconds"] > resume["total_seconds_limit"]
        if over_total:
            progress.update(status="failed_stop_without_retry", diagnostic_status="failed_stop_without_retry",
                            resume_budget_error="Total program budget exceeded after final cleanup")
        _write(REPORT / "progress.json", progress)
        if not progress["owned_root_removed"]:
            raise AssertionError("The owned D4 fixture directory was not released")
        if over_total:
            raise AssertionError("Total D4 program time exceeded after final cleanup")
    acceptance = _read(REPORT / "acceptance.json")
    acceptance.update(status="fixed_real_nodes_passed_pending_final_audit", D4_complete=False,
                      real_nodes=progress["resume_nodes"],
                      counters={k: progress[k] for k in ("input_rows", "locator_rows", "sql_logical_rows", "real_controls")},
                      elapsed_seconds=progress["program_seconds"], owned_root_removed=True, automatic_retries=0,
                      memory_validation_status="not_measured_estimate_only_by_administrator_decision",
                      not_claimed=["formal Lake/API/page/XXM/DG migration", "RSS measurement", "P95", "new capacity/native interrupt acceptance"])
    _write(REPORT / "acceptance.json", acceptance)


if __name__ == "__main__":
    main()
