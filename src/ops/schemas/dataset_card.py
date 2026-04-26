from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class DatasetCardStageStatus(BaseModel):
    stage: str
    stage_label: str
    table_name: str | None = None
    source_key: str | None = None
    status: str
    rows_in: int | None = None
    rows_out: int | None = None
    error_count: int | None = None
    lag_seconds: int | None = None
    message: str | None = None
    calculated_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None


class DatasetCardSourceStatus(BaseModel):
    source_key: str
    table_name: str | None = None
    status: str
    calculated_at: datetime | None = None


class DatasetCardItem(BaseModel):
    card_key: str
    dataset_key: str
    detail_dataset_key: str
    resource_key: str
    display_name: str
    domain_key: str
    domain_display_name: str
    status: str
    freshness_status: str
    mode: str
    mode_label: str
    mode_tone: str
    layer_plan: str
    cadence: str
    raw_table: str | None = None
    raw_table_label: str | None = None
    target_table: str | None = None
    latest_business_date: date | None = None
    earliest_business_date: date | None = None
    last_sync_date: date | None = None
    latest_success_at: datetime | None = None
    expected_business_date: date | None = None
    lag_days: int | None = None
    freshness_note: str | None = None
    primary_action_key: str | None = None
    active_execution_status: str | None = None
    active_execution_started_at: datetime | None = None
    auto_schedule_status: str
    auto_schedule_total: int
    auto_schedule_active: int
    auto_schedule_next_run_at: datetime | None = None
    probe_total: int
    probe_active: int
    std_mapping_configured: bool
    std_cleansing_configured: bool
    resolution_policy_configured: bool
    status_updated_at: datetime | None = None
    stage_statuses: list[DatasetCardStageStatus]
    raw_sources: list[DatasetCardSourceStatus]


class DatasetCardGroup(BaseModel):
    domain_key: str
    domain_display_name: str
    items: list[DatasetCardItem]


class DatasetCardListResponse(BaseModel):
    total: int
    groups: list[DatasetCardGroup]
