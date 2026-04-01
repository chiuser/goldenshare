from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class DatasetFreshnessItem(BaseModel):
    dataset_key: str
    resource_key: str
    display_name: str
    domain_key: str
    domain_display_name: str
    job_name: str
    target_table: str
    cadence: str
    state_business_date: date | None = None
    earliest_business_date: date | None = None
    observed_business_date: date | None = None
    latest_business_date: date | None = None
    business_date_source: str = "none"
    freshness_note: str | None = None
    latest_success_at: datetime | None = None
    expected_business_date: date | None = None
    lag_days: int | None = None
    freshness_status: str
    recent_failure_message: str | None = None
    recent_failure_summary: str | None = None
    recent_failure_at: datetime | None = None
    primary_execution_spec_key: str | None = None
    full_sync_done: bool


class FreshnessGroup(BaseModel):
    domain_key: str
    domain_display_name: str
    items: list[DatasetFreshnessItem]


class OpsFreshnessSummary(BaseModel):
    total_datasets: int
    fresh_datasets: int
    lagging_datasets: int
    stale_datasets: int
    unknown_datasets: int


class OpsFreshnessResponse(BaseModel):
    summary: OpsFreshnessSummary
    groups: list[FreshnessGroup]
