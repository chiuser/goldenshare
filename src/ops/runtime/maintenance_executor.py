from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from src.foundation.kernel.contracts.ingestion_run_context import IngestionRunContext


class MaintenanceInputAuditBlockedError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


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


@dataclass(frozen=True, slots=True)
class MaintenanceTaskRunContext:
    task_run_id: int
    run_context: IngestionRunContext


@dataclass(frozen=True, slots=True)
class MaintenancePlanCheckpoint:
    unit_done: int
    unit_total: int
    units: tuple[MaintenanceExecutionUnit, ...]
    gaps: tuple[Mapping[str, Any], ...]
    metadata: Mapping[str, Any]
    expected_rows: int
    phase: str
    current_object: Mapping[str, Any] = field(default_factory=dict)


class MaintenancePlanTaskRunContext(Protocol):
    task_run_id: int

    def is_cancel_requested(self) -> bool: ...

    def update_phase(
        self,
        *,
        unit_done: int,
        unit_total: int,
        phase: str,
        current_object: Mapping[str, Any],
    ) -> None: ...

    def save_checkpoint(self, checkpoint: MaintenancePlanCheckpoint) -> None: ...


class MaintenanceInputAuditTaskRunContext(Protocol):
    task_run_id: int

    def is_cancel_requested(self) -> bool: ...

    def update_audit_phase(
        self,
        *,
        audit_done: int,
        audit_total: int,
        phase: str,
        current_object: Mapping[str, Any],
    ) -> None: ...


class MaintenanceExecutor(Protocol):
    def plan(self, request: MaintenanceExecutionRequest) -> MaintenanceExecutionPlan: ...

    def execute_unit(self, unit: MaintenanceExecutionUnit) -> MaintenanceExecutionResult: ...


@runtime_checkable
class TaskRunAwareMaintenanceExecutor(MaintenanceExecutor, Protocol):
    def execute_unit_for_task_run(
        self,
        unit: MaintenanceExecutionUnit,
        *,
        context: MaintenanceTaskRunContext,
    ) -> MaintenanceExecutionResult: ...


@runtime_checkable
class TaskRunAwareMaintenancePlanner(MaintenanceExecutor, Protocol):
    def plan_for_task_run(
        self,
        request: MaintenanceExecutionRequest,
        *,
        context: MaintenancePlanTaskRunContext,
    ) -> MaintenanceExecutionPlan: ...


@runtime_checkable
class TaskRunAwareMaintenanceInputAuditor(MaintenanceExecutor, Protocol):
    def audit_for_task_run(
        self,
        request: MaintenanceExecutionRequest,
        *,
        context: MaintenanceInputAuditTaskRunContext,
    ) -> MaintenanceExecutionPlan: ...
