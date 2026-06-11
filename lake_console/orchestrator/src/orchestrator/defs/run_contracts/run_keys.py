"""Run key and upstream batch id builders for Dagster automation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any


_FORBIDDEN_BATCH_PAYLOAD_KEYS = frozenset(
    {
        "event_storage_id",
        "event_storage_ids",
        "storage_id",
        "storage_ids",
    }
)


def build_asset_update_run_key(*, subject: str, unit_id: str) -> str:
    """Build the run key for one asset update unit."""

    subject = _require_segment(subject, field_name="subject")
    unit_id = _require_segment(unit_id, field_name="unit_id")
    return f"{subject}:{unit_id}"


def build_repair_attempt_run_key(
    *,
    subject: str,
    repair_scope_id: str,
    attempt: int,
    attempt_scope: str | None = None,
) -> str:
    """Build the run key for one bounded repair attempt."""

    subject = _require_segment(subject, field_name="subject")
    repair_scope_id = _require_segment(
        repair_scope_id,
        field_name="repair_scope_id",
    )
    _require_positive_attempt(attempt)

    if attempt_scope is None:
        return f"{subject}:{repair_scope_id}:{attempt}"
    if not isinstance(attempt_scope, str):
        raise ValueError("attempt_scope must be a string")
    if attempt_scope.strip() == "":
        return f"{subject}:{repair_scope_id}:{attempt}"

    return f"{subject}:{repair_scope_id}:{attempt_scope}:{attempt}"


def build_upstream_triggered_run_key(
    *,
    consumer: str,
    upstream_batch_id: str,
) -> str:
    """Build the run key for a consumer triggered by an upstream batch."""

    consumer = _require_segment(consumer, field_name="consumer")
    upstream_batch_id = _require_segment(
        upstream_batch_id,
        field_name="upstream_batch_id",
    )
    return f"{consumer}:{upstream_batch_id}"


def build_batch_id(
    *,
    producer: str,
    scope: str,
    payload: Mapping[str, Any],
    digest_length: int = 12,
) -> str:
    """Build an opaque upstream batch id from a stable business payload."""

    producer = _require_segment(producer, field_name="producer")
    scope = _require_segment(scope, field_name="scope")
    _require_digest_length(digest_length)
    canonical_payload = _canonical_payload(payload)
    canonical_json = json.dumps(
        canonical_payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = sha256(canonical_json.encode("utf-8")).hexdigest()[:digest_length]
    return f"{producer}:{scope}:{digest}"


def _require_segment(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if value.strip() == "":
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_positive_attempt(attempt: int) -> None:
    if isinstance(attempt, bool) or not isinstance(attempt, int):
        raise ValueError("attempt must be an integer")
    if attempt <= 0:
        raise ValueError("attempt must be positive")


def _require_digest_length(digest_length: int) -> None:
    if isinstance(digest_length, bool) or not isinstance(digest_length, int):
        raise ValueError("digest_length must be an integer")
    if digest_length <= 0 or digest_length > 64:
        raise ValueError("digest_length must be greater than 0 and no more than 64")


def _canonical_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")
    if not payload:
        raise ValueError("payload must be non-empty")
    if "producer_run_id" not in payload:
        raise ValueError("payload must contain producer_run_id")
    return _canonical_mapping(payload, path="payload")


def _canonical_mapping(value: Mapping[str, Any], *, path: str) -> dict[str, Any]:
    canonical: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{path} keys must be strings")
        if key.strip() == "":
            raise ValueError(f"{path} keys must be non-empty strings")
        if key in _FORBIDDEN_BATCH_PAYLOAD_KEYS:
            raise ValueError(f"payload must not contain {key}")
        canonical[key] = _canonical_json_value(item, path=f"{path}.{key}")
    return canonical


def _canonical_json_value(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return _canonical_mapping(value, path=path)
    if isinstance(value, tuple):
        return [_canonical_json_value(item, path=path) for item in value]
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_canonical_json_value(item, path=path) for item in value]
    raise ValueError(f"{path} must be JSON serializable")
