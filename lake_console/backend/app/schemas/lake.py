from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    time: datetime


class LakePathInfo(BaseModel):
    lake_root: str
    exists: bool
    readable: bool
    writable: bool
    initialized: bool
    layout_version: int | None = None


class DiskUsageInfo(BaseModel):
    total_bytes: int
    used_bytes: int
    free_bytes: int
    usage_percent: float


class LakeRiskItem(BaseModel):
    severity: str
    code: str
    message: str
    path: str | None = None
    suggested_action: str | None = None


class LakeLayerSummary(BaseModel):
    layer: str
    layer_name: str
    purpose: str
    source_layer: str | None = None
    layout: str
    path: str
    partition_count: int
    file_count: int
    total_bytes: int
    row_count: int | None = None
    freqs: list[int] = []
    earliest_trade_date: str | None = None
    latest_trade_date: str | None = None
    earliest_trade_month: str | None = None
    latest_trade_month: str | None = None
    latest_modified_at: datetime | None = None
    recommended_usage: str
    risks: list[LakeRiskItem] = []


class LakeStatusResponse(BaseModel):
    path: LakePathInfo
    disk: DiskUsageInfo | None = None
    risks: list[LakeRiskItem] = []


class LakeDatasetSummary(BaseModel):
    dataset_key: str
    display_name: str
    source: str = "tushare"
    category: str | None = None
    group_key: str | None = None
    group_label: str | None = None
    group_order: int | None = None
    description: str | None = None
    dataset_role: str = "raw_dataset"
    storage_root: str | None = None
    layers: list[str]
    layer_summaries: list[LakeLayerSummary] = []
    freqs: list[int]
    supported_freqs: list[int] = []
    raw_freqs: list[int] = []
    derived_freqs: list[int] = []
    partition_count: int
    file_count: int
    total_bytes: int
    row_count: int | None = None
    earliest_trade_date: str | None = None
    latest_trade_date: str | None = None
    earliest_trade_month: str | None = None
    latest_trade_month: str | None = None
    latest_modified_at: datetime | None = None
    primary_layout: str | None = None
    available_layouts: list[str] = []
    write_policy: str | None = None
    update_mode: str | None = None
    health_status: str = "empty"
    risks: list[LakeRiskItem] = []


class LakeDatasetListResponse(BaseModel):
    items: list[LakeDatasetSummary]


class LakeCommandExampleResponse(BaseModel):
    example_key: str
    title: str
    scenario: str
    description: str
    command: str
    argv: list[str]
    prerequisites: list[str] = []
    notes: list[str] = []


class LakeCommandExampleItemResponse(BaseModel):
    item_key: str
    item_type: str
    display_name: str
    description: str | None = None
    examples: list[LakeCommandExampleResponse]


class LakeCommandExampleGroupResponse(BaseModel):
    group_key: str
    group_label: str
    group_order: int
    items: list[LakeCommandExampleItemResponse]


class LakeCommandExamplesResponse(BaseModel):
    groups: list[LakeCommandExampleGroupResponse]


class LakePartitionSummary(BaseModel):
    dataset_key: str
    layer: str
    layout: str
    freq: int | None = None
    trade_date: str | None = None
    trade_month: str | None = None
    bucket: int | None = None
    path: str
    file_count: int
    total_bytes: int
    row_count: int | None = None
    modified_at: datetime | None = None
    risks: list[LakeRiskItem] = []


class LakePartitionListResponse(BaseModel):
    items: list[LakePartitionSummary]


class LakeRecoveryRepositorySummaryResponse(BaseModel):
    connected: bool
    repository_type: str | None = None
    repository_path: str | None = None
    lake_root: str
    snapshot_count: int
    pinned_snapshot_count: int
    latest_snapshot_at: datetime | None = None
    latest_baseline_at: datetime | None = None
    repository_error: str | None = None


class LakeRecoveryCommandHint(BaseModel):
    command_key: str
    title: str
    command: str
    scenario: str


class LakeRecoverySnapshotSummary(BaseModel):
    snapshot_id: str
    manifest_id: str | None = None
    description: str | None = None
    scope: str
    dataset_key: str | None = None
    source_path: str
    display_path: str
    is_baseline: bool = False
    pins: list[str] = []
    retention_reasons: list[str] = []
    total_size: int
    file_count: int
    dir_count: int
    started_at: datetime | None = None
    finished_at: datetime | None = None


class LakeRecoverySnapshotListResponse(BaseModel):
    items: list[LakeRecoverySnapshotSummary]
    total: int
    limit: int
    offset: int


class LakeRecoverySnapshotDetailResponse(LakeRecoverySnapshotSummary):
    repository_path: str | None = None
    host: str | None = None
    user_name: str | None = None
    command_hints: list[LakeRecoveryCommandHint] = []
