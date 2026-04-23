from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.kernel.contracts.index_series_active_store import IndexSeriesActiveStore
from src.foundation.kernel.contracts.sync_execution_context import SyncExecutionContext
from src.foundation.kernel.contracts.sync_state_store import SyncJobStateStore, SyncRunLogStore
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

TRADE_DATE_BACKFILL_RESOURCE_KEYS: tuple[str, ...] = (
    "daily_basic",
    "moneyflow",
    "moneyflow_ths",
    "moneyflow_dc",
    "moneyflow_cnt_ths",
    "moneyflow_ind_ths",
    "moneyflow_ind_dc",
    "moneyflow_mkt_dc",
    "margin",
    "top_list",
    "block_trade",
    "limit_list_d",
    "stk_factor_pro",
    "stk_nineturn",
    "suspend_d",
    "dc_member",
    "ths_hot",
    "dc_hot",
    "limit_list_ths",
    "limit_step",
    "limit_cpt_list",
    "kpl_concept_cons",
)


def _validate_trade_date_backfill_resources() -> None:
    duplicate_check = set(TRADE_DATE_BACKFILL_RESOURCE_KEYS)
    if len(duplicate_check) != len(TRADE_DATE_BACKFILL_RESOURCE_KEYS):
        raise RuntimeError("TRADE_DATE_BACKFILL_RESOURCE_KEYS contains duplicates.")
    unknown_resources = sorted(duplicate_check - set(SYNC_SERVICE_REGISTRY))
    if unknown_resources:
        joined = ", ".join(unknown_resources)
        raise RuntimeError(f"TRADE_DATE_BACKFILL_RESOURCE_KEYS contains unknown sync resources: {joined}")


_validate_trade_date_backfill_resources()


def list_trade_date_backfill_resources() -> tuple[str, ...]:
    return TRADE_DATE_BACKFILL_RESOURCE_KEYS


def build_sync_service(
    resource: str,
    session: Session,
    *,
    execution_context: SyncExecutionContext | None = None,
    run_log_store: SyncRunLogStore | None = None,
    job_state_store: SyncJobStateStore | None = None,
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
    if (run_log_store is not None or job_state_store is not None) and hasattr(service, "set_state_stores"):
        service.set_state_stores(
            run_log_store=run_log_store,
            job_state_store=job_state_store,
        )
    if index_series_active_store is not None and hasattr(service, "set_index_series_active_store"):
        service.set_index_series_active_store(index_series_active_store)
    return service

