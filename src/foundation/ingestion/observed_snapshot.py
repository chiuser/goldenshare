from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal
import base64
import hashlib
import json
from typing import Any


class ObservedSnapshotHashError(ValueError):
    """Base error for deterministic source-content hashing failures."""


class SourceFieldMissingError(ObservedSnapshotHashError):
    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"完整快照缺少显式 source field：{field}")


class SourceContentValueUnsupportedError(ObservedSnapshotHashError):
    def __init__(self, field: str, value: object) -> None:
        self.field = field
        self.value_type = type(value).__name__
        super().__init__(f"source field {field} 的值类型不支持确定性哈希：{self.value_type}")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def compute_source_content_hash(*, row: Mapping[str, Any], source_fields: Sequence[str]) -> str:
    """Hash exactly the declared source fields in declaration order.

    The envelope preserves scalar type information, handles null explicitly and
    avoids implicit ``str(value)`` coercion.  It is intentionally pure so a
    dataset transform may use the same hash for a content-based fallback key;
    the writer still recomputes it before persistence.
    """
    fields = tuple(source_fields)
    if not fields:
        raise ObservedSnapshotHashError("观察快照必须声明至少一个 source field")

    payload: list[dict[str, object]] = []
    for field in fields:
        if field not in row:
            raise SourceFieldMissingError(field)
        payload.append({"field": field, "value": _canonical_value(row[field], field=field)})
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical_value(value: Any, *, field: str) -> object:
    if value is None:
        return {"type": "null", "value": None}
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, int):
        return {"type": "int", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value.hex()}
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": _canonical_decimal(value)}
    if isinstance(value, str):
        return {"type": "str", "value": value}
    if isinstance(value, bytes):
        return {"type": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": _canonical_datetime(value)}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, Mapping):
        return {
            "type": "mapping",
            "value": [
                {"key": str(key), "value": _canonical_value(item, field=field)}
                for key, item in sorted(value.items(), key=lambda item: str(item[0]))
            ],
        }
    if isinstance(value, tuple):
        return {"type": "tuple", "value": [_canonical_value(item, field=field) for item in value]}
    if isinstance(value, list):
        return {"type": "list", "value": [_canonical_value(item, field=field) for item in value]}
    raise SourceContentValueUnsupportedError(field, value)


def _canonical_decimal(value: Decimal) -> str:
    if value.is_nan():
        return "NaN"
    if value.is_infinite():
        return "Infinity" if value > 0 else "-Infinity"
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _canonical_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        return value.isoformat(timespec="microseconds")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
