from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal


ResolutionMode = Literal["primary", "fallback", "primary_fallback", "field_merge", "freshness_first"]


@dataclass(frozen=True)
class ResolutionPolicy:
    dataset_key: str
    mode: ResolutionMode
    primary_source_key: str
    fallback_source_keys: tuple[str, ...] = ()
    field_rules: dict[str, dict[str, Any]] = field(default_factory=dict)
    version: int = 1
    enabled: bool = True


@dataclass(frozen=True)
class ResolutionInput:
    dataset_key: str
    business_key: str
    candidates_by_source: dict[str, dict[str, Any]]
    active_sources: set[str] | None = None


@dataclass(frozen=True)
class ResolutionOutput:
    dataset_key: str
    business_key: str
    resolved_record: dict[str, Any] | None
    resolved_source_key: str | None
    policy_version: int
    mode: ResolutionMode
    audit: dict[str, Any]


@dataclass(frozen=True)
class FieldConflict:
    field: str
    values_by_source: dict[str, Any]
    comparable_sources: tuple[str, ...]


def parse_freshness_value(value: Any) -> datetime | date | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            if len(text) == 10:
                return date.fromisoformat(text)
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
