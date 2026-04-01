from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.operations.specs import get_job_spec, get_workflow_spec, list_dataset_freshness_specs
from src.web.queries.ops.freshness_query_service import OpsFreshnessQueryService
from src.web.schemas.ops.freshness import DatasetFreshnessItem, FreshnessGroup, OpsFreshnessResponse


class DatasetStatusSnapshotService:
    def __init__(self, query_service: OpsFreshnessQueryService | None = None) -> None:
        self.query_service = query_service or OpsFreshnessQueryService()

    def rebuild_all(self, session: Session, *, today: date | None = None, strict: bool = False) -> int:
        try:
            items = self.query_service.build_live_items(session, today=today)
            session.execute(delete(DatasetStatusSnapshot))
            self._upsert_items(session, items, snapshot_date=today or datetime.now(timezone.utc).date())
            session.commit()
            return len(items)
        except SQLAlchemyError:
            session.rollback()
            if strict:
                raise
            return 0

    def refresh_resources(self, session: Session, resource_keys: list[str], *, today: date | None = None, strict: bool = False) -> int:
        target_keys = sorted(set(resource_keys))
        if not target_keys:
            return 0
        try:
            items = self.query_service.build_live_items(session, today=today, resource_keys=target_keys)
            snapshot_date = today or datetime.now(timezone.utc).date()
            self._upsert_items(session, items, snapshot_date=snapshot_date)
            session.commit()
            return len(items)
        except SQLAlchemyError:
            session.rollback()
            if strict:
                raise
            return 0

    def refresh_for_execution(self, session: Session, *, spec_type: str, spec_key: str, today: date | None = None) -> int:
        return self.refresh_resources(session, self._resource_keys_for_spec(spec_type=spec_type, spec_key=spec_key), today=today)

    def read_snapshot(self, session: Session) -> OpsFreshnessResponse | None:
        try:
            rows = list(session.scalars(select(DatasetStatusSnapshot).order_by(DatasetStatusSnapshot.domain_key, DatasetStatusSnapshot.display_name)))
            if not rows:
                return None
            items = [self._to_item(row) for row in rows]
            groups = self.query_service._group_items(items)
            summary = self.query_service._build_summary(items)
            return OpsFreshnessResponse(summary=summary, groups=groups)
        except SQLAlchemyError:
            session.rollback()
            return None

    @staticmethod
    def _to_item(row: DatasetStatusSnapshot) -> DatasetFreshnessItem:
        return DatasetFreshnessItem(
            dataset_key=row.dataset_key,
            resource_key=row.resource_key,
            display_name=row.display_name,
            domain_key=row.domain_key,
            domain_display_name=row.domain_display_name,
            job_name=row.job_name,
            target_table=row.target_table,
            cadence=row.cadence,
            state_business_date=row.state_business_date,
            earliest_business_date=row.earliest_business_date,
            observed_business_date=row.observed_business_date,
            latest_business_date=row.latest_business_date,
            business_date_source=row.business_date_source,
            freshness_note=row.freshness_note,
            latest_success_at=row.latest_success_at,
            last_sync_date=row.last_sync_date,
            expected_business_date=row.expected_business_date,
            lag_days=row.lag_days,
            freshness_status=row.freshness_status,
            recent_failure_message=row.recent_failure_message,
            recent_failure_summary=row.recent_failure_summary,
            recent_failure_at=row.recent_failure_at,
            primary_execution_spec_key=row.primary_execution_spec_key,
            full_sync_done=row.full_sync_done,
        )

    @staticmethod
    def _resource_keys_for_spec(*, spec_type: str, spec_key: str) -> list[str]:
        if spec_type == "job":
            job_spec = get_job_spec(spec_key)
            if job_spec is None or "." not in job_spec.key:
                return []
            return [job_spec.key.split(".", 1)[1]]
        if spec_type == "workflow":
            workflow_spec = get_workflow_spec(spec_key)
            if workflow_spec is None:
                return []
            resource_keys: list[str] = []
            for step in workflow_spec.steps:
                if "." in step.job_key:
                    resource_keys.append(step.job_key.split(".", 1)[1])
            return resource_keys
        return []

    def _upsert_items(self, session: Session, items: list[DatasetFreshnessItem], *, snapshot_date: date) -> None:
        calculated_at = datetime.now(timezone.utc)
        for item in items:
            row = session.get(DatasetStatusSnapshot, item.dataset_key)
            if row is None:
                row = DatasetStatusSnapshot(dataset_key=item.dataset_key)
                session.add(row)
            row.resource_key = item.resource_key
            row.display_name = item.display_name
            row.domain_key = item.domain_key
            row.domain_display_name = item.domain_display_name
            row.job_name = item.job_name
            row.target_table = item.target_table
            row.cadence = item.cadence
            row.state_business_date = item.state_business_date
            row.earliest_business_date = item.earliest_business_date
            row.observed_business_date = item.observed_business_date
            row.latest_business_date = item.latest_business_date
            row.business_date_source = item.business_date_source
            row.freshness_note = item.freshness_note
            row.latest_success_at = item.latest_success_at
            row.last_sync_date = item.last_sync_date
            row.expected_business_date = item.expected_business_date
            row.lag_days = item.lag_days
            row.freshness_status = item.freshness_status
            row.recent_failure_message = item.recent_failure_message
            row.recent_failure_summary = item.recent_failure_summary
            row.recent_failure_at = item.recent_failure_at
            row.primary_execution_spec_key = item.primary_execution_spec_key
            row.full_sync_done = item.full_sync_done
            row.snapshot_date = snapshot_date
            row.last_calculated_at = calculated_at
