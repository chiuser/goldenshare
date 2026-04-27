from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.foundation.datasets.registry import get_dataset_definition, list_dataset_definitions
from src.foundation.ingestion.service import DatasetMaintainService
from src.foundation.kernel.contracts.ingestion_run_context import IngestionRunContext
from src.foundation.kernel.contracts.ingestion_state_store import IngestionResultStore, IngestionRunRecorder


@dataclass(frozen=True, slots=True)
class DatasetRuntimeSpec:
    dataset_key: str
    target_table: str


DATASET_RUNTIME_REGISTRY: dict[str, DatasetRuntimeSpec] = {
    definition.dataset_key: DatasetRuntimeSpec(
        dataset_key=definition.dataset_key,
        target_table=definition.storage.target_table,
    )
    for definition in list_dataset_definitions()
}


def build_dataset_maintain_service(
    resource: str,
    session: Session,
    *,
    run_context: IngestionRunContext | None = None,
    run_recorder: IngestionRunRecorder | None = None,
    result_store: IngestionResultStore | None = None,
):
    get_dataset_definition(resource)
    service = DatasetMaintainService(
        session,
        dataset_key=resource,
        run_context=run_context,
        run_recorder=run_recorder,
        result_store=result_store,
    )
    return service
