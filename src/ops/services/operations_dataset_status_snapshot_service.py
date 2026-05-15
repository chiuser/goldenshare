from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.foundation.datasets.registry import get_dataset_definition_by_action_key
from src.ops.dataset_definition_projection import (
    get_dataset_freshness_projection,
)
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.queries.freshness_query_service import OpsFreshnessQueryService
from src.ops.schemas.freshness import DatasetFreshnessItem, OpsFreshnessResponse
from src.ops.dataset_status_projection import snapshot_row_to_freshness_item
from src.ops.action_catalog import get_workflow_definition


class DatasetStatusSnapshotService:
    def __init__(self, query_service: OpsFreshnessQueryService | None = None) -> None:
        self.query_service = query_service or OpsFreshnessQueryService()

    def rebuild_all(self, session: Session, *, today: date | None = None, strict: bool = False) -> int:
        try:
            items = self.query_service.build_live_items(session, today=today)
            session.execute(delete(DatasetStatusSnapshot))
            snapshot_date = OpsFreshnessQueryService._business_reference_date(today)
            self._upsert_items(session, items, snapshot_date=snapshot_date)
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
            snapshot_date = OpsFreshnessQueryService._business_reference_date(today)
            self._upsert_items(session, items, snapshot_date=snapshot_date)
            session.commit()
            return len(items)
        except SQLAlchemyError:
            session.rollback()
            if strict:
                raise
            return 0

    def refresh_for_target(
        self,
        session: Session,
        *,
        target_type: str,
        target_key: str,
        today: date | None = None,
        strict: bool = False,
    ) -> int:
        return self.refresh_resources(
            session,
            self._resource_keys_for_target(target_type=target_type, target_key=target_key),
            today=today,
            strict=strict,
        )

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
        projection = get_dataset_freshness_projection(row.resource_key)
        return snapshot_row_to_freshness_item(row, raw_table=projection.raw_table if projection is not None else None)

    @staticmethod
    def _resource_keys_for_target(*, target_type: str, target_key: str) -> list[str]:
        if target_type == "dataset_action":
            try:
                definition, _action = get_dataset_definition_by_action_key(target_key)
            except KeyError:
                return []
            resource_key = definition.dataset_key
            if get_dataset_freshness_projection(resource_key) is None:
                return []
            return [resource_key]
        if target_type == "maintenance_action":
            return []
        if target_type == "workflow":
            workflow = get_workflow_definition(target_key)
            if workflow is None:
                return []
            resource_keys: list[str] = []
            for step in workflow.steps:
                try:
                    definition, _action = get_dataset_definition_by_action_key(step.action_key)
                except KeyError:
                    continue
                if get_dataset_freshness_projection(definition.dataset_key) is not None:
                    resource_keys.append(definition.dataset_key)
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
            row.target_table = item.target_table
            row.cadence = item.cadence
            row.earliest_business_date = item.earliest_business_date
            row.observed_business_date = item.observed_business_date
            row.latest_business_date = item.latest_business_date
            row.earliest_observed_at = item.earliest_observed_at
            row.latest_observed_at = item.latest_observed_at
            row.freshness_note = item.freshness_note
            row.latest_success_at = item.latest_success_at
            row.last_sync_date = item.last_sync_date
            row.expected_business_date = item.expected_business_date
            row.lag_days = item.lag_days
            row.freshness_status = item.freshness_status
            row.recent_failure_message = item.recent_failure_message
            row.recent_failure_summary = item.recent_failure_summary
            row.recent_failure_at = item.recent_failure_at
            row.primary_action_key = item.primary_action_key
            row.snapshot_date = snapshot_date
            row.last_calculated_at = calculated_at
