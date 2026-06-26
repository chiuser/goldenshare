"""Compact cursor payload builders for Dagster sensors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


CURSOR_SAMPLE_LIMIT = 3


def limit_cursor_samples(
    values: Sequence[object] | None,
    *,
    sample_limit: int = CURSOR_SAMPLE_LIMIT,
) -> list[object]:
    if values is None or sample_limit <= 0:
        return []
    return list(values[:sample_limit])


def reason_code_from(value: object, *, fallback: str = "not_ready") -> str:
    text = str(value or "").strip().lower()
    if not text or not text.isascii():
        return fallback
    normalized = "".join(char if char.isalnum() else "_" for char in text)
    normalized = "_".join(part for part in normalized.split("_") if part)
    return normalized or fallback


def cursor_runtime_state(details: Mapping[str, Any]) -> dict[str, Any]:
    runtime_state = details.get("runtime_state")
    return dict(runtime_state) if isinstance(runtime_state, Mapping) else {}


def runtime_state_value(
    details: Mapping[str, Any],
    key: str,
    *,
    default: object = None,
) -> object:
    runtime_state = cursor_runtime_state(details)
    if key in runtime_state:
        return runtime_state[key]
    return details.get(key, default)


def build_cursor_details(
    *,
    sensor_name: str,
    job_name: str | None,
    asset_family: str,
    partition_set: str | None,
    reason_code: str,
    blocked_component: str | None,
    summary: str,
    next_action: str,
    frontier: Mapping[str, object] | None = None,
    gate_statuses: Mapping[str, object] | None = None,
    evidence: Mapping[str, object] | None = None,
    runtime_state: Mapping[str, object] | None = None,
    performance_ms: Mapping[str, object] | None = None,
    diagnostic_ref: Mapping[str, object] | None = None,
) -> dict[str, object]:
    details: dict[str, object] = {
        "sensor_name": sensor_name,
        "job_name": job_name,
        "asset_family": asset_family,
        "partition_set": partition_set,
        "reason_code": reason_code_from(reason_code, fallback="unknown"),
        "blocked_component": blocked_component or "none",
        "summary": summary,
        "next_action": next_action,
    }
    for key, value in (
        ("frontier", frontier),
        ("gate_statuses", gate_statuses),
        ("evidence", evidence),
        ("runtime_state", runtime_state),
        ("performance_ms", performance_ms),
        ("diagnostic_ref", diagnostic_ref),
    ):
        compact_value = _drop_empty(value)
        if compact_value not in (None, {}, []):
            details[key] = compact_value
    return details


def compact_asset_readiness_status(status: object | None) -> dict[str, object] | None:
    if status is None:
        return None
    return {
        "asset_key": getattr(status, "asset_key", None),
        "partition_key": getattr(status, "partition_key", None),
        "ready": bool(getattr(status, "ready", False)),
        "materialized": bool(getattr(status, "materialized", False)),
        "checks_passed": bool(getattr(status, "checks_passed", False)),
        "freshness_passed": bool(getattr(status, "freshness_passed", True)),
        "reason_code": reason_code_from(getattr(status, "reason", None)),
        "missing_check_names": limit_cursor_samples(
            tuple(getattr(status, "missing_check_names", ()) or ())
        ),
        "failed_check_names": limit_cursor_samples(
            tuple(getattr(status, "failed_check_names", ()) or ())
        ),
        "missing_check_count": len(tuple(getattr(status, "missing_check_names", ()) or ())),
        "failed_check_count": len(tuple(getattr(status, "failed_check_names", ()) or ())),
    }


def compact_date_readiness(status: object | None) -> dict[str, object] | None:
    if status is None:
        return None
    failed_check_names = tuple(getattr(status, "failed_check_names", ()) or ())
    missing_check_names = tuple(getattr(status, "missing_check_names", ()) or ())
    missing_file_paths = tuple(getattr(status, "missing_file_paths", ()) or ())
    payload: dict[str, object] = {
        "trade_date": getattr(status, "trade_date", None),
        "ready": bool(getattr(status, "ready", False)),
        "materialized": bool(getattr(status, "materialized", False)),
        "checks_passed": bool(getattr(status, "checks_passed", False)),
        "reason_code": reason_code_from(getattr(status, "reason", None)),
        "failed_check_names": limit_cursor_samples(failed_check_names),
        "missing_check_names": limit_cursor_samples(missing_check_names),
        "failed_check_count": len(failed_check_names),
        "missing_check_count": len(missing_check_names),
        "missing_file_count": len(missing_file_paths),
    }
    for attr_name in (
        "expected_file_count",
        "existing_file_count",
        "checked_row_count",
        "failed_row_count",
    ):
        value = getattr(status, attr_name, None)
        if value is not None:
            payload[attr_name] = value
    return payload


def compact_dataset_readiness(status: object | None) -> dict[str, object] | None:
    if status is None:
        return None
    statuses = tuple(getattr(status, "statuses", ()) or ())
    not_ready_statuses = tuple(
        asset_status for asset_status in statuses if not getattr(asset_status, "ready", False)
    )
    missing_check_names: list[object] = []
    failed_check_names: list[object] = []
    for asset_status in not_ready_statuses:
        missing_check_names.extend(tuple(getattr(asset_status, "missing_check_names", ()) or ()))
        failed_check_names.extend(tuple(getattr(asset_status, "failed_check_names", ()) or ()))
    first_not_ready = not_ready_statuses[0] if not_ready_statuses else None
    return {
        "ready": bool(getattr(status, "ready", False)),
        "reason_code": reason_code_from(getattr(status, "reason", None), fallback="ready"),
        "asset_count": len(statuses),
        "not_ready_count": len(not_ready_statuses),
        "first_not_ready_asset": getattr(first_not_ready, "asset_key", None),
        "first_not_ready_partition": getattr(first_not_ready, "partition_key", None),
        "missing_check_names": limit_cursor_samples(tuple(missing_check_names)),
        "failed_check_names": limit_cursor_samples(tuple(failed_check_names)),
        "missing_check_count": len(missing_check_names),
        "failed_check_count": len(failed_check_names),
    }


def compact_readiness_status(status: object | None) -> dict[str, object] | None:
    if status is None:
        return None
    if hasattr(status, "statuses"):
        return compact_dataset_readiness(status)
    if hasattr(status, "asset_key"):
        return compact_asset_readiness_status(status)
    return compact_date_readiness(status)


def compact_gate_statuses(
    statuses: Mapping[str, object | None],
) -> dict[str, object]:
    compacted: dict[str, object] = {}
    for key, status in statuses.items():
        compact_status = compact_readiness_status(status)
        if compact_status is not None:
            compacted[key] = compact_status
    return compacted


def compact_batch_frontier(
    batch_status: object | None,
    *,
    selected_trade_date: str | None = None,
) -> dict[str, object] | None:
    if batch_status is None:
        return None
    expected_trade_dates = tuple(getattr(batch_status, "expected_trade_dates", ()) or ())
    if not expected_trade_dates:
        start_date = getattr(batch_status, "expected_start_date", None)
        end_date = getattr(batch_status, "expected_end_date", None)
        expected_count = int(getattr(batch_status, "expected_count", 0) or 0)
    else:
        start_date = expected_trade_dates[0]
        end_date = expected_trade_dates[-1]
        expected_count = len(expected_trade_dates)

    ready_through_date = None
    first_not_ready_date = None
    first_not_ready_reason = None
    for trade_date in expected_trade_dates:
        status = _status_for_trade_date(batch_status, str(trade_date))
        if status is None or not getattr(status, "ready", False):
            first_not_ready_date = str(trade_date)
            first_not_ready_reason = reason_code_from(
                getattr(status, "reason", None),
                fallback="readiness_status_missing",
            )
            break
        ready_through_date = str(trade_date)

    frontier: dict[str, object] = {
        "dataset": getattr(batch_status, "dataset", None),
        "expected_start_date": start_date,
        "expected_end_date": end_date,
        "expected_count": expected_count,
        "ready_through_date": ready_through_date,
        "first_not_ready_date": first_not_ready_date,
        "first_not_ready_reason": first_not_ready_reason,
        "selected_date": selected_trade_date,
        "elapsed_ms": getattr(batch_status, "elapsed_ms", None),
        "scanned_file_count": getattr(batch_status, "scanned_file_count", None),
        "freq_count": getattr(batch_status, "freq_count", None),
    }
    return _drop_empty(frontier)


def compact_continuity_frontier(
    continuity_status: Mapping[str, object] | object | None,
    *,
    selected_trade_date: str | None = None,
) -> dict[str, object] | None:
    if continuity_status is None:
        return None
    if isinstance(continuity_status, Mapping):
        source = continuity_status
        first_missing_registered_date = source.get("first_missing_registered_date")
        ready_through_trade_date = source.get("ready_through_trade_date") or source.get(
            "ready_through_date"
        )
        first_not_ready_trade_date = source.get("first_not_ready_trade_date") or source.get(
            "first_not_ready_date"
        )
        frontier = {
            "expected_start_date": source.get("expected_start_date"),
            "expected_end_date": source.get("expected_end_date"),
            "expected_count": source.get("expected_count"),
            "registered_count": source.get("registered_count"),
            "first_missing_registered_date": first_missing_registered_date,
            "ready_through_date": ready_through_trade_date,
            "first_not_ready_date": first_not_ready_trade_date,
            "selected_date": selected_trade_date or source.get("selected_trade_date"),
            "blocked_reason": source.get("blocked_reason"),
            "elapsed_ms": source.get("batch_elapsed_ms") or source.get("elapsed_ms"),
            "scanned_file_count": source.get("scanned_file_count"),
        }
        return _drop_empty(frontier)
    if hasattr(continuity_status, "expected_trade_dates"):
        return _drop_empty(
            {
                "expected_start_date": _first_or_none(
                    tuple(getattr(continuity_status, "expected_trade_dates", ()) or ())
                ),
                "expected_end_date": _last_or_none(
                    tuple(getattr(continuity_status, "expected_trade_dates", ()) or ())
                ),
                "expected_count": len(
                    tuple(getattr(continuity_status, "expected_trade_dates", ()) or ())
                ),
                "registered_count": len(
                    tuple(getattr(continuity_status, "registered_trade_dates", ()) or ())
                ),
                "first_missing_registered_date": getattr(
                    continuity_status, "first_missing_registered_date", None
                ),
                "selected_date": selected_trade_date,
            }
        )
    if hasattr(continuity_status, "expected_count"):
        return _drop_empty(
            {
                "partition_set_name": getattr(
                    continuity_status, "partition_set_name", None
                ),
                "expected_start_date": getattr(
                    continuity_status, "expected_start_date", None
                ),
                "expected_end_date": getattr(
                    continuity_status, "expected_end_date", None
                ),
                "expected_count": getattr(continuity_status, "expected_count", None),
                "registered_count": getattr(
                    continuity_status, "registered_count", None
                ),
                "ready_count": getattr(continuity_status, "ready_count", None),
                "first_missing_registered_date": getattr(
                    continuity_status, "first_missing_registered_date", None
                ),
                "first_not_ready_date": getattr(
                    continuity_status, "first_not_ready_trade_date", None
                ),
                "first_not_ready_reason": getattr(
                    continuity_status, "first_not_ready_reason", None
                ),
                "ready_through_date": getattr(
                    continuity_status, "ready_through_trade_date", None
                ),
                "next_actionable_date": getattr(
                    continuity_status, "next_actionable_trade_date", None
                ),
                "selected_date": selected_trade_date,
                "blocked_reason": getattr(continuity_status, "blocked_reason", None),
            }
        )
    return None


def merge_frontiers(*frontiers: Mapping[str, object] | None) -> dict[str, object]:
    merged: dict[str, object] = {}
    for index, frontier in enumerate(frontiers):
        if frontier:
            merged[f"frontier_{index + 1}"] = dict(frontier)
    return merged


def _status_for_trade_date(batch_status: object, trade_date: str) -> object | None:
    status_for_trade_date = getattr(batch_status, "status_for_trade_date", None)
    if callable(status_for_trade_date):
        return status_for_trade_date(trade_date)
    statuses_by_trade_date = getattr(batch_status, "statuses_by_trade_date", None)
    if isinstance(statuses_by_trade_date, Mapping):
        return statuses_by_trade_date.get(trade_date)
    return None


def _drop_empty(value: object) -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            compact_item = _drop_empty(item)
            if compact_item not in (None, {}, []):
                result[str(key)] = compact_item
        return result
    if isinstance(value, tuple):
        return [_drop_empty(item) for item in value if _drop_empty(item) is not None]
    if isinstance(value, list):
        return [_drop_empty(item) for item in value if _drop_empty(item) is not None]
    return value


def _first_or_none(values: Sequence[object]) -> object | None:
    return values[0] if values else None


def _last_or_none(values: Sequence[object]) -> object | None:
    return values[-1] if values else None
