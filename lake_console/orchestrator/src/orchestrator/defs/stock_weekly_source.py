"""One-code annual weekly capture through a terminable SDK subprocess."""

from __future__ import annotations

import multiprocessing
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

import pandas as pd

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
            sender.send(("source_schema_mismatch", None))
        elif len(frame) > max_rows:
            sender.send(("unit_row_budget_exceeded", None))
        else:
            sender.send(("ok", frame))
    except WeeklyCaptureError as error:
        # Only local known contract reasons are exposed by our SDK worker.
        reason = str(error)
        sender.send(
            (
                reason
                if reason in {"unit_row_budget_exceeded", "source_schema_mismatch"}
                else "source_failed",
                None,
            )
        )
    except Exception:  # noqa: BLE001 -- Worker must never expose SDK exception text.
        # SDK exception text may contain token or URL: never send/persist it.
        sender.send(("source_failed", None))
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
                raise WeeklyCaptureError("source_timeout")
            if receiver.poll(0.1):
                try:
                    reason, frame = receiver.recv()
                except EOFError:
                    raise WeeklyCaptureError("source_failed") from None
                if reason != "ok":
                    raise WeeklyCaptureError(reason)
                return frame
            if not process.is_alive():
                raise WeeklyCaptureError("source_failed")
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
        receiver.close()
        if process.is_alive():
            raise WeeklyCaptureError("source_worker_not_terminated")
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
