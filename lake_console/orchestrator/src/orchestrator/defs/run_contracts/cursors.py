"""Sensor-private cursor payload helpers."""

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from typing import Any


SENSOR_CURSOR_SCHEMA_VERSION = 1
MAX_CURSOR_SAMPLE_KEYS = 20
TYPICAL_SENSOR_CURSOR_BYTES = 2048
COMPLEX_SENSOR_CURSOR_BYTES = 3072
MAX_SENSOR_CURSOR_BYTES = 8192
_REQUIRED_DETAILS_TEXT_KEYS = frozenset({"summary", "next_action"})
_FORBIDDEN_CURSOR_DETAIL_KEYS = frozenset(
    {
        "status_samples",
        "sample_rows",
        "missing_file_paths",
        "readiness_details",
        "raw_batch_status",
        "silver_batch_status",
        "gold_batch_status",
        "serving_batch_status",
        "upstream_batch_statuses",
        "batch_status",
    }
)


class SensorCursorDecision(str, Enum):
    SKIP = "skip"
    REQUEST_RUNS = "request_runs"
    REGISTER_PARTITIONS = "register_partitions"
    NOTIFY = "notify"


def _coerce_cursor_decision(decision: SensorCursorDecision | str) -> SensorCursorDecision:
    if isinstance(decision, SensorCursorDecision):
        return decision
    return SensorCursorDecision(decision)


def _require_non_negative(value: int, field_name: str) -> int:
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative.")
    return value


def _assert_reason_values_are_ascii(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if (
                key in {"reason", "reason_code"}
                and isinstance(item, str)
                and not item.isascii()
            ):
                raise ValueError(
                    f"{child_path} must be ASCII. Use reason_code for cursor "
                    "decision diagnostics and keep human text in SkipReason."
                )
            _assert_reason_values_are_ascii(item, path=child_path)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _assert_reason_values_are_ascii(item, path=f"{path}[{index}]")


def _assert_details_contract(details: Mapping[str, Any]) -> None:
    missing_keys = sorted(
        key
        for key in _REQUIRED_DETAILS_TEXT_KEYS
        if not isinstance(details.get(key), str) or not str(details.get(key)).strip()
    )
    if missing_keys:
        raise ValueError(
            "sensor cursor details must include non-empty summary and next_action; "
            f"missing: {', '.join(missing_keys)}."
        )


def _assert_no_report_fields(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if (
                key_text in _FORBIDDEN_CURSOR_DETAIL_KEYS
                or key_text.endswith("_batch_status")
                or key_text.endswith("_batch_statuses")
            ):
                raise ValueError(
                    f"{child_path} is not allowed in sensor cursor details. "
                    "Cursor payloads must stay compact; keep full diagnostics in "
                    "asset/check metadata or readiness reports."
                )
            _assert_no_report_fields(item, path=child_path)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _assert_no_report_fields(item, path=f"{path}[{index}]")


def build_sensor_cursor(
    *,
    evaluated_at: datetime,
    decision: SensorCursorDecision | str,
    target_date: str | None = None,
    selected_count: int = 0,
    blocked_count: int = 0,
    sample_keys: Sequence[str] = (),
    details: Mapping[str, Any] | None = None,
) -> str:
    """Build a versioned cursor payload for one sensor's diagnostics and progress."""

    details_payload = dict(details) if details else {}
    if details_payload:
        _assert_details_contract(details_payload)
        _assert_no_report_fields(details_payload, path="details")
    _assert_reason_values_are_ascii(details_payload, path="details")
    payload = {
        "schema_version": SENSOR_CURSOR_SCHEMA_VERSION,
        "evaluated_at": evaluated_at.isoformat(),
        "decision": _coerce_cursor_decision(decision).value,
        "target_date": target_date,
        "selected_count": _require_non_negative(selected_count, "selected_count"),
        "blocked_count": _require_non_negative(blocked_count, "blocked_count"),
        "sample_keys": list(sample_keys[:MAX_CURSOR_SAMPLE_KEYS]),
        "details": details_payload,
    }
    cursor = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    cursor_size = len(cursor.encode("utf-8"))
    if cursor_size > MAX_SENSOR_CURSOR_BYTES:
        raise ValueError(
            "sensor cursor must not exceed "
            f"{MAX_SENSOR_CURSOR_BYTES} bytes; got {cursor_size} bytes."
        )
    return cursor


def load_sensor_cursor(cursor: str | None) -> dict[str, Any]:
    """Load a versioned sensor cursor payload, returning an empty payload when unsafe."""

    if not cursor:
        return {}
    try:
        payload = json.loads(cursor)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("schema_version") != SENSOR_CURSOR_SCHEMA_VERSION:
        return {}
    details = payload.get("details")
    if details is not None and not isinstance(details, dict):
        return {}
    return payload


def sensor_cursor_details(cursor_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return sensor-specific cursor details from a loaded versioned payload."""

    details = cursor_payload.get("details")
    return dict(details) if isinstance(details, Mapping) else {}
