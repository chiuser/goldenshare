"""Narrow read-only prod TaskRun contract for daily stock-minute readiness."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter

from orchestrator.defs.resources import ProdPostgresResource
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_SOURCE_FREQS


PROD_STK_MINS_TASK_RUN_QUERY_LIMIT = 20
PROD_STK_MINS_TASK_RUN_COLUMNS = (
    "id",
    "task_type",
    "resource_key",
    "action",
    "status",
    "status_reason_code",
    "ended_at",
    "unit_total",
    "unit_done",
    "unit_failed",
    "progress_percent",
    "rows_fetched",
    "rows_saved",
    "rows_rejected",
    "time_input_json",
    "filters_json",
)


@dataclass(frozen=True, slots=True)
class ProdStkMinsFullMarketTaskRun:
    task_run_id: int
    trade_date: str
    ended_at: str
    unit_total: int
    unit_done: int
    unit_failed: int
    progress_percent: float
    rows_fetched: int
    rows_saved: int
    rows_rejected: int


@dataclass(frozen=True, slots=True)
class ProdStkMinsTaskRunProbe:
    ready: bool
    reason_code: str
    task_run: ProdStkMinsFullMarketTaskRun | None
    candidate_task_run_id: int | None
    candidate_status: str | None
    candidate_reason_code: str | None
    elapsed_ms: int
    error_type: str | None = None


def probe_full_market_stk_mins_task_run(
    *,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
) -> ProdStkMinsTaskRunProbe:
    """Return only a validated all-market completion record for one trade date."""

    started = perf_counter()
    try:
        rows = _load_task_run_rows(prod_postgres=prod_postgres, trade_date=trade_date)
    except Exception as error:
        return ProdStkMinsTaskRunProbe(
            ready=False,
            reason_code="prod_ops_task_run_query_error",
            task_run=None,
            candidate_task_run_id=None,
            candidate_status=None,
            candidate_reason_code=None,
            elapsed_ms=int((perf_counter() - started) * 1000),
            error_type=type(error).__name__,
        )
    probe = evaluate_full_market_stk_mins_task_run_rows(rows, trade_date=trade_date)
    return ProdStkMinsTaskRunProbe(
        ready=probe.ready,
        reason_code=probe.reason_code,
        task_run=probe.task_run,
        candidate_task_run_id=probe.candidate_task_run_id,
        candidate_status=probe.candidate_status,
        candidate_reason_code=probe.candidate_reason_code,
        elapsed_ms=int((perf_counter() - started) * 1000),
        error_type=None,
    )


def probe_full_market_stk_mins_task_run_by_id(
    *,
    prod_postgres: ProdPostgresResource,
    task_run_id: int,
    trade_date: str,
) -> ProdStkMinsTaskRunProbe:
    """Revalidate the exact source completion record carried by a run config."""

    if task_run_id <= 0:
        raise ValueError("task_run_id must be positive.")
    started = perf_counter()
    try:
        row = _load_task_run_row_by_id(
            prod_postgres=prod_postgres,
            task_run_id=task_run_id,
        )
    except Exception as error:
        return ProdStkMinsTaskRunProbe(
            ready=False,
            reason_code="prod_ops_task_run_query_error",
            task_run=None,
            candidate_task_run_id=task_run_id,
            candidate_status=None,
            candidate_reason_code=None,
            elapsed_ms=int((perf_counter() - started) * 1000),
            error_type=type(error).__name__,
        )
    probe = evaluate_full_market_stk_mins_task_run_rows(
        () if row is None else (row,),
        trade_date=trade_date,
    )
    return ProdStkMinsTaskRunProbe(
        ready=probe.ready,
        reason_code=probe.reason_code,
        task_run=probe.task_run,
        candidate_task_run_id=probe.candidate_task_run_id,
        candidate_status=probe.candidate_status,
        candidate_reason_code=probe.candidate_reason_code,
        elapsed_ms=int((perf_counter() - started) * 1000),
        error_type=None,
    )


def evaluate_full_market_stk_mins_task_run_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    trade_date: str,
) -> ProdStkMinsTaskRunProbe:
    """Pure, fail-closed TaskRun selection shared by daily and recovery paths."""

    candidate = rows[0] if rows else None
    for row in rows:
        task_run = full_market_stk_mins_task_run_from_row(row, trade_date=trade_date)
        if task_run is not None:
            return ProdStkMinsTaskRunProbe(
                ready=True,
                reason_code="prod_ops_task_run_ready",
                task_run=task_run,
                candidate_task_run_id=int(row["id"]),
                candidate_status=str(row["status"]),
                candidate_reason_code=_optional_text(row.get("status_reason_code")),
                elapsed_ms=0,
            )

    if candidate is None:
        return ProdStkMinsTaskRunProbe(
            ready=False,
            reason_code="prod_ops_task_run_missing",
            task_run=None,
            candidate_task_run_id=None,
            candidate_status=None,
            candidate_reason_code=None,
            elapsed_ms=0,
        )
    return ProdStkMinsTaskRunProbe(
        ready=False,
        reason_code="prod_ops_task_run_not_full_market_success",
        task_run=None,
        candidate_task_run_id=_optional_int(candidate.get("id")),
        candidate_status=_optional_text(candidate.get("status")),
        candidate_reason_code=_optional_text(candidate.get("status_reason_code")),
        elapsed_ms=0,
    )


def full_market_stk_mins_task_run_from_row(
    row: Mapping[str, object],
    *,
    trade_date: str,
) -> ProdStkMinsFullMarketTaskRun | None:
    """Return a normalized completion only when every source fact is closed."""

    if (
        row.get("task_type") != "dataset_action"
        or row.get("resource_key") != "stk_mins"
        or row.get("action") != "maintain"
        or row.get("status") != "success"
        or row.get("ended_at") is None
    ):
        return None
    time_input = _json_mapping(row.get("time_input_json"))
    filters = _json_mapping(row.get("filters_json"))
    if time_input.get("trade_date") != trade_date:
        return None
    if _normalized_requested_freqs(filters.get("freq")) != _expected_freq_labels():
        return None
    if _has_explicit_code_filter(filters.get("ts_code")):
        return None
    unit_total = _int(row.get("unit_total"))
    unit_done = _int(row.get("unit_done"))
    unit_failed = _int(row.get("unit_failed"))
    progress_percent = _float(row.get("progress_percent"))
    rows_fetched = _int(row.get("rows_fetched"))
    rows_saved = _int(row.get("rows_saved"))
    rows_rejected = _int(row.get("rows_rejected"))
    if not (
        unit_total > 0
        and unit_done == unit_total
        and unit_failed == 0
        and progress_percent == 100.0
        and rows_fetched > 0
        and rows_saved > 0
        and rows_rejected == 0
    ):
        return None
    task_run_id = _optional_int(row.get("id"))
    ended_at = _datetime_text(row.get("ended_at"))
    if task_run_id is None or ended_at is None:
        return None
    return ProdStkMinsFullMarketTaskRun(
        task_run_id=task_run_id,
        trade_date=trade_date,
        ended_at=ended_at,
        unit_total=unit_total,
        unit_done=unit_done,
        unit_failed=unit_failed,
        progress_percent=progress_percent,
        rows_fetched=rows_fetched,
        rows_saved=rows_saved,
        rows_rejected=rows_rejected,
    )


def _load_task_run_rows(
    *,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
) -> tuple[dict[str, object], ...]:
    sql = f"""
    SELECT
      {", ".join(PROD_STK_MINS_TASK_RUN_COLUMNS)}
    FROM ops.task_run
    WHERE task_type = 'dataset_action'
      AND resource_key = 'stk_mins'
      AND action = 'maintain'
      AND time_input_json ->> 'trade_date' = %s
    ORDER BY ended_at DESC NULLS LAST, id DESC
    LIMIT %s
    """
    with prod_postgres.connect_readonly_transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, (trade_date, PROD_STK_MINS_TASK_RUN_QUERY_LIMIT))
            columns = tuple(description.name for description in cursor.description)
            return tuple(
                dict(zip(columns, row, strict=True))
                for row in cursor.fetchall()
            )


def _load_task_run_row_by_id(
    *,
    prod_postgres: ProdPostgresResource,
    task_run_id: int,
) -> dict[str, object] | None:
    sql = f"""
    SELECT
      {", ".join(PROD_STK_MINS_TASK_RUN_COLUMNS)}
    FROM ops.task_run
    WHERE id = %s
    """
    with prod_postgres.connect_readonly_transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, (task_run_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            columns = tuple(description.name for description in cursor.description)
            return dict(zip(columns, row, strict=True))


def _json_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, Mapping) else {}
    return {}


def _normalized_requested_freqs(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(sorted({str(item).strip().lower() for item in value if str(item).strip()}))


def _expected_freq_labels() -> tuple[str, ...]:
    return tuple(sorted(f"{freq}min" for freq in STK_MINS_SOURCE_FREQS))


def _has_explicit_code_filter(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Sequence):
        return any(str(item).strip() for item in value)
    return True


def _int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _optional_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _datetime_text(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return _optional_text(value)
