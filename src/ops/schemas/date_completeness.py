from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class DateCompletenessRuleItem(BaseModel):
    dataset_key: str
    display_name: str
    domain_key: str
    domain_display_name: str
    target_table: str
    date_axis: str
    bucket_rule: str
    window_mode: str
    input_shape: str
    observed_field: str | None = None
    audit_applicable: bool
    not_applicable_reason: str | None = None
    rule_label: str


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
    expected_bucket_count: int
    actual_bucket_count: int
    missing_bucket_count: int
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
