"""Sensor-private cursor payload helpers."""

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from typing import Any


SENSOR_CURSOR_SCHEMA_VERSION = 1
MAX_CURSOR_SAMPLE_KEYS = 20


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

    payload = {
        "schema_version": SENSOR_CURSOR_SCHEMA_VERSION,
        "evaluated_at": evaluated_at.isoformat(),
        "decision": _coerce_cursor_decision(decision).value,
        "target_date": target_date,
        "selected_count": _require_non_negative(selected_count, "selected_count"),
        "blocked_count": _require_non_negative(blocked_count, "blocked_count"),
        "sample_keys": list(sample_keys[:MAX_CURSOR_SAMPLE_KEYS]),
        "details": dict(details) if details else {},
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


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
