from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping, Protocol


HEAT_READY = "HEAT_READY"
HEAT_NON_TRADING_DAY = "HEAT_NON_TRADING_DAY"
HEAT_UPSTREAM_NOT_READY = "HEAT_UPSTREAM_NOT_READY"
HEAT_SOURCE_NOT_READY = "HEAT_SOURCE_NOT_READY"
HEAT_PREVIEW_FAILED = "HEAT_PREVIEW_FAILED"
HEAT_AUTOMATION_SOURCE_TIMEOUT = "HEAT_AUTOMATION_SOURCE_TIMEOUT"
HEAT_AUTOMATION_ALREADY_ATTEMPTED = "HEAT_AUTOMATION_ALREADY_ATTEMPTED"


@dataclass(frozen=True, slots=True)
class HeatReadinessRequest:
    trade_date: date
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class HeatReadinessResult:
    ready: bool
    reason_code: str
    message: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    config_version: str | None = None
    config_hash: str | None = None
    source_hash: str | None = None
    plan_hash: str | None = None
    content_hash: str | None = None


class HeatReadinessEvaluator(Protocol):
    def evaluate(self, session: Any, *, request: HeatReadinessRequest) -> HeatReadinessResult: ...
