"""LLD §08/16.2: common execution only; no stock Web registration in A/B.

Real Admission, AnyIO worker, handoff, encoder and send; only Control and
calculate are replaced. The result is a contract literal, not algorithm evidence.
JUnit reports this function's costs; historical reports are never read/written.
"""

from dataclasses import replace
import inspect
import json
import threading
from time import monotonic
import weakref

import anyio
import pytest

from test_admission import FakeControl, light_case
from test_execution_cancellation import (
    inspect_release_locals, install_control, literal_result, runtime,
)
from src.app.runtime.technical_indicators import execution
from src.biz.services.wealth.market.stock_detail.stock_daily_kline_calculations import (
    STOCK_DAILY_CALCULATIONS,
)
from src.foundation.technical_indicators.contracts import (
    CalculationInstance, CalculationRequest, CalculationValues,
)
from src.foundation.technical_indicators.errors import OutputContractError, RequestInvalidError


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

            def calculate(service, normalized):
                metrics["calculate_stub_calls"] += 1
                assert threading.get_ident() != main_thread
                assert service.control is controls[-1]
                assert normalized == request and normalized is not request
                assert len(normalized.calculations) == 10
                calls.append(normalized)
                if mode == "wrong_library_type":
                    value = _Payload(result="unsupported library result")
                    weak_values.append(weakref.ref(value))
                    return value
                return reference

            monkeypatch.setattr(execution.TechnicalIndicatorService, "calculate", calculate)
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
