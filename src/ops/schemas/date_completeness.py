from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class DateCompletenessRuleDataRange(BaseModel):
    range_type: Literal["business_date", "observed_time", "sync_date", "none"]
    start_date: date | None = None
    end_date: date | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    label: str


class DateCompletenessRuleItem(BaseModel):
    dataset_key: str
    display_name: str
    group_key: str
    group_label: str
    group_order: int
    item_order: int
    domain_key: str
    domain_display_name: str
    target_table: str
    date_axis: str
    bucket_rule: str
    window_mode: str
    input_shape: str
    observed_field: str | None = None
    bucket_window_rule: str | None = None
    bucket_applicability_rule: str
    audit_applicable: bool
    not_applicable_reason: str | None = None
    rule_label: str
    data_range: DateCompletenessRuleDataRange


class DateCompletenessRuleGroup(BaseModel):
    group_key: str
    group_label: str
    items: list[DateCompletenessRuleItem]


class DateCompletenessRuleSummary(BaseModel):
    total: int
    supported: int
    unsupported: int


class DateCompletenessRuleListResponse(BaseModel):
    summary: DateCompletenessRuleSummary
    groups: list[DateCompletenessRuleGroup]


class DateCompletenessRunCreateRequest(BaseModel):
    dataset_key: str
    start_date: date
    end_date: date


class DateCompletenessRunItem(BaseModel):
    id: int
    dataset_key: str
    display_name: str
    target_table: str
    run_mode: str
    run_status: str
    result_status: str | None = None
    start_date: date
    end_date: date
    date_axis: str
    bucket_rule: str
    window_mode: str
    input_shape: str
    observed_field: str
    bucket_window_rule: str
    bucket_applicability_rule: str
    expected_bucket_count: int
    actual_bucket_count: int
    missing_bucket_count: int
    excluded_bucket_count: int
    gap_range_count: int
    current_stage: str | None = None
    operator_message: str | None = None
    technical_message: str | None = None
    requested_by_user_id: int | None = None
    schedule_id: int | None = None
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DateCompletenessRunCreateResponse(BaseModel):
    id: int
    run_status: str
    dataset_key: str
    display_name: str
    start_date: date
    end_date: date
    requested_at: datetime


class DateCompletenessRunListResponse(BaseModel):
    total: int
    items: list[DateCompletenessRunItem]


class DateCompletenessGapItem(BaseModel):
    id: int
    run_id: int
    dataset_key: str
    bucket_kind: str
    range_start: date
    range_end: date
    missing_count: int
    sample_values: list[str]
    created_at: datetime


class DateCompletenessGapListResponse(BaseModel):
    total: int
    items: list[DateCompletenessGapItem]


class DateCompletenessExclusionItem(BaseModel):
    id: int
    run_id: int
    dataset_key: str
    bucket_kind: str
    bucket_value: date
    window_start: date
    window_end: date
    reason_code: str
    reason_message: str
    created_at: datetime


class DateCompletenessExclusionListResponse(BaseModel):
    total: int
    items: list[DateCompletenessExclusionItem]


class DateCompletenessScheduleCreateRequest(BaseModel):
    dataset_key: str
    display_name: str | None = None
    status: str = "active"
    window_mode: str
    start_date: date | None = None
    end_date: date | None = None
    lookback_count: int | None = None
    lookback_unit: str | None = None
    calendar_scope: str = "default_cn_market"
    calendar_exchange: str | None = None
    cron_expr: str
    timezone: str = "Asia/Shanghai"


class DateCompletenessScheduleUpdateRequest(BaseModel):
    display_name: str | None = None
    status: str | None = None
    window_mode: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    lookback_count: int | None = None
    lookback_unit: str | None = None
    calendar_scope: str | None = None
    calendar_exchange: str | None = None
    cron_expr: str | None = None
    timezone: str | None = None


class DateCompletenessScheduleItem(BaseModel):
    id: int
    dataset_key: str
    display_name: str
    status: str
    window_mode: str
    start_date: date | None = None
    end_date: date | None = None
    lookback_count: int | None = None
    lookback_unit: str | None = None
    calendar_scope: str
    calendar_exchange: str | None = None
    cron_expr: str
    timezone: str
    next_run_at: datetime | None = None
    last_run_id: int | None = None
    last_run_status: str | None = None
    last_result_status: str | None = None
    last_run_finished_at: datetime | None = None
    created_by_user_id: int | None = None
    updated_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime


class DateCompletenessScheduleListResponse(BaseModel):
    total: int
    items: list[DateCompletenessScheduleItem]


class DateCompletenessScheduleDeleteResponse(BaseModel):
    id: int
    status: str = "deleted"


class DateCompletenessScheduleTickResponse(BaseModel):
    scheduled: int
    run_ids: list[int]
