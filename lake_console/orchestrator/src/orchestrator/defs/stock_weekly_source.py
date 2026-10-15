"""Terminable request transport retained for the monthly source consumer."""

from __future__ import annotations

import json
import multiprocessing
import time
from typing import Protocol

import pandas as pd
from requests import exceptions as request_errors

from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    check_weekly_cancel,
)
from orchestrator.defs.tushare_errors import TushareResponseError

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
    if isinstance(error, TushareResponseError):
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
