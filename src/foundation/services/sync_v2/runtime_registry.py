from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.kernel.contracts.index_series_active_store import IndexSeriesActiveStore
from src.foundation.kernel.contracts.sync_execution_context import SyncExecutionContext
from src.foundation.kernel.contracts.sync_state_store import SyncExecutionResultStore, SyncRunRecorder
from src.foundation.services.sync_v2.registry import get_sync_v2_contract, list_sync_v2_contracts
from src.foundation.services.sync_v2.service import SyncV2Service


@dataclass(frozen=True, slots=True)
class SyncRuntimeSpec:
    dataset_key: str
    job_name: str
    target_table: str


SYNC_SERVICE_REGISTRY: dict[str, SyncRuntimeSpec] = {
    contract.dataset_key: SyncRuntimeSpec(
        dataset_key=contract.dataset_key,
        job_name=contract.job_name,
        target_table=contract.write_spec.target_table,
    )
    for contract in list_sync_v2_contracts()
}

def build_sync_service(
    resource: str,
    session: Session,
    *,
    execution_context: SyncExecutionContext | None = None,
    run_recorder: SyncRunRecorder | None = None,
    execution_result_store: SyncExecutionResultStore | None = None,
    index_series_active_store: IndexSeriesActiveStore | None = None,
):
    contract = get_sync_v2_contract(resource)
    service = SyncV2Service(
        session,
        contract=contract,
        strict_contract=bool(get_settings().sync_v2_strict_contract),
    )
    if execution_context is not None and hasattr(service, "set_execution_context"):
        service.set_execution_context(execution_context)
    if (run_recorder is not None or execution_result_store is not None) and hasattr(service, "set_state_stores"):
        service.set_state_stores(
            run_recorder=run_recorder,
            execution_result_store=execution_result_store,
        )
    if index_series_active_store is not None and hasattr(service, "set_index_series_active_store"):
        service.set_index_series_active_store(index_series_active_store)
    return service
