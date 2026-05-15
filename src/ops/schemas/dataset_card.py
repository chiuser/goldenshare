from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class DatasetCardItem(BaseModel):
    card_key: str
    dataset_key: str
    detail_dataset_key: str
    resource_key: str
    display_name: str
    group_key: str
    group_label: str
    group_order: int
    item_order: int
    domain_key: str
    domain_display_name: str
    status: str
    freshness_status: str
    delivery_mode: str
    delivery_mode_label: str
    delivery_mode_tone: str
    layer_plan: str
    cadence: str
    cadence_display_name: str
    raw_table: str | None = None
    raw_table_label: str | None = None
    target_table: str | None = None
    latest_business_date: date | None = None
    earliest_business_date: date | None = None
    latest_observed_at: datetime | None = None
    earliest_observed_at: datetime | None = None
    last_sync_date: date | None = None
    latest_success_at: datetime | None = None
    expected_business_date: date | None = None
    lag_days: int | None = None
    freshness_note: str | None = None
    primary_action_key: str | None = None
    active_task_run_status: str | None = None
    active_task_run_started_at: datetime | None = None
    auto_schedule_status: str
    auto_schedule_total: int
    auto_schedule_active: int
    auto_schedule_next_run_at: datetime | None = None
    probe_total: int
    probe_active: int
    std_mapping_configured: bool
    std_cleansing_configured: bool
    resolution_policy_configured: bool


class DatasetCardGroup(BaseModel):
    group_key: str
    group_label: str
    group_order: int
    items: list[DatasetCardItem]


class DatasetCardListResponse(BaseModel):
    total: int
    groups: list[DatasetCardGroup]
