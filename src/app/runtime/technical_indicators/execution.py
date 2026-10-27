"""Isolated App entry points, with one lease spanning work and actual sending.

The Foundation library stays synchronous. Only the owning worker touches its
connection; the event-loop task observes cancellation and waits for real exit.
"""

import traceback

import anyio
from starlette.types import Receive, Send

from src.foundation.technical_indicators.contracts import (
    CalculationRequest, CalculationResult, normalize_request_and_validate_all_instances,
)
from src.foundation.technical_indicators.errors import (
    CalculationCancelledError, CalculationUnsupportedError,
)
from src.foundation.technical_indicators.execution_control import ExecutionControl
from src.foundation.technical_indicators.output.encoding import encode_response_utf8
from src.foundation.technical_indicators.service import TechnicalIndicatorService

from .composition import TechnicalIndicatorRuntime
from .response import send_encoded_body


def _validate_request_before_wait(
    runtime: TechnicalIndicatorRuntime, request: CalculationRequest,
) -> CalculationRequest:
    normalized = normalize_request_and_validate_all_instances(request, runtime.config)
    for item in normalized.calculations:
        definition = runtime.registry.resolve(item.calculation_id)
        if normalized.period not in definition.supported_periods:
            raise CalculationUnsupportedError("Calculation does not support the requested period")
        definition.validate_parameters(item.parameters)
    return normalized


def _clear_error_frames(error: BaseException) -> None:
    pending, seen = [error], set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
        if current.__traceback__ is not None:
            traceback.clear_frames(current.__traceback__)


async def _execute(
    runtime: TechnicalIndicatorRuntime, request: CalculationRequest, *, arrived_at: float,
    receive: Receive | None = None, send: Send | None = None,
) -> CalculationResult | None:
    cancelled_type = anyio.get_cancelled_exc_class()
    control = ExecutionControl(arrived_at=arrived_at, config=runtime.config)
    control.check_active()
    normalized = _validate_request_before_wait(runtime, request)
    handoff = {"result": None, "body": None, "error": None}
    done = anyio.Event()
    lease = primary_error = return_result = result = body = None
    request_finished = False

    def remember(error):
        nonlocal primary_error
        if primary_error is None:
            published = handoff["error"]
            if isinstance(error, cancelled_type) and isinstance(
                published, (CalculationCancelledError, cancelled_type)
            ):
                # A faster stop response must not replace the main task's
                # original cancellation; already-published real faults remain.
                primary_error = error
            else:
                primary_error = published if published is not None else error

    def worker():
        result = body = None
        try:
            control.check_active()
            result = TechnicalIndicatorService(
                source=runtime.source, registry=runtime.registry,
                config=runtime.config, control=control,
            ).calculate(normalized)
            control.check_active()
            if send is None:
                handoff["result"] = result
            else:
                body = encode_response_utf8(
                    result, control=control, max_bytes=runtime.config.max_output_bytes,
                )
                control.check_active()
                handoff["body"] = body
        except BaseException as error:
            handoff["error"] = error
        finally:
            result = body = None
        # No result or exception travels as a task return value.

    async def run_worker():
        try:
            await anyio.to_thread.run_sync(worker, abandon_on_cancel=False)
        except BaseException as error:
            if handoff["error"] is None:
                handoff["error"] = error
        finally:
            done.set()

    try:
        async with anyio.create_task_group() as group:
            async def observe_disconnect():
                try:
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            control.request_stop("cancel")
                            group.cancel_scope.cancel()
                            return
                except anyio.get_cancelled_exc_class():
                    raise
                except BaseException as error:
                    remember(error)
                    control.request_stop("cancel")
                    group.cancel_scope.cancel()
                finally:
                    if not request_finished:
                        control.request_stop("cancel")

            try:
                if receive is not None:
                    group.start_soon(observe_disconnect)
                # The worker may still be waiting for the framework's thread
                # limiter, before the SQL interrupt monitor exists. Wake the
                # main task at the same absolute work deadline in that case.
                remaining = max(0.0, control.work_until - control.clock())
                with anyio.CancelScope(deadline=anyio.current_time() + remaining) as working:
                    lease = await runtime.admission.acquire(control)
                    control.check_active()
                    group.start_soon(run_worker)
                    await done.wait()
                if working.cancel_called:
                    control.request_stop("deadline")
                    control.check_active()
                if handoff["error"] is not None:
                    remember(handoff["error"])
                else:
                    control.check_active()
                    if send is None:
                        return_result = handoff["result"]
                        handoff["result"] = None
                    else:
                        body = handoff["body"]
                        handoff["body"] = None
                        await send_encoded_body(body, send=send, control=control)
                        body = None
                    request_finished = True
            except BaseException as error:
                remember(error)
                control.request_stop("cancel")
            finally:
                group.cancel_scope.cancel()
    except BaseException as error:
        remember(error)
        control.request_stop("cancel")
    finally:
        # Leaving the task group has awaited the worker and receive observer.
        # Cancellation cannot skip finalization or release a live request.
        with anyio.CancelScope(shield=True):
            result = body = None
            handoff["result"] = handoff["body"] = handoff["error"] = None
            if primary_error is None and not request_finished:
                try:
                    control.check_active()
                except BaseException as error:
                    primary_error = error
            if primary_error is not None:
                return_result = None
                _clear_error_frames(primary_error)
            if lease is not None:
                try:
                    runtime.admission.release(lease)
                except BaseException as error:
                    return_result = None
                    if primary_error is None:
                        primary_error = error
                    else:
                        primary_error.add_note(f"Admission release: {type(error).__name__}: {error}")
                    _clear_error_frames(primary_error)
    if primary_error is not None:
        raise primary_error
    return return_result


async def execute_library(
    runtime: TechnicalIndicatorRuntime, request: CalculationRequest, *, arrived_at: float,
) -> CalculationResult:
    return await _execute(runtime, request, arrived_at=arrived_at)


async def execute_http(
    runtime: TechnicalIndicatorRuntime, request: CalculationRequest, *, arrived_at: float,
    receive: Receive, send: Send,
) -> None:
    await _execute(runtime, request, arrived_at=arrived_at, receive=receive, send=send)
