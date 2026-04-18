from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.foundation.kernel.contracts.sync_state_store import SyncJobStateStore
from src.ops.models.ops.sync_job_state import SyncJobState
from src.ops.sync_state_store_adapter import OpsSyncJobStateStore
from src.operations.specs import DatasetFreshnessSpec, get_dataset_freshness_spec, list_dataset_freshness_specs
from src.operations.specs.observed_dataset_registry import OBSERVED_DATE_MODEL_REGISTRY
from src.foundation.services.sync.registry import build_sync_service

@dataclass(slots=True)
class ReconciledSyncJobState:
    job_name: str
    resource_key: str
    display_name: str
    target_table: str
    previous_last_success_date: date | None
    observed_last_success_date: date


class SyncJobStateReconciliationService:
    def __init__(self, job_state_store: SyncJobStateStore | None = None) -> None:
        self.job_state_store = job_state_store

    def _resolve_job_state_store(self, session: Session) -> SyncJobStateStore:
        return self.job_state_store or OpsSyncJobStateStore(session)

    def refresh_resource_state_from_observed(self, session: Session, resource_key: str) -> date | None:
        spec = get_dataset_freshness_spec(resource_key)
        if spec is None or spec.observed_date_column is None:
            return None
        observed_last_success_date = self._latest_observed_business_date(session, spec)
        if not isinstance(observed_last_success_date, date):
            return None

        sync_service = build_sync_service(resource_key, session)
        self._resolve_job_state_store(session).mark_success(
            job_name=sync_service.job_name,
            target_table=sync_service.target_table,
            last_success_date=observed_last_success_date,
        )
        session.commit()
        return observed_last_success_date

    def preview_stale_sync_job_states(self, session: Session) -> list[ReconciledSyncJobState]:
        items: list[ReconciledSyncJobState] = []
        for spec in list_dataset_freshness_specs():
            item = self._build_reconciliation_item(session, spec)
            if item is not None:
                items.append(item)
        items.sort(key=lambda item: (item.display_name, item.job_name))
        return items

    def reconcile_stale_sync_job_states(self, session: Session) -> list[ReconciledSyncJobState]:
        items = self.preview_stale_sync_job_states(session)
        store = self._resolve_job_state_store(session)
        for item in items:
            store.reconcile_success_date(
                job_name=item.job_name,
                target_table=item.target_table,
                last_success_date=item.observed_last_success_date,
            )
        session.commit()
        return items

    def _build_reconciliation_item(self, session: Session, spec: DatasetFreshnessSpec) -> ReconciledSyncJobState | None:
        if spec.observed_date_column is None:
            return None
        observed_last_success_date = self._latest_observed_business_date(session, spec)
        if not isinstance(observed_last_success_date, date):
            return None

        state = session.get(SyncJobState, spec.job_name)
        previous_last_success_date = state.last_success_date if state is not None else None
        if previous_last_success_date is not None and observed_last_success_date <= previous_last_success_date:
            return None

        return ReconciledSyncJobState(
            job_name=spec.job_name,
            resource_key=spec.resource_key,
            display_name=spec.display_name,
            target_table=spec.target_table,
            previous_last_success_date=previous_last_success_date,
            observed_last_success_date=observed_last_success_date,
        )

    @staticmethod
    def _latest_observed_business_date(session: Session, spec: DatasetFreshnessSpec) -> date | None:
        if spec.observed_date_column is None:
            return None
        model = OBSERVED_DATE_MODEL_REGISTRY.get(spec.target_table)
        if model is None:
            return None
        column = getattr(model, spec.observed_date_column, None)
        if column is None:
            return None
        try:
            return session.scalar(select(func.max(column)))
        except SQLAlchemyError:
            session.rollback()
            return None
