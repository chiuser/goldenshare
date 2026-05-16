from __future__ import annotations

from datetime import date, datetime

from src.foundation.datasets.freshness_policies import SNAPSHOT_RUN_TRACE
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.schemas.freshness import DatasetFreshnessItem


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def snapshot_row_to_freshness_item(
    row: DatasetStatusSnapshot,
    *,
    freshness_policy: str = SNAPSHOT_RUN_TRACE,
    raw_table: str | None = None,
) -> DatasetFreshnessItem:
    return DatasetFreshnessItem(
        dataset_key=row.dataset_key,
        resource_key=row.resource_key,
        display_name=row.display_name,
        domain_key=row.domain_key,
        domain_display_name=row.domain_display_name,
        target_table=row.target_table,
        raw_table=raw_table,
        freshness_policy=freshness_policy,
        earliest_business_date=row.earliest_business_date,
        observed_business_date=row.observed_business_date,
        latest_business_date=row.latest_business_date,
        earliest_observed_at=row.earliest_observed_at,
        latest_observed_at=row.latest_observed_at,
        freshness_note=row.freshness_note,
        latest_success_at=row.latest_success_at,
        last_sync_date=row.last_sync_date,
        expected_business_date=row.expected_business_date,
        latest_observed_date=_iso(row.latest_observed_at or row.latest_business_date),
        latest_observed_date_label="最新观测时间" if row.latest_observed_at else ("最新业务日期" if row.latest_business_date else None),
        expected_observed_date=_iso(row.expected_business_date),
        expected_observed_date_label="应完成业务日期" if row.expected_business_date else None,
        last_success_label="最近维护成功时间" if row.latest_success_at else None,
        lag_days=row.lag_days,
        freshness_status=row.freshness_status,
        recent_failure_message=row.recent_failure_message,
        recent_failure_summary=row.recent_failure_summary,
        recent_failure_at=row.recent_failure_at,
        primary_action_key=row.primary_action_key,
    )
