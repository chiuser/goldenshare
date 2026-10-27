"""D4's original response class, using a result literal and no calculation.

LLD12.4b/14.3 require one body, a single receive observer, actual sending
exit before release, and preserved errors without retained result references.
Real source/SQL/HTTP resource requests belong only to the diagnostic ledger.
"""

import json
import threading
from time import monotonic

import anyio
import pytest

from test_admission import light_case
from test_execution_cancellation import (
    assert_ended_frames_empty, inspect_release_locals, install_control,
    literal_result, request, runtime,
)
from src.app.runtime.technical_indicators import execution
from src.foundation.technical_indicators.errors import CalculationDeadlineError, OutputEncodingError


def test_response_lifecycle(monkeypatch):
    with light_case("test_response_lifecycle"):
        async def scenario():
            # These three calls cover normal sending, crossing the working
            # deadline after response start, and the response's own deadline.
            for mode in ("normal", "cross_work_deadline", "response_deadline"):
                rt = runtime()
                disconnect, never = anyio.Event(), anyio.Event()
                messages, releases = [], []
                sending_exited = False

                def on_create(control):
                    if mode == "response_deadline":
                        control.target_finish = monotonic() + 0.2

                created = install_control(monkeypatch, on_create=on_create)
                monkeypatch.setattr(execution.TechnicalIndicatorService, "calculate",
                                    lambda service, normalized: literal_result())
                original_release = rt.admission.release

                def release(lease):
                    assert sending_exited and len(rt.admission.active_leases) == 1
                    inspect_release_locals(failure=mode == "response_deadline")
                    releases.append(lease)
                    original_release(lease)

                monkeypatch.setattr(rt.admission, "release", release)

                async def receive():
                    await disconnect.wait()
                    return {"type": "http.disconnect"}

                async def send(message):
                    nonlocal sending_exited
                    assert len(rt.admission.active_leases) == 1
                    if message["type"] == "http.response.start":
                        assert not messages and message["status"] == 200
                        if mode == "cross_work_deadline":
                            # No sleep: the controlled working clock advances
                            # only after sending has already started.
                            created[0].work_until = created[0].clock() - 1
                    try:
                        if mode == "response_deadline":
                            await never.wait()
                        messages.append(message)
                    finally:
                        if mode == "response_deadline" or message["type"] == "http.response.body":
                            sending_exited = True

                try:
                    if mode == "response_deadline":
                        with pytest.raises(CalculationDeadlineError):
                            await execution.execute_http(rt, request(), arrived_at=monotonic(),
                                                         receive=receive, send=send)
                        assert messages == []
                    else:
                        returned = await execution.execute_http(rt, request(), arrived_at=monotonic(),
                                                                receive=receive, send=send)
                        assert returned is None and len(messages) == 2
                        assert [item["type"] for item in messages] == ["http.response.start", "http.response.body"]
                        assert messages[1]["more_body"] is False
                        payload = json.loads(messages[1]["body"])
                        assert payload["times"] == ["2026-01-02"]
                        assert payload["calculations"][0]["fields"] == {"value": [None]}
                        assert created[0].stop_reason is None
                    assert len(releases) == 1 and not rt.admission.active_leases
                finally:
                    await rt.aclose()

            # A disconnect is sent while the controlled worker still owns the
            # result request. Stop must be visible before releasing that worker.
            rt = runtime()
            started, disconnect, stopped, done = (anyio.Event() for _ in range(4))
            release_worker = threading.Event()
            outcome, messages, order = {}, [], []

            def on_stop(control):
                order.append("stop")
                stopped.set()

            created = install_control(monkeypatch, on_stop=on_stop)

            def controlled_calculate(service, normalized):
                anyio.from_thread.run_sync(started.set)
                try:
                    assert release_worker.wait(1), "Test did not release its controlled HTTP worker"
                    service.control.check_active()
                    return literal_result()
                finally:
                    order.append("worker_exit")

            monkeypatch.setattr(execution.TechnicalIndicatorService, "calculate", controlled_calculate)
            original_release = rt.admission.release

            def release(lease):
                assert "worker_exit" in order
                inspect_release_locals(failure=True)
                order.append("release")
                original_release(lease)

            monkeypatch.setattr(rt.admission, "release", release)

            async def receive():
                await disconnect.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                messages.append(message)

            async def call():
                try:
                    await execution.execute_http(rt, request(), arrived_at=monotonic(), receive=receive, send=send)
                except BaseException as error:
                    outcome["error"] = error
                finally:
                    done.set()

            try:
                with anyio.fail_after(2):
                    async with anyio.create_task_group() as group:
                        group.start_soon(call)
                        await started.wait()
                        disconnect.set()
                        await stopped.wait()
                        assert len(rt.admission.active_leases) == 1 and "worker_exit" not in order
                        release_worker.set()
                        await done.wait()
                assert isinstance(outcome["error"], anyio.get_cancelled_exc_class())
                assert messages == [] and not rt.admission.active_leases
                assert created[0].stop_reason == "cancel"
                assert order.index("stop") < order.index("worker_exit") < order.index("release")
            finally:
                release_worker.set()
                await rt.aclose()

            # Preserve the original encoding error/cause and its failure line,
            # while finished worker/encoder frames no longer retain the literal.
            rt = runtime()
            created = install_control(monkeypatch)
            original_error = OutputEncodingError("Deliberate controlled encoding failure")
            cause = TypeError("Deliberate unsupported encoding input")
            original_error.add_note("controlled fixture note")
            sent, released = [], []
            monkeypatch.setattr(execution.TechnicalIndicatorService, "calculate",
                                lambda service, normalized: literal_result())

            def failing_encoder(payload, *, control, max_bytes):
                result = payload
                body = bytearray(b"partial")
                try:
                    raise cause
                except TypeError:
                    raise original_error from cause

            monkeypatch.setattr(execution, "encode_response_utf8", failing_encoder)
            original_release = rt.admission.release

            def release(lease):
                inspect_release_locals(failure=True)
                assert_ended_frames_empty(original_error, "failing_encoder")
                released.append(lease)
                original_release(lease)

            monkeypatch.setattr(rt.admission, "release", release)
            never = anyio.Event()

            async def receive():
                await never.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                sent.append(message)

            try:
                with pytest.raises(OutputEncodingError) as caught:
                    await execution.execute_http(rt, request(), arrived_at=monotonic(), receive=receive, send=send)
                assert caught.value is original_error and caught.value.__cause__ is cause
                assert "controlled fixture note" in caught.value.__notes__
                assert_ended_frames_empty(caught.value, "failing_encoder")
                assert not sent and len(released) == 1 and not rt.admission.active_leases
                assert created[0].stop_reason == "cancel"
            finally:
                await rt.aclose()

        anyio.run(scenario)
