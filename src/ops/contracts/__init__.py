"""Stable Ops contracts for application-composed external tasks."""

from src.ops.contracts.external_task import (
    ExternalTaskDefinition,
    ExternalTaskExecutionOutcome,
    ExternalTaskExecutor,
)

__all__ = ["ExternalTaskDefinition", "ExternalTaskExecutionOutcome", "ExternalTaskExecutor"]
