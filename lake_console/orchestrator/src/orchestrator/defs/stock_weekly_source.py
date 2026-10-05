"""One-code annual weekly capture through a terminable SDK subprocess."""

from __future__ import annotations

import json
import multiprocessing
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

import pandas as pd
from requests import exceptions as request_errors

from orchestrator.defs.bootstrap.stock_weekly_capture import (
    CancelProbe,
    WeeklyCaptureError,
    WeeklyCaptureStore,
    check_weekly_cancel,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    ALTERNATE_WEEKLY_FIELDS,
    StockWeeklySource,
    WeeklyBudget,
    WeeklySourceUnit,
    normalize_week_key,
    normalize_weekly_code,
    stable_weekly_hash,
)

_SOURCE_DIAGNOSTIC_PREFIX = "source_diagnostic="
_SOURCE_DIAGNOSTICS = frozenset(
    {
        "network_proxy",
        "network_tls",
        "network_timeout",
        "network_connection",
        "network_request",
        "response_decode",
        "response_schema",
        "unit_row_budget",
        "worker_dependency",
        "worker_type",
        "worker_value",
        "unknown",
        "supervisor_timeout",
        "worker_eof",
        "worker_exit",
        "worker_not_terminated",
    }
)


def _source_exception_category(error: Exception) -> str:
    # Classify by known types only: SDK messages and arbitrary class names are secret.
    for error_type, category in (
        (request_errors.ProxyError, "network_proxy"),
        (request_errors.SSLError, "network_tls"),
        (request_errors.Timeout, "network_timeout"),
        (request_errors.ConnectionError, "network_connection"),
        ((json.JSONDecodeError, request_errors.JSONDecodeError), "response_decode"),
        (request_errors.RequestException, "network_request"),
        (ImportError, "worker_dependency"),
        (TypeError, "worker_type"),
        (ValueError, "worker_value"),
    ):
        if isinstance(error, error_type):
            return category
    # The worker loads resources itself. Diagnostics must not repeat a failed import.
    response_error = getattr(
        sys.modules.get("orchestrator.defs.resources"), "TushareResponseError", ()
    )
    if isinstance(error, response_error):
        return "response_schema"
    return "unknown"


def _source_error(reason: str, category: str) -> WeeklyCaptureError:
    error = WeeklyCaptureError(reason)
    safe_category = category if category in _SOURCE_DIAGNOSTICS else "unknown"
    error.add_note(_SOURCE_DIAGNOSTIC_PREFIX + safe_category)
    return error


def copy_source_diagnostic(source: Exception | None, target: Exception) -> Exception:
    """Copy only our fixed diagnostic; never copy arbitrary source exception notes."""
    for note in getattr(source, "__notes__", ()):
        if isinstance(note, str) and note.startswith(_SOURCE_DIAGNOSTIC_PREFIX):
            category = note[len(_SOURCE_DIAGNOSTIC_PREFIX) :]
            if category in _SOURCE_DIAGNOSTICS:
                target.add_note(_SOURCE_DIAGNOSTIC_PREFIX + category)
                break
    return target


class WeeklySourceWorker(Protocol):
    def __call__(
        self, params: dict, fields: tuple[str, ...], max_rows: int
    ) -> pd.DataFrame: ...


@dataclass(frozen=True)
class WeeklySdkWorker:
    token: str = field(repr=False)

    def __call__(
        self, params: dict, fields: tuple[str, ...], max_rows: int
    ) -> pd.DataFrame:
        # Resource is created inside the worker, not on module import.
        from orchestrator.defs.resources import TushareResource

        result = TushareResource(token=self.token).call("weekly", params, fields)
        if len(result.rows) > max_rows:
            raise WeeklyCaptureError("unit_row_budget_exceeded")
        return pd.DataFrame(result.rows, columns=result.columns, dtype=object)


def weekly_source_params(unit: WeeklySourceUnit) -> dict:
    if (
        StockWeeklySource(unit.source) is not StockWeeklySource.ALTERNATE_WEEKLY
        or not 0 < unit.max_rows <= 54
    ):
        raise WeeklyCaptureError("weekly_unit_invalid")
    normalize_weekly_code(unit.ts_code)
    normalize_week_key(unit.anchor_start)
    normalize_week_key(unit.anchor_end)
    start = datetime.fromisoformat(unit.anchor_start).date()
    end = datetime.fromisoformat(unit.anchor_end).date()
    if (
        start > end
        or start.year != end.year
        or unit.request_start != start - timedelta(days=4)
        or unit.request_end != end + timedelta(days=2)
    ):
        raise WeeklyCaptureError("weekly_unit_invalid")
    return {
        "ts_code": unit.ts_code,
        "start_date": unit.request_start.strftime("%Y%m%d"),
        "end_date": unit.request_end.strftime("%Y%m%d"),
    }


def _weekly_worker_entry(
    sender,
    worker: WeeklySourceWorker,
    params: dict,
    fields: tuple[str, ...],
    max_rows: int,
) -> None:
    try:
        frame = worker(params, fields, max_rows)
        if not isinstance(frame, pd.DataFrame) or tuple(frame.columns) != fields:
            sender.send(("source_schema_mismatch", None, "response_schema"))
        elif len(frame) > max_rows:
            sender.send(("unit_row_budget_exceeded", None, "unit_row_budget"))
        else:
            sender.send(("ok", frame, None))
    except WeeklyCaptureError as error:
        # Only local known contract reasons are exposed by our SDK worker.
        reason = str(error)
        sender.send(
            (
                reason
                if reason in {"unit_row_budget_exceeded", "source_schema_mismatch"}
                else "source_failed",
                None,
                {
                    "unit_row_budget_exceeded": "unit_row_budget",
                    "source_schema_mismatch": "response_schema",
                }.get(reason, "unknown"),
            )
        )
    except Exception as error:  # noqa: BLE001 -- Worker must never expose SDK exception text.
        # SDK exception text may contain token or URL: never send/persist it.
        sender.send(("source_failed", None, _source_exception_category(error)))
    finally:
        sender.close()


def fetch_weekly_supervised(
    worker: WeeklySourceWorker,
    unit: WeeklySourceUnit,
    budget: WeeklyBudget,
    cancel: CancelProbe,
    progress: Callable[[], None] = lambda: None,
) -> pd.DataFrame:
    return fetch_weekly_request_supervised(
        worker,
        weekly_source_params(unit),
        ALTERNATE_WEEKLY_FIELDS,
        unit.max_rows,
        budget,
        cancel,
        progress,
    )


def fetch_weekly_request_supervised(
    worker, params, fields, max_rows, budget, cancel, progress=lambda: None
):
    check_weekly_cancel(cancel)
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_weekly_worker_entry,
        args=(sender, worker, params, fields, max_rows),
    )
    process.start()
    sender.close()
    deadline = time.monotonic() + budget.call_timeout_seconds
    try:
        while True:
            progress()
            check_weekly_cancel(cancel)
            if time.monotonic() >= deadline:
                raise _source_error("source_timeout", "supervisor_timeout")
            if receiver.poll(0.1):
                try:
                    reason, frame, category = receiver.recv()
                except EOFError:
                    raise _source_error("source_failed", "worker_eof") from None
                if reason != "ok":
                    raise _source_error(reason, category)
                return frame
            if not process.is_alive():
                raise _source_error("source_failed", "worker_exit")
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
        receiver.close()
        if process.is_alive():
            raise _source_error("source_worker_not_terminated", "worker_not_terminated")
        process.close()


def capture_weekly_source_unit(
    connection,
    unit: WeeklySourceUnit,
    *,
    worker: WeeklySourceWorker,
    store: WeeklyCaptureStore,
    cancel: CancelProbe,
    progress: Callable[[], None] = lambda: None,
) -> dict:
    budget = store.manifest.budget
    params = weekly_source_params(unit)
    for retry in range(budget.max_retries + 1):
        check_weekly_cancel(cancel)
        attempt = store.begin_attempt(unit)
        try:
            while datetime.now(UTC).timestamp() < store.next_request_at():
                check_weekly_cancel(cancel)
                progress()
                time.sleep(0.1)
            check_weekly_cancel(cancel)
            store.reserve_request()
            try:
                frame = fetch_weekly_supervised(worker, unit, budget, cancel, progress)
            finally:
                store.request_ended()
            check_weekly_cancel(cancel)
            chunk = store.write_chunk(connection, frame, unit, attempt, 0)
            check_weekly_cancel(cancel)
            return store.seal(
                connection,
                unit,
                [chunk],
                len(frame),
                {
                    "params": params,
                    "params_hash": stable_weekly_hash(params),
                    "fields": list(ALTERNATE_WEEKLY_FIELDS),
                    "api_name": "weekly",
                },
            )
        except WeeklyCaptureError as error:
            store.mark_failed(unit, str(error))
            if (
                str(error) not in ("source_failed", "source_timeout")
                or retry == budget.max_retries
            ):
                raise
        except Exception:  # noqa: BLE001 -- Persist capture failures without leaking source data.
            store.mark_failed(unit, "capture_failed")
            raise WeeklyCaptureError("capture_failed") from None
    raise WeeklyCaptureError("source_failed")
