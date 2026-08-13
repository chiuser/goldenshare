from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


@dataclass(frozen=True, slots=True)
class MaintenanceExecutionRequest:
    action_key: str
    params: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class MaintenanceExecutionUnit:
    unit_key: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class MaintenanceExecutionPlan:
    plan_hash: str
    units: tuple[MaintenanceExecutionUnit, ...]
    apply_ready: bool = True
    expected_rows: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MaintenanceExecutionResult:
    rows_fetched: int = 0
    rows_saved: int = 0
    rows_rejected: int = 0
    rejected_reason_counts: Mapping[str, int] = field(default_factory=dict)
    summary_message: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class MaintenanceExecutor(Protocol):
    def plan(self, request: MaintenanceExecutionRequest) -> MaintenanceExecutionPlan: ...

    def execute_unit(self, unit: MaintenanceExecutionUnit) -> MaintenanceExecutionResult: ...
