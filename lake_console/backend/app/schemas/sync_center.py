from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SyncProfileDatasetSummary(BaseModel):
    dataset_key: str


class SyncProfileSummary(BaseModel):
    profile_key: str
    display_name: str
    description: str
    profile_status: str
    default_lookback_days: int | None = None
    requires_kopia_backup: bool
    stale_after_seconds: int
    disabled_reason: str | None = None
    datasets: list[SyncProfileDatasetSummary] = Field(default_factory=list)


class SyncProfileListResponse(BaseModel):
    items: list[SyncProfileSummary]


class SyncRecommendationPlanHint(BaseModel):
    profile_key: str
    dataset_keys: list[str]
    target_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class SyncRecommendationItem(BaseModel):
    dataset_key: str
    display_name: str
    source: str
    status: str
    local_latest_trade_date: str | None = None
    expected_latest_trade_date: str | None = None
    suggested_start_date: str | None = None
    suggested_end_date: str | None = None
    lag_anchor_count: int = 0
    lag_calendar_days: int = 0
    reason: str
    plan_hint: SyncRecommendationPlanHint | None = None


class SyncRecommendationResponse(BaseModel):
    generated_at: str
    profile_key: str
    cutoff_time: str
    expected_reference_date: str | None = None
    aggregate_plan_hint: SyncRecommendationPlanHint | None = None
    items: list[SyncRecommendationItem]


class SyncLockResponse(BaseModel):
    status: str
    run_id: str | None = None
    profile_key: str | None = None
    owner_pid: int | None = None
    owner_host: str | None = None
    acquired_at: str | None = None
    last_heartbeat_at: str | None = None
    stale_after_seconds: int
    can_release_stale: bool = False


class SyncPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    dataset_keys: list[str] | None = None
    freqs: list[int] | None = None
    scope: str | None = None
    mode: str | None = None
    include_backup_plan: bool = True


class SyncPlanResponse(BaseModel):
    plan_token: str
    plan_token_expires_at: str
    profile_key: str
    profile: dict[str, Any]
    request: dict[str, Any]
    normalized_parameters: dict[str, Any]
    lock: dict[str, Any]
    dataset_plans: list[dict[str, Any]]
    pipeline_stages: list[dict[str, Any]] = Field(default_factory=list)
    affected_trade_dates: list[str] = Field(default_factory=list)
    affected_months: list[str] = Field(default_factory=list)
    backup_plan: dict[str, Any]
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class SyncRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_token: str
    confirmed_backup_required: bool = True
    confirmed_no_sql: bool = True


class SyncRunContinueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_continue: bool = True
    operator: str | None = None


class SyncRunAbortRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class SyncRunResponse(BaseModel):
    run_id: str
    profile_key: str
    status: str
    run_status: str | None = None
    lock: dict[str, Any]
    detail_url: str
    events_url: str


class SyncCurrentRunResponse(BaseModel):
    active_run_id: str | None = None
    status: str
    profile_key: str | None = None
    started_at: str | None = None
    updated_at: str
    progress_summary: str
    current_dataset_key: str | None = None
    current_partition: str | None = None
    current_stage_key: str | None = None
    requires_confirmation: bool = False
    next_action: dict[str, Any] | None = None


class SyncRunDetailResponse(BaseModel):
    run_id: str
    profile_key: str
    plan_token: str
    status: str
    run_status: str
    started_at: str
    finished_at: str | None = None
    backup: dict[str, Any] | None = None
    pipeline_stages: list[dict[str, Any]] = Field(default_factory=list)
    current_stage_key: str | None = None
    requires_confirmation: bool = False
    next_action: dict[str, Any] | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    dataset_results: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class SyncRunEventListResponse(BaseModel):
    items: list[dict[str, Any]]
    next_cursor: int


class SyncReleaseStaleLockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_stale: bool
    reason: str = Field(min_length=1)


class SyncReleaseStaleLockResponse(BaseModel):
    released: bool
    released_lock: dict[str, Any]
