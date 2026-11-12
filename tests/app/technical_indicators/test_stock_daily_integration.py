"""LLD §08/16.2: common execution only; no stock Web registration in A/B.

Real Admission, request preparation, AnyIO worker, handoff, encoder and send.
Only Control and worker calculation are replaced with test doubles.
JUnit reports this function's costs; historical reports are never read/written.
"""

import asyncio
from dataclasses import replace
import inspect
import json
import threading
from time import monotonic
import weakref
from src.foundation.config.settings import Settings

import anyio
import pytest

from test_admission import FakeControl, light_case, make_config
from test_execution_cancellation import (
    inspect_release_locals, install_control, literal_result, runtime,
)
from src.app.runtime.technical_indicators import execution
from src.biz.services.wealth.market.stock_detail.stock_daily_kline_calculations import (
    STOCK_DAILY_CALCULATIONS,
)
from goldenshare_technical_indicators.contracts import (
    CalculationInstance, CalculationRequest, CalculationValues,
)
from goldenshare_technical_indicators.errors import OutputContractError, RequestInvalidError


class _Payload(dict):
    """A weak-referenceable value used only to check ended-frame ownership."""


def _literal_ten_results():
    # Fixed metadata and values from the LLD; no calculation or product helper.
    means = tuple(CalculationValues(f"ma{period}", "ma", "1.0.0", (("period", period),),
                                   (("value", (None,)),))
                  for period in (5, 10, 20, 30, 60, 90, 250))
    others = (
        CalculationValues("boll", "boll", "1.0.0", (("period", 20), ("multiplier", 2)),
                          (("middle", (None,)), ("upper", (None,)), ("lower", (None,)))),
        CalculationValues("macd", "macd", "2.0.0", (("fast", 12), ("slow", 26), ("signal", 9)),
                          (("dif", (0.0,)), ("dea", (0.0,)), ("hist", (0.0,)))),
        CalculationValues("kdj", "kdj", "2.0.0", (("window", 9), ("k_period", 3), ("d_period", 3)),
                          (("k", (50.0,)), ("d", (50.0,)), ("j", (50.0,)))),
    )
    return replace(literal_result(), calculations=means + others)


def test_single_work_and_existing_entries(monkeypatch, record_property):
    metrics = {"fake_controls": 0, "real_controls": 0, "calculate_stub_calls": 0,
               "input_rows": 0, "sql_logical_rows": 0}
    original_init = FakeControl.__init__

    def counted_init(control, *args, **kwargs):
        metrics["fake_controls"] += 1
        original_init(control, *args, **kwargs)

    monkeypatch.setattr(FakeControl, "__init__", counted_init)
    with light_case("test_single_work_and_existing_entries"):
        async def scenario():
            rt = runtime()
            controls = install_control(monkeypatch)
            main_thread = threading.get_ident()
            reference = _literal_ten_results()
            request = CalculationRequest("stock", "600000.SH", "day", STOCK_DAILY_CALCULATIONS)
            calls, releases, weak_values, faults = [], [], [], []
            mode = "normal"

            def calculate(service, prepared, *, control):
                metrics["calculate_stub_calls"] += 1
                assert threading.get_ident() != main_thread
                assert service.control is control is controls[-1]
                assert prepared.normalized is request
                assert len(prepared.normalized.calculations) == 10
                calls.append(prepared.normalized)
                if mode == "wrong_library_type":
                    value = _Payload(result="unsupported library result")
                    weak_values.append(weakref.ref(value))
                    return value
                return reference

            monkeypatch.setattr(execution.TechnicalIndicatorService, "_calculate_library", calculate)
            monkeypatch.setattr(execution.TechnicalIndicatorService, "_calculate_result", calculate)
            original_release = rt.admission.release

            def release(lease):
                inspect_release_locals(failure=mode == "group_failure")
                if mode == "group_failure":
                    assert weak_values[-1]() is None
                releases.append(lease)
                original_release(lease)

            monkeypatch.setattr(rt.admission, "release", release)

            async def invoke_http(*, private=False):
                never = anyio.Event()
                sent, observers = [], []

                async def receive():
                    observers.append("started")
                    try:
                        await never.wait()
                    finally:
                        observers.append("ended")

                async def send(message):
                    assert len(rt.admission.active_leases) == 1
                    sent.append(message)

                if private:
                    normalized = object()
                    invoked = []

                    def validate():
                        assert not rt.admission.active_leases
                        invoked.append("validate")
                        return normalized

                    def work(value, control):
                        assert threading.get_ident() != main_thread
                        assert value is normalized and control is controls[-1]
                        invoked.append("work")
                        return {"message": "内部结构化结果", "values": [None, 1.25]}

                    result = await execution._execute(
                        rt, arrived_at=monotonic(), validate_before_wait=validate, work=work,
                        receive=receive, send=send, response_content_type=b"application/json",
                    )
                    assert invoked == ["validate", "work"]
                    assert json.loads(sent[1]["body"]) == {
                        "message": "内部结构化结果", "values": [None, 1.25],
                    }
                else:
                    result = await execution.execute_http(
                        rt, request, arrived_at=monotonic(), receive=receive, send=send,
                    )
                    payload = json.loads(sent[1]["body"])
                    assert payload["times"] == ["2026-01-02"]
                    assert [item["instance_id"] for item in payload["calculations"]] == [
                        "ma5", "ma10", "ma20", "ma30", "ma60", "ma90", "ma250", "boll", "macd", "kdj",
                    ]
                    assert payload["calculations"][8]["fields"]["hist"] == [0.0]
                assert result is None and observers == ["started", "ended"]
                assert [item["type"] for item in sent] == ["http.response.start", "http.response.body"]
                headers = dict(sent[0]["headers"])
                assert headers[b"content-type"] == (
                    b"application/json" if private else b"application/json; charset=utf-8"
                )
                assert int(headers[b"content-length"]) == len(sent[1]["body"])
                assert sent[1]["more_body"] is False and not rt.admission.active_leases
                assert controls[-1].stop_reason is None

            try:
                assert await execution.execute_library(rt, request, arrived_at=monotonic()) is reference
                assert len(calls) == 1 and len(releases) == 1
                await invoke_http()
                assert len(calls) == 2 and len(releases) == 2
                await invoke_http(private=True)
                assert len(calls) == 2 and len(releases) == 3
                invalid = replace(request, calculations=(CalculationInstance("bad", "ma", {"period": 0}),))
                with monkeypatch.context() as blocked:
                    async def forbidden_acquire(control):
                        raise AssertionError("An invalid request entered admission")
                    blocked.setattr(rt.admission, "acquire", forbidden_acquire)
                    with pytest.raises(RequestInvalidError):
                        await execution.execute_library(rt, invalid, arrived_at=monotonic())
                assert len(calls) == 2 and len(releases) == 3
                mode = "wrong_library_type"
                with pytest.raises(OutputContractError) as caught:
                    await execution.execute_library(rt, request, arrived_at=monotonic())
                assert (caught.value.reason, caught.value.stage) == ("type_mismatch", "library_return")
                assert weak_values[-1]() is None
                assert len(calls) == 3 and len(releases) == 4
                mode = "group_failure"

                def fail_leaf():
                    value = _Payload(result="must not survive the original child error")
                    weak_values.append(weakref.ref(value))
                    raise ValueError("Controlled child failure")

                def failing_work(normalized, control):
                    child = None
                    try:
                        fail_leaf()
                    except ValueError as error:
                        child = error
                    group = ExceptionGroup("Controlled worker failures", [child])
                    faults.append(group)
                    # Outside except: no __context__ shortcut to the child.
                    raise group

                with pytest.raises(ExceptionGroup) as caught:
                    await execution._execute(
                        rt, arrived_at=monotonic(), validate_before_wait=lambda: request,
                        work=failing_work,
                    )
                assert caught.value is faults[0] and caught.value.__context__ is None
                assert isinstance(caught.value.exceptions[0], ValueError)
                assert weak_values[-1]() is None
                child_trace = caught.value.exceptions[0].__traceback__
                assert child_trace is not None
                while child_trace is not None:
                    assert child_trace.tb_frame.f_locals == {}
                    child_trace = child_trace.tb_next
                assert len(controls) == 6 and len(releases) == 5
                assert not rt.admission.active_leases and not rt.admission.waiters
                assert list(inspect.signature(execution.execute_library).parameters) == [
                    "runtime", "request", "arrived_at",
                ]
                assert list(inspect.signature(execution.execute_http).parameters) == [
                    "runtime", "request", "arrived_at", "receive", "send",
                ]
            finally:
                await rt.aclose()

        try:
            anyio.run(scenario)
            assert metrics["fake_controls"] == 6 and metrics["calculate_stub_calls"] == 3
        finally:
            record_property("stock_daily_step12_metrics", json.dumps(metrics, sort_keys=True))


def _scope(method="GET", path="/api/v1/wealth/market/stock-detail/kline"):
    return {"type": "http", "method": method, "path": path, "raw_path": path.encode(),
            "headers": [(b"x-request-id", b"stock-step3")], "query_string": b"", "scheme": "http",
            "server": ("test", 80), "client": ("test", 1), "http_version": "1.1", "state": {}}


def test_actual_send_holds_lease(monkeypatch, record_property):
    from src.app.web.middleware.access_log import AccessLogMiddleware
    from src.app.web.middleware.request_id import RequestIdMiddleware
    from tests.stock_daily_kline_helpers import controlled_controls, make_runtime

    with controlled_controls(monkeypatch, record_property):
        async def scenario():
            rt = make_runtime()
            sending, finish, never = anyio.Event(), anyio.Event(), anyio.Event()
            sent = []
            scope = _scope()

            async def inner(scope, receive, send):
                assert scope["state"]["stock_daily_arrived_at"] <= monotonic()
                await execution._execute(
                    rt, arrived_at=scope["state"]["stock_daily_arrived_at"],
                    validate_before_wait=lambda: None, work=lambda value, control: {"unchanged": "中文"},
                    receive=receive, send=send, response_content_type=b"application/json",
                )

            async def receive():
                await never.wait()

            async def send(message):
                assert len(rt.admission.active_leases) == 1
                if message["type"] == "http.response.body":
                    sending.set()
                    await finish.wait()
                sent.append(message)

            try:
                async with anyio.create_task_group() as group:
                    group.start_soon(AccessLogMiddleware(RequestIdMiddleware(inner)), scope, receive, send)
                    await sending.wait()
                    assert len(rt.admission.active_leases) == 1
                    finish.set()
                assert not rt.admission.active_leases
                assert dict(sent[0]["headers"])[b"x-request-id"] == b"stock-step3"
                assert dict(sent[0]["headers"])[b"content-type"] == b"application/json"
                assert json.loads(sent[1]["body"]) == {"unchanged": "中文"}
            finally:
                await rt.aclose()
        anyio.run(scenario)


def test_cancel_and_cleanup_release_once(monkeypatch, record_property):
    from contextlib import contextmanager
    from datetime import date
    from src.app.dependencies import stock_daily_technical_indicators as wiring
    from goldenshare_technical_indicators.errors import CalculationCancelledError, ResourceCleanupError
    from tests.stock_daily_kline_helpers import controlled_controls, make_runtime, result_for
    from tests.test_stock_daily_kline_service import _request, _row, _source

    with controlled_controls(monkeypatch, record_property) as (create, controls):
        async def scenario():
            rt = make_runtime()
            backend = wiring.StockDailyKlineAppBackend(
                rt, lambda: object(), settings=Settings(_env_file=None, APP_ENV="prod"),
            )
            source = _source((_row(date(2026, 1, 5)),))
            started, stopped = anyio.Event(), anyio.Event()
            gate = threading.Event()
            loop = asyncio.get_running_loop()
            events, failures, scopes, references = [], [], [], []
            mode = "cancel"
            original_release = rt.admission.release

            def factory(**kwargs):
                control = create(**kwargs)
                original = control.request_stop
                def stop(reason):
                    original(reason)
                    loop.call_soon_threadsafe(stopped.set)
                control.request_stop = stop
                return control

            monkeypatch.setattr(execution, "ExecutionControl", factory)

            @contextmanager
            def session(factory, control):
                owner = threading.get_ident()
                events.append(("open", owner))
                try:
                    yield object()
                finally:
                    events.append(("close", threading.get_ident()))
                    assert threading.get_ident() == owner
                    if mode == "close_failure":
                        raise ResourceCleanupError("Controlled close failure")

            def prepare(session, request, *, load_rows):
                assert threading.get_ident() != threading.main_thread().ident
                events.append(("prepare", threading.get_ident()))
                return replace(source, request=request)

            def calculate(service, request):
                assert events[-1][0] == "close"
                events.append(("calculate", threading.get_ident()))
                if mode == "cancel":
                    loop.call_soon_threadsafe(started.set)
                    assert gate.wait(2)
                return result_for(source.ts_code, (date(2026, 1, 5),))

            def release(lease):
                inspect_release_locals(failure=True)
                if mode == "dto_failure":
                    assert references[-1]() is None
                events.append(("release", threading.get_ident()))
                original_release(lease)

            monkeypatch.setattr(wiring, "open_stock_daily_read_session", session)
            monkeypatch.setattr(backend.service, "prepare", prepare)
            monkeypatch.setattr(execution.TechnicalIndicatorService, "calculate", calculate)
            monkeypatch.setattr(rt.admission, "release", release)

            async def invoke():
                with anyio.CancelScope() as scope:
                    scopes.append(scope)
                    try:
                        await execution._execute(rt, arrived_at=monotonic(),
                            validate_before_wait=lambda: backend.validate_before_wait(_request()),
                            work=backend.work)
                    except BaseException as error:
                        failures.append(error)

            try:
                async with anyio.create_task_group() as group:
                    group.start_soon(invoke)
                    await started.wait()
                    scopes[0].cancel()
                    await stopped.wait()
                    assert len(rt.admission.active_leases) == 1
                    gate.set()
                assert len(failures) == 1
                assert isinstance(failures[0], (CalculationCancelledError, anyio.get_cancelled_exc_class()))
                assert [name for name, _ in events].count("release") == 1
                mode = "close_failure"
                await invoke()
                assert isinstance(failures[-1], ResourceCleanupError)
                assert [name for name, _ in events].count("calculate") == 1
                assert [name for name, _ in events].count("release") == 2

                # The LLD's DTO branch must discard Pydantic's input-owning error.
                from src.biz.services.wealth.market.stock_detail import stock_daily_kline_service as mapping
                real_dto = mapping.StockDetailKlineResponseDto
                def bad_dto(**kwargs):
                    value = _Payload(invalid="not a valid context")
                    references.append(weakref.ref(value))
                    return real_dto.model_validate({"pageContext": value})
                monkeypatch.setattr(mapping, "StockDetailKlineResponseDto", bad_dto)
                mode = "dto_failure"
                await invoke()
                error = failures[-1]
                assert isinstance(error, OutputContractError) and error.reason == "dto_validation_failed"
                assert error.__cause__ is None and error.__context__ is None
                assert len(error.diagnostics["issues"]) <= 4
                assert references[-1]() is None
                assert [name for name, _ in events].count("release") == 3
                assert len(controls) == 3 and not rt.admission.active_leases
            finally:
                gate.set()
                await rt.aclose()
        anyio.run(scenario)


def test_legacy_payload_encoding(monkeypatch, record_property):
    from tests.stock_daily_kline_helpers import controlled_controls, make_runtime
    payload = {"debugInfo": None, "bars": [], "label": "中文"}
    expected = b'{"debugInfo":null,"bars":[],"label":"' + "中文".encode("utf-8") + b'"}'
    with controlled_controls(monkeypatch, record_property):
        async def scenario():
            rt = make_runtime()
            sent, never = [], anyio.Event()

            async def receive():
                await never.wait()

            async def send(message):
                sent.append(message)

            try:
                await execution._execute(rt, arrived_at=monotonic(),
                    validate_before_wait=lambda: None, work=lambda request, control: payload,
                    receive=receive, send=send)
                assert sent[-1]["body"] == expected
                assert not rt.admission.active_leases
            finally:
                await rt.aclose()
        anyio.run(scenario)


def test_fixed_stock_definitions_checked_once_at_startup(monkeypatch):
    from types import SimpleNamespace
    from src.app.dependencies import stock_daily_technical_indicators as wiring
    from src.app.exceptions import WebAppError
    from src.biz.services.wealth.market.stock_detail.stock_daily_kline_contracts import StockDailyKlineRequest
    from goldenshare_technical_indicators.calculation.calculation import CalculationDefinition
    from goldenshare_technical_indicators.calculation.indicators import create_builtin_registry
    from goldenshare_technical_indicators.errors import CalculationUnsupportedError
    from goldenshare_technical_indicators.service import TechnicalIndicatorService

    registry = create_builtin_registry()
    rt = SimpleNamespace(registry=registry, source=object(), config=make_config())
    resolved, validated = [], []
    resolve = registry.resolve
    validate = CalculationDefinition.validate_parameters

    def resolve_once(calculation_id):
        resolved.append(calculation_id)
        return resolve(calculation_id)

    def validate_once(definition, parameters):
        if definition.public:
            validated.append(definition.calculation_id)
        return validate(definition, parameters)

    monkeypatch.setattr(registry, "resolve", resolve_once)
    monkeypatch.setattr(CalculationDefinition, "validate_parameters", validate_once)
    backend = wiring.StockDailyKlineAppBackend(rt, settings=Settings(_env_file=None, APP_ENV="prod"))
    expected = ["ma"] * 7 + ["boll", "macd", "kdj"]
    assert resolved == expected and validated == []
    request = StockDailyKlineRequest("600000.SH", "day", "forward", None, None, None, 500, False)
    assert backend.validate_before_wait(request) is request
    assert backend.validate_before_wait(replace(request, limit=250)).limit == 250
    with pytest.raises(WebAppError) as caught:
        backend.validate_before_wait(replace(request, limit=0))
    assert caught.value.code == "400001"
    assert resolved == expected and validated == []

    service = TechnicalIndicatorService(source=rt.source, registry=registry, config=rt.config)
    prepared = service._prepare_calculation(CalculationRequest(
        "stock", "600000.SH", "day", STOCK_DAILY_CALCULATIONS,
    ))
    assert len(prepared.instances) == 10
    assert validated == expected

    # Deliberately inconsistent definitions exercise the existing startup contract.
    for changed in (replace(resolve("ma"), algorithm_version="unexpected"),
                    replace(resolve("ma"), supported_periods=("week",))):
        bad_registry = SimpleNamespace(resolve=lambda calculation_id: changed)
        with pytest.raises(CalculationUnsupportedError, match="definition changed"):
            wiring.StockDailyKlineAppBackend(
                SimpleNamespace(registry=bad_registry), settings=Settings(_env_file=None, APP_ENV="prod"),
            )


def test_database_session_ownership_and_timeout(monkeypatch, record_property):
    from types import SimpleNamespace
    from sqlalchemy.exc import SQLAlchemyError
    from src.app.dependencies import stock_daily_technical_indicators as wiring
    from goldenshare_technical_indicators.errors import ResourceCleanupError, SourceReadError, SourceUnsupportedError
    from tests.stock_daily_kline_helpers import controlled_controls

    with controlled_controls(monkeypatch, record_property) as (create, _):
        # Four initialization positions and the directly specified failure exits.
        for mode in ("normal", "factory", "bind_close", "connection", "listener",
                     "remove", "close", "primary_close", "unsupported"):
            now = [100.0]
            control = create(config=make_config(), arrived_at=100,
                             clock=lambda: now[0])
            owner = threading.get_ident()
            events, registered, timeouts = [], [], []
            primary = ValueError("Controlled business error")

            def note(name):
                assert threading.get_ident() == owner
                events.append(name)

            class Connection:
                closed = False
                def invalidate(self):
                    note("invalidate_connection")
                def close(self):
                    note("close_connection")
                    self.closed = True

            connection = Connection()

            class Session:
                def get_bind(self):
                    note("bind")
                    if mode == "bind_close":
                        raise SQLAlchemyError("Controlled bind failure")
                    return SimpleNamespace(dialect=SimpleNamespace(
                        name="sqlite" if mode == "unsupported" else "postgresql", driver="psycopg"))
                def connection(self, *, execution_options):
                    note("connection")
                    assert execution_options == {"postgresql_readonly": True}
                    if mode == "connection":
                        raise SQLAlchemyError("Controlled connection failure")
                    return connection
                def close(self):
                    note("close_session")
                    if mode in ("bind_close", "close", "primary_close"):
                        raise SQLAlchemyError("Controlled close failure")
                def invalidate(self):
                    note("invalidate_session")

            def factory():
                note("session")
                if mode == "factory":
                    raise SQLAlchemyError("Controlled factory failure")
                return Session()

            def listen(conn, name, callback):
                note("listen")
                assert conn is connection and name == "before_cursor_execute"
                registered.append(callback)
                if mode == "listener":
                    raise SQLAlchemyError("Controlled partial listen failure")

            def remove(conn, name, callback):
                note("remove")
                if mode == "remove":
                    raise RuntimeError("Controlled listener removal failure")
                registered.remove(callback)

            monkeypatch.setattr(wiring.event, "listen", listen)
            monkeypatch.setattr(wiring.event, "contains", lambda conn, name, cb: cb in registered)
            monkeypatch.setattr(wiring.event, "remove", remove)

            class Cursor:
                def execute(self, statement, parameters):
                    note("timeout")
                    assert statement == "SELECT set_config('statement_timeout', %s, true)"
                    timeouts.append(int(parameters[0]))

            try:
                with wiring.open_stock_daily_read_session(factory, control):
                    note("query")
                    callback = registered[0]
                    callback(connection, Cursor(), "SELECT 1", (), None, False)
                    now[0] += 0.01
                    callback(connection, Cursor(), "SELECT 1", (), None, False)
                    if mode == "primary_close":
                        raise primary
            except BaseException as error:
                if mode == "primary_close":
                    assert error is primary and error.__notes__
                elif mode in ("remove", "close"):
                    assert isinstance(error, ResourceCleanupError)
                elif mode == "unsupported":
                    assert isinstance(error, SourceUnsupportedError)
                else:
                    assert mode in ("factory", "bind_close", "connection", "listener")
                    assert isinstance(error, SourceReadError) and isinstance(error.__cause__, SQLAlchemyError)
            else:
                assert mode == "normal" and 0 < timeouts[1] < timeouts[0] == 6000
            assert events.count("close_session") == (0 if mode == "factory" else 1)
            if mode == "bind_close":
                assert "invalidate_session" in events
            if mode in ("listener", "remove", "normal", "close", "primary_close"):
                assert "remove" in events
            if mode in ("remove", "close", "primary_close"):
                assert "invalidate_connection" in events
            if mode in ("close", "primary_close"):
                assert "close_connection" in events


def test_lifespan_and_other_paths(monkeypatch, record_property):
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    from fastapi import FastAPI
    from starlette.middleware.base import BaseHTTPMiddleware
    from src.app.dependencies import stock_daily_technical_indicators as wiring
    from src.app.web.middleware.access_log import AccessLogMiddleware
    from src.app.web.middleware.request_id import RequestIdMiddleware
    from src.app.web.middleware.stock_daily_kline import is_stock_daily_kline

    # No top-level construction of runtime, connection, query, or data source.
    tree = ast.parse(Path(wiring.__file__).read_text())
    assert not any(isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call)
                   for node in tree.body)

    async def scenario():
        app = FastAPI()
        app.dependency_overrides[object()] = "preserved"
        counts = {"runtime": 0, "close": 0}
        mode = "normal"
        class Runtime:
            def __init__(self):
                from goldenshare_technical_indicators.calculation.indicators import create_builtin_registry
                self.registry = create_builtin_registry()

            async def aclose(self):
                counts["close"] += 1
                if mode in ("close", "body_close"):
                    raise RuntimeError("Controlled shutdown failure")
        def create(settings):
            assert asyncio.get_running_loop().is_running()
            counts["runtime"] += 1
            return Runtime()
        real_backend = wiring.StockDailyKlineAppBackend
        def backend(*args, **kwargs):
            if mode == "backend":
                raise ValueError("Controlled backend initialization failure")
            return real_backend(*args, **kwargs)
        monkeypatch.setattr(wiring, "create_runtime", create)
        monkeypatch.setattr(wiring, "StockDailyKlineAppBackend", backend)
        wiring.install_stock_daily_technical_indicators(app)
        assert counts == {"runtime": 0, "close": 0} and len(app.dependency_overrides) == 2
        for mode in ("normal", "backend", "close", "body_close"):
            primary = ValueError("Controlled lifespan body failure")
            try:
                async with wiring.stock_daily_technical_indicators_lifespan(
                    app, settings_provider=lambda: Settings(_env_file=None, APP_ENV="prod"),
                    session_factory_provider=lambda: object(),
                ):
                    assert app.state.technical_indicator_runtime is app.state.stock_daily_kline_backend.runtime
                    if mode == "body_close":
                        raise primary
            except BaseException as error:
                if mode == "body_close":
                    assert error is primary and error.__notes__
                else:
                    assert mode in ("backend", "close")
            else:
                assert mode == "normal"
            assert not hasattr(app.state, "technical_indicator_runtime")
            assert not hasattr(app.state, "stock_daily_kline_backend")
        assert counts == {"runtime": 4, "close": 4}

        forwarded = []
        async def base(self, scope, receive, send):
            forwarded.append((type(self).__name__, scope["path"], scope["method"]))
            await self.app(scope, receive, send)
        monkeypatch.setattr(BaseHTTPMiddleware, "__call__", base)
        async def inner(scope, receive, send):
            pass
        wrapped = AccessLogMiddleware(RequestIdMiddleware(inner))
        for scope in (_scope("OPTIONS"), _scope(path="/api/v1/wealth/market/stock-detail/page-init"),
                      _scope(path="/api/v1/wealth/market/index-detail/kline"),
                      _scope(path="/api/v1/wealth/market/stock-detail/minute-kline")):
            assert not is_stock_daily_kline(scope)
            await wrapped(scope, None, None)
        assert len(forwarded) == 8
        assert not is_stock_daily_kline({"type": "websocket"})
    anyio.run(scenario)
    record_property("stock_daily_step3_metrics", json.dumps({"fake_controls": 0, "real_controls": 0}))
