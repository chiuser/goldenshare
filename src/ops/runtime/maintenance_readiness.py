from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping, Protocol


@dataclass(frozen=True, slots=True)
class MaintenanceReadinessRequest:
    trade_date: date
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class MaintenanceReadinessResult:
    ready: bool
    reason_code: str
    message: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    config_version: str | None = None
    config_hash: str | None = None
    source_hash: str | None = None
    plan_hash: str | None = None
    content_hash: str | None = None


class MaintenanceReadinessEvaluator(Protocol):
    def evaluate(
        self,
        session: Any,
        *,
        request: MaintenanceReadinessRequest,
    ) -> MaintenanceReadinessResult: ...
