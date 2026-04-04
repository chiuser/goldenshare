from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.operations.specs.job_spec import ParameterSpec


@dataclass(slots=True)
class WorkflowStepSpec:
    step_key: str
    job_key: str
    display_name: str
    depends_on: tuple[str, ...] = ()
    default_params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkflowSpec:
    key: str
    display_name: str
    description: str
    steps: tuple[WorkflowStepSpec, ...]
    supported_params: tuple[ParameterSpec, ...] = ()
    parallel_policy: str = "by_dependency"
    default_schedule_policy: str | None = None
    supports_schedule: bool = False
    supports_manual_run: bool = True
