from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.foundation.datasets.registry import get_dataset_definition, list_dataset_definitions
from src.foundation.ingestion.service import DatasetMaintainService
from src.foundation.kernel.contracts.sync_execution_context import SyncExecutionContext
from src.foundation.kernel.contracts.sync_state_store import SyncExecutionResultStore, SyncRunRecorder


@dataclass(frozen=True, slots=True)
class DatasetRuntimeSpec:
    dataset_key: str
    job_name: str
    target_table: str


DATASET_RUNTIME_REGISTRY: dict[str, DatasetRuntimeSpec] = {
    definition.dataset_key: DatasetRuntimeSpec(
        dataset_key=definition.dataset_key,
        job_name=definition.dataset_key,
        target_table=definition.storage.target_table,
    )
    for definition in list_dataset_definitions()
}


def build_dataset_maintain_service(
    resource: str,
    session: Session,
    *,
    execution_context: SyncExecutionContext | None = None,
    run_recorder: SyncRunRecorder | None = None,
    execution_result_store: SyncExecutionResultStore | None = None,
):
    get_dataset_definition(resource)
    service = DatasetMaintainService(
        session,
        dataset_key=resource,
        execution_context=execution_context,
        run_recorder=run_recorder,
        execution_result_store=execution_result_store,
    )
    return service
