from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ParameterType = Literal["string", "date", "month", "integer", "boolean", "enum"]
StrategyType = Literal["maintenance_action"]
ExecutorKind = Literal["maintenance"]


@dataclass(slots=True)
class ParameterSpec:
    key: str
    display_name: str
    param_type: ParameterType
    description: str
    required: bool = False
    options: tuple[str, ...] = ()
    multi_value: bool = False


@dataclass(slots=True)
class JobSpec:
    key: str
    display_name: str
    category: str
    description: str
    strategy_type: StrategyType
    executor_kind: ExecutorKind
    target_tables: tuple[str, ...]
    supported_params: tuple[ParameterSpec, ...] = ()
    default_params: dict[str, Any] = field(default_factory=dict)
    supports_manual_run: bool = True
    supports_schedule: bool = False
    supports_retry: bool = True
