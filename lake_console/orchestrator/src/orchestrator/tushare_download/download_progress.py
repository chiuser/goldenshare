"""Three synchronous summary notifications; observers cannot trigger source retries."""

from __future__ import annotations

import inspect
import json
import math
from dataclasses import asdict

from .download_errors import DownloadCancelled, DownloadErrorCode, require
from .download_models import DownloadProgress, DownloadScope, DownloadStage
from .download_models import DownloadProgressEvent as Event


def validate_callback(callback, arity):
    if callback is None:
        return
    require(callable(callback), DownloadErrorCode.INPUT)
    target = getattr(callback, "__call__", None)  # noqa: B004 - inspect async __call__, after callable validation.
    require(
        not any(
            test(x)
            for x in (callback, target)
            for test in (inspect.iscoroutinefunction, inspect.isasyncgenfunction)
        ),
        DownloadErrorCode.INPUT,
    )
    signature = None
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        pass
    valid = True
    if signature is not None:
        try:
            signature.bind(*([None] * arity))
        except TypeError:
            valid = False
    require(valid, DownloadErrorCode.INPUT)


class ProgressReporter:
    def __init__(
        self,
        callback,
        counters,
        clock,
        *,
        task_id,
        contract_name,
        total_units,
        started_at,
        cancel_requested,
    ):
        self.on_progress, self.counters, self.clock = callback, counters, clock
        self.task_id, self.contract_name, self.total_units = (
            task_id,
            contract_name,
            total_units,
        )
        self.started_at, self._cancel_requested = started_at, cancel_requested
        self.sequence, self.latest, self.in_callback = 0, None, False

    def record_observation_error(self, name):
        try:
            self.counters.progress_error_count += 1
            self.counters.last_progress_error_type = name[:128]
        except Exception:  # noqa: BLE001 - observation recording itself must never affect data.
            return

    def _freeze(self, event, facts):
        require(isinstance(event, Event))
        page = event == Event.PAGE_COMPLETED
        retry = event == Event.RETRY_SCHEDULED
        if page:
            require(
                all(
                    x is None
                    for x in (
                        facts.next_attempt_number,
                        facts.retry_delay_seconds,
                        facts.error_code,
                    )
                )
            )
            require(
                facts.position is not None
                and type(facts.attempt_number) is int
                and 1 <= facts.attempt_number <= 4
            )
            require(
                type(facts.page_row_count) is int
                and facts.page_row_count >= 0
                and type(facts.page_accepted) is bool
            )
        elif retry:
            require(facts.page_row_count is None and facts.page_accepted is None)
            require(
                facts.position is not None
                and type(facts.attempt_number) is int
                and 1 <= facts.attempt_number <= 3
            )
            require(facts.next_attempt_number == facts.attempt_number + 1)
            require(
                type(facts.retry_delay_seconds) in (float, int)
                and math.isfinite(facts.retry_delay_seconds)
                and facts.retry_delay_seconds >= 0
            )
            require(
                facts.error_code
                in (
                    DownloadErrorCode.RATE_LIMIT,
                    DownloadErrorCode.TRANSIENT_SOURCE,
                    DownloadErrorCode.NO_VALID_RESPONSE,
                )
            )
        else:
            require(
                all(
                    x is None
                    for x in (
                        facts.position,
                        facts.attempt_number,
                        facts.page_row_count,
                        facts.page_accepted,
                        facts.next_attempt_number,
                        facts.retry_delay_seconds,
                        facts.error_code,
                    )
                )
            )
        require(type(facts.unit_row_count) is int and facts.unit_row_count >= 0)
        stage = (
            DownloadStage.SOURCE
            if page
            else DownloadStage.BACKOFF
            if retry
            else DownloadStage.UNIT_READY
        )
        unit, c = facts.unit, self.counters
        scope = DownloadScope(
            unit.object_code,
            unit.point,
            unit.time_range,
            facts.position.request_input_index if facts.position is not None else None,
        )
        result = DownloadProgress(
            1,
            event,
            self.sequence + 1,
            self.task_id,
            self.contract_name,
            unit.unit_id,
            unit.ordinal,
            stage,
            scope,
            facts.position if page or retry else None,
            self.total_units,
            c.completed_units,
            c.delivered_units,
            100 * c.completed_units / self.total_units if self.total_units else None,
            facts.unit_row_count,
            c.completed_row_count,
            facts.page_row_count if page else None,
            facts.page_accepted if page else None,
            c.request_count,
            c.retry_count,
            facts.attempt_number if page or retry else None,
            facts.next_attempt_number if retry else None,
            facts.retry_delay_seconds if retry else None,
            facts.error_code if retry else None,
            self.clock.monotonic() - self.started_at,
            self.clock.utc_now().isoformat(),
            self._cancel_requested(),
        )
        encoded = json.dumps(
            asdict(result), ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        require(len(encoded) <= 4096)
        return result

    def publish(self, event, facts):
        try:
            candidate = self._freeze(event, facts)
        except Exception as error:  # noqa: BLE001 - snapshot failure is observation-only by contract.
            self.record_observation_error(type(error).__name__)
            return
        self.sequence, self.latest = candidate.sequence, candidate
        if self.on_progress is None:
            return
        started, self.in_callback = self.clock.monotonic(), True
        returned = None
        try:
            returned = self.on_progress(candidate)
            if inspect.isawaitable(returned):
                if (
                    inspect.iscoroutine(returned)
                    and inspect.getcoroutinestate(returned) == inspect.CORO_CREATED
                ):
                    returned.close()
                self.record_observation_error("TypeError")
        except DownloadCancelled:
            raise
        except Exception as error:  # noqa: BLE001 - observer failure must not retry source or lose data.
            self.record_observation_error(type(error).__name__)
        finally:
            self.counters.callback_elapsed_seconds += self.clock.monotonic() - started
            self.in_callback = False
            returned = None

    def release(self):
        self.on_progress = self._cancel_requested = None
