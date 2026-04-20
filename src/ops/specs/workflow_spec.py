from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.ops.specs.job_spec import ParameterSpec


@dataclass(slots=True)
class WorkflowStepSpec:
    step_key: str
    job_key: str
    display_name: str
    dataset_key: str | None = None
    depends_on: tuple[str, ...] = ()
    default_params: dict[str, Any] = field(default_factory=dict)
    failure_policy_override: str | None = None
    params_override: dict[str, Any] = field(default_factory=dict)
    max_retry_per_unit: int = 2


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
    workflow_profile: str = "point_incremental"
    failure_policy_default: str = "fail_fast"
    supports_probe_trigger: bool = False
    resume_supported: bool = True
