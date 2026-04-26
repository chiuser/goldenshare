from __future__ import annotations

import time
from datetime import date
from typing import Any, Callable

import typer
from sqlalchemy import func, select


def resolve_default_sync_date(
    session,
    *,
    build_sync_service_fn: Callable[..., Any],
    default_exchange: str,
) -> date:
    trade_cal = build_sync_service_fn("trade_cal", session)
    trade_cal.run_incremental()
    today = date.today()
    latest = trade_cal.dao.trade_calendar.get_latest_open_date(default_exchange, today)
    if latest is None:
        raise typer.BadParameter("No open trade date found in trade calendar.")
    today_row = trade_cal.dao.trade_calendar.fetch_by_pk(default_exchange, today)
    if today_row is None:
        raise typer.BadParameter("Today's trade calendar row is missing.")
    if today_row.is_open:
        if today_row.pretrade_date is None:
            raise typer.BadParameter("Today's trade calendar row has no pretrade_date.")
        return today_row.pretrade_date
    return latest


def open_task_run_counts(session, *, task_run_model) -> tuple[int, int]:
    queued = session.scalar(
        select(func.count()).select_from(task_run_model).where(task_run_model.status == "queued")
    ) or 0
    running = session.scalar(
        select(func.count()).select_from(task_run_model).where(task_run_model.status == "running")
    ) or 0
    return int(queued), int(running)


def auto_reconcile_stale_task_runs(
    session,
    *,
    stale_for_minutes: int,
    limit: int,
    reconciliation_service,
) -> int:
    if stale_for_minutes <= 0:
        return 0
    reconciled = reconciliation_service.reconcile_stale_task_runs(
        session,
        stale_for_minutes=stale_for_minutes,
        limit=limit,
    )
    return len(reconciled)


def prepare_sync_kwargs_for_service(service, kwargs: dict[str, object | None]) -> dict[str, object]:
    filtered = {key: value for key, value in kwargs.items() if value is not None}
    service_vars = vars(service)
    if "contract" not in service_vars:
        return filtered
    contract = service_vars.get("contract")
    input_schema = getattr(contract, "input_schema", None)
    fields = getattr(input_schema, "fields", None)
    if not isinstance(fields, (list, tuple)) or not fields:
        return filtered

    allowed = {
        getattr(field, "name", "")
        for field in fields
        if getattr(field, "name", "")
    }
    passthrough = {"run_profile", "source_key", "correlation_id", "rerun_id", "trigger_source", "request_id"}
    return {key: value for key, value in filtered.items() if key in allowed or key in passthrough}


def attach_cli_progress_reporter(service, *, resource: str) -> None:
    if not hasattr(service, "set_cli_progress_reporter"):
        return
    service_vars = vars(service)
    if "contract" not in service_vars:
        return

    state: dict[str, float | int] = {
        "last_emit_at": 0.0,
        "last_emit_current": 0,
    }
    min_emit_seconds = 8.0
    min_emit_delta = 50

    def progress_reporter(progress_snapshot, _: str) -> None:  # type: ignore[no-untyped-def]
        current = int(progress_snapshot.unit_done + progress_snapshot.unit_failed)
        total = int(progress_snapshot.unit_total)
        rows_fetched = int(progress_snapshot.rows_fetched)
        rows_written = int(progress_snapshot.rows_written)
        last_emit_current = int(state["last_emit_current"])
        now = time.monotonic()
        elapsed = float(now - float(state["last_emit_at"]))

        should_emit = (
            current in (0, total)
            or current - last_emit_current >= min_emit_delta
            or elapsed >= min_emit_seconds
        )
        if not should_emit:
            return

        percent = f"{(current / total * 100):.1f}%" if total else "-"
        typer.echo(
            f"[{resource}] progress {current}/{total} ({percent}) "
            f"fetched={rows_fetched} written={rows_written}"
        )
        state["last_emit_at"] = now
        state["last_emit_current"] = current

    service.set_cli_progress_reporter(progress_reporter)
