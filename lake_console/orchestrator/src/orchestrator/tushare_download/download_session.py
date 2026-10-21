"""One calling-thread session, explicit cancellation and owned-resource finalization."""

from __future__ import annotations

import inspect
from dataclasses import fields, replace
from uuid import uuid4

from .contract_registry import validate_contract
from .download_errors import DownloadCancelled, DownloadError, ErrorDetails, require
from .download_errors import DownloadErrorCode as Code
from .download_models import (
    CleanupIssue,
    DownloadControl,
    DownloadScope,
    DownloadStage,
    DownloadSummary,
    DownloadTask,
    ProgressFacts,
    SessionCounters,
)
from .download_models import DownloadProgressEvent as Event
from .download_models import DownloadStatus as Status
from .download_progress import ProgressReporter, validate_callback
from .page_download import PageDownloader
from .task_input import validate_task
from .unit_memory import UnitMemory
from .unit_output import UnitOutput
from .unit_planner import UnitPlanner


class SessionControl:
    def __init__(self, check, task_id):
        self.requested = False
        self._check = check
        self._location = ErrorDetails(stage=DownloadStage.PREPARE, task_id=task_id)

    def raise_if_cancelled(self):
        if self.requested:
            raise DownloadCancelled(details=self.error_location())
        if self._check is not None:
            value = self._check()
            if type(value) is not bool:
                if (
                    inspect.iscoroutine(value)
                    and inspect.getcoroutinestate(value) == inspect.CORO_CREATED
                ):
                    value.close()
                raise DownloadError(Code.INPUT, details=self.error_location())
            if value:
                self.requested = True
                raise DownloadCancelled(details=self.error_location())

    def set_location(self, stage, unit_id, position, attempt_number):
        self._location = replace(
            self._location,
            stage=stage,
            unit_id=unit_id,
            source_position=position,
            attempt_number=attempt_number,
        )

    def set_unit(self, unit):
        self._location = replace(
            self._location,
            unit_id=unit.unit_id,
            current_scope=DownloadScope(unit.object_code, unit.point, unit.time_range),
        )

    def set_contract(self, contract):
        self._location = replace(
            self._location,
            contract_name=contract.contract_name,
            contract_version=contract.version,
        )

    def error_location(self):
        return replace(self._location)

    def clear(self):
        self._check = None


class DownloadSession:
    def __init__(self, owner, task, control, on_progress):
        self._owner = owner
        self._task, self._raw_control, self._raw_callback = task, control, on_progress
        self.task_id = str(uuid4())
        self._status, self._closed, self._in_next = Status.CREATED, False, False
        self._started_at, self._ended_at = owner._clock.monotonic(), None
        self._counters = SessionCounters()
        check = control.is_cancelled if isinstance(control, DownloadControl) else None
        self._control = SessionControl(check, self.task_id)
        self._input = self._contract = self._binding = self._planner = (
            self._transport
        ) = None
        self._progress = self._pages = self._output = self._memory = (
            self._current_unit
        ) = None
        self._total_units = self._summary = self._failure = None
        self._cleanup_errors = ()

    @property
    def download_complete(self):
        return (
            self._total_units is not None
            and self._counters.delivered_units == self._total_units
        )

    def _snapshot(self):
        c = self._counters
        elapsed = (
            self._ended_at
            if self._ended_at is not None
            else self._owner._clock.monotonic()
        ) - self._started_at
        return DownloadSummary(
            self.task_id,
            self._status,
            self._total_units,
            c.completed_units,
            c.delivered_units,
            c.completed_row_count,
            c.row_count,
            c.request_count,
            c.retry_count,
            c.successful_response_count,
            self.download_complete,
            elapsed,
            self._failure,
            self._cleanup_errors,
            c.progress_error_count,
            c.last_progress_error_type,
            c.callback_elapsed_seconds,
        )

    @property
    def summary(self):
        return self._summary if self._closed else self._snapshot()

    def _guard_not_running(self):
        require(
            not self._in_next
            and not (self._progress is not None and self._progress.in_callback),
            Code.INPUT,
        )

    def __enter__(self):
        self._guard_not_running()
        require(self._status == Status.CREATED and not self._closed, Code.INPUT)
        try:
            require(self._owner._active_session is None, Code.INPUT)
            self._owner._active_session = self
            require(isinstance(self._task, DownloadTask), Code.INPUT)
            require(
                self._raw_control is None
                or isinstance(self._raw_control, DownloadControl),
                Code.INPUT,
            )
            validate_callback(self._control._check, 0)
            validate_callback(self._raw_callback, 1)
            self._contract = self._owner._registry.resolve(self._task.contract_name)
            validate_contract(self._contract)
            self._control.set_contract(self._contract)
            self._binding = self._owner._bindings.resolve(self._contract)
            self._input = validate_task(
                self._task, self._contract, self._owner._config.max_request_bytes
            )
            self._planner = UnitPlanner(self._input, self._contract)
            self._total_units = self._planner.total_units
            self._transport = self._owner._transport_factory(
                self._binding, self._owner._clock
            )
            self._transport.prepare(self._binding, self._owner._config, self._contract)
            self._memory = UnitMemory(self._owner._config)
            control = self._control
            self._progress = ProgressReporter(
                self._raw_callback,
                self._counters,
                self._owner._clock,
                task_id=self.task_id,
                contract_name=self._contract.contract_name,
                total_units=self._total_units,
                started_at=self._started_at,
                cancel_requested=lambda: control.requested,
            )
            self._pages = PageDownloader(
                self._owner._config,
                self._transport,
                self._memory,
                self._counters,
                self._owner._clock,
                self._owner._sleep_fn,
            )
            self._output = UnitOutput(self._owner._config, self._owner._clock)
            self._task = self._raw_control = self._raw_callback = None
            self._status = Status.READY
            return self
        except BaseException as error:
            self._finalize(primary=error)
            raise

    def __iter__(self):
        require(self._status != Status.CREATED or self._closed, Code.INPUT)
        return self

    def _require_next_allowed(self):
        self._guard_not_running()
        if self._closed:
            raise StopIteration
        require(self._status == Status.READY, Code.INPUT)

    def __next__(self):
        self._require_next_allowed()
        self._in_next = True
        self._status = Status.RUNNING
        buffer = result = None
        try:
            if self.download_complete:
                unit = None
            else:
                self._control.raise_if_cancelled()
                unit = self._planner.next_unit()
                if unit is None:
                    raise RuntimeError(
                        "download planner ended before its declared total"
                    )
            if unit is not None:
                self._current_unit = unit
                self._control.set_unit(unit)
                self._control.set_location(
                    DownloadStage.SOURCE, unit.unit_id, None, None
                )
                buffer = self._pages.download_unit(
                    unit, self._contract, self._control, self._progress
                )
                self._control.set_location(
                    DownloadStage.ORDERING, unit.unit_id, None, None
                )
                result = self._output.finish_unit(
                    buffer, self._contract, self._memory, self._control
                )
                self._control.set_location(
                    DownloadStage.UNIT_READY, unit.unit_id, None, None
                )
                self._control.raise_if_cancelled()
                self._counters.completed_units += 1
                self._counters.completed_row_count += result.statistics.row_count
                try:
                    self._progress.publish(
                        Event.UNIT_COMPLETED,
                        ProgressFacts(unit, result.statistics.row_count),
                    )
                except DownloadCancelled:
                    self.cancel()
                buffer.clear()
                self._memory.clear()
                self._current_unit = None
                self._status = Status.READY
                self._counters.delivered_units += 1
                self._counters.row_count += result.statistics.row_count
                return result
        except StopIteration as error:
            failure = RuntimeError("download step unexpectedly raised StopIteration")
            self._finalize(primary=failure)
            raise failure from error
        except MemoryError:
            failure = DownloadError(
                Code.CAPACITY, details=self._control.error_location()
            )
            self._finalize(primary=failure)
            raise failure from None
        except BaseException as error:
            self._finalize(primary=error)
            raise
        finally:
            buffer = result = None
            self._in_next = False
        self._finalize(normal_exit=True)
        raise StopIteration

    def cancel(self):
        if not self._closed:
            self._control.requested = True

    def poll_progress(self):
        return self._progress.latest if self._progress is not None else None

    def close(self):
        self._guard_not_running()
        self._finalize(normal_exit=True)

    def __exit__(self, exc_type, exc, traceback):
        self._guard_not_running()
        if not self._closed:
            self._finalize(primary=exc, normal_exit=exc is None)
        return False

    def _error_details(self, primary):
        if primary is None:
            return None
        location = self._control.error_location()
        if isinstance(primary, DownloadError):
            changes = {
                f.name: getattr(primary.details, f.name)
                for f in fields(ErrorDetails)
                if getattr(primary.details, f.name) is not None
            }
            return replace(location, **changes)
        return replace(location, cause_type=type(primary).__name__)

    def _finalize(self, *, primary=None, normal_exit=False):
        if self._closed:
            return
        details = self._error_details(primary)
        cleanup = list(details.cleanup_errors if details is not None else ())
        if self._transport is not None:
            cleanup.extend(getattr(self._transport, "last_cleanup_errors", ()))
        interrupt = None
        self._control.set_location(
            DownloadStage.CLOSE, self._control.error_location().unit_id, None, None
        )
        for owner, resource, method in (
            ("source_transport", self._transport, "close"),
            ("unit_planner", self._planner, "close"),
            ("unit_memory", self._memory, "clear"),
            ("progress_reporter", self._progress, "release"),
        ):
            if resource is None:
                continue
            try:
                getattr(resource, method)()
            except BaseException as error:  # noqa: BLE001 - finish all closing attempts, then preserve original interruption.
                if isinstance(error, DownloadError) and error.cleanup_errors:
                    cleanup.extend(error.cleanup_errors)
                else:
                    cleanup.append(CleanupIssue(owner, type(error).__name__))
                if (
                    not isinstance(error, Exception)
                    and primary is None
                    and interrupt is None
                ):
                    interrupt = error
        self._cleanup_errors = tuple(dict.fromkeys(cleanup))[:8]
        self._control.clear()
        self._task = self._raw_control = self._raw_callback = self._input = (
            self._current_unit
        ) = None
        self._planner = self._transport = self._pages = self._memory = self._output = (
            None
        )
        if self._owner._active_session is self:
            self._owner._active_session = None
        if primary is not None:
            self._status = (
                Status.CANCELLED
                if isinstance(primary, DownloadCancelled)
                else Status.FAILED
            )
        elif interrupt is not None or self._cleanup_errors:
            self._status = Status.FAILED
        elif self.download_complete:
            self._status = Status.SUCCEEDED
        elif self._control.requested:
            self._status = Status.CANCELLED
        else:
            self._status = Status.STOPPED
        self._failure = (
            replace(details, cleanup_errors=self._cleanup_errors)
            if details is not None
            else None
        )
        if primary is None and self._cleanup_errors:
            self._failure = replace(
                self._control.error_location(),
                code=Code.CLEANUP,
                cleanup_errors=self._cleanup_errors,
            )
        self._ended_at, self._closed = self._owner._clock.monotonic(), True
        self._summary = self._snapshot()
        if primary is None:
            if interrupt is not None:
                raise interrupt
            if self._cleanup_errors:
                raise DownloadError(Code.CLEANUP, details=self._failure)
