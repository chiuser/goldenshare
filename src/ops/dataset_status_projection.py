from __future__ import annotations

from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.schemas.freshness import DatasetFreshnessItem


def snapshot_row_to_freshness_item(row: DatasetStatusSnapshot, *, raw_table: str | None = None) -> DatasetFreshnessItem:
    return DatasetFreshnessItem(
        dataset_key=row.dataset_key,
        resource_key=row.resource_key,
        display_name=row.display_name,
        domain_key=row.domain_key,
        domain_display_name=row.domain_display_name,
        target_table=row.target_table,
        raw_table=raw_table,
        cadence=row.cadence,
        earliest_business_date=row.earliest_business_date,
        observed_business_date=row.observed_business_date,
        latest_business_date=row.latest_business_date,
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
    )
