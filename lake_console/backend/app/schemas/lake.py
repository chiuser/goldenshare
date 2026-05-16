from __future__ import annotations

from typing import Any
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


class LakeNodeSummary(BaseModel):
    dataset_key: str
    node_key: str
    node_name: str
    layer: str
    layer_name: str
    path: str
    scan_profile: str
    asset_role: str
    asset_role_label: str
    source_node_keys: list[str] = []
    partition_dimensions: list[str] = []
    partition_count: int
    file_count: int
    total_bytes: int
    row_count: int | None = None
    freqs: list[int] = []
    earliest_trade_date: str | None = None
    latest_trade_date: str | None = None
    earliest_event_date: str | None = None
    latest_event_date: str | None = None
    earliest_trade_month: str | None = None
    latest_trade_month: str | None = None
    latest_modified_at: datetime | None = None
    coverage_label: str
    recommended_usage: str
    registered_state: str
    risks: list[LakeRiskItem] = []


class LakeStatusResponse(BaseModel):
    path: LakePathInfo
    disk: DiskUsageInfo | None = None
    risks: list[LakeRiskItem] = []


class LakeDatasetSummary(BaseModel):
    dataset_key: str
    display_name: str
    source: str = "tushare"
    source_label: str = "Tushare"
    category: str | None = None
    group_key: str | None = None
    group_label: str | None = None
    group_order: int | None = None
    description: str | None = None
    dataset_role: str = "raw_dataset"
    dataset_role_label: str = "数据集"
    node_summaries: list[LakeNodeSummary] = []
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
    earliest_event_date: str | None = None
    latest_event_date: str | None = None
    earliest_trade_month: str | None = None
    latest_trade_month: str | None = None
    latest_modified_at: datetime | None = None
    coverage_label: str
    health_status: str = "empty"
    health_label: str = "未落盘"
    risks: list[LakeRiskItem] = []
    sort_order: int = 0


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
    node_key: str
    partition_values: dict[str, Any] = {}
    partition_locator: str
    partition_label: str
    path: str
    file_count: int
    total_bytes: int
    row_count: int | None = None
    modified_at: datetime | None = None
    risks: list[LakeRiskItem] = []


class LakePartitionListResponse(BaseModel):
    items: list[LakePartitionSummary]


class LakePhysicalAssetSummary(BaseModel):
    path: str
    asset_type: str
    registered_state: str
    dataset_key: str | None = None
    node_key: str | None = None
    display_name: str
    total_bytes: int
    file_count: int
    dir_count: int
    latest_modified_at: datetime | None = None
    risk_level: str = "none"
    risk_label: str = "正常"


class LakePhysicalAssetListResponse(BaseModel):
    items: list[LakePhysicalAssetSummary]
    total: int
    limit: int
    offset: int


class LakeOverviewMetric(BaseModel):
    key: str
    label: str
    value: str
    hint: str
    tone: str = "subtle"
    sort_order: int = 0


class LakeOverviewLayerGroup(BaseModel):
    layer: str
    layer_name: str
    dataset_count: int
    node_count: int
    partition_count: int
    file_count: int
    total_bytes: int
    coverage_label: str
    freqs: list[int] = []
    sample_path: str | None = None
    sort_order: int = 0


class LakeOverviewSyncMethodGroup(BaseModel):
    key: str
    label: str
    count: int
    sort_order: int = 0


class LakeOverviewDatasetRow(BaseModel):
    dataset_key: str
    display_name: str
    group_label: str
    source_label: str
    node_count: int
    partition_count: int
    file_count: int
    total_bytes: int
    coverage_label: str
    health_status: str
    health_label: str
    primary_path: str | None = None
    sort_order: int = 0


class LakeOverviewResponse(BaseModel):
    generated_at: datetime
    lake_root: str
    summary_metrics: list[LakeOverviewMetric]
    layer_groups: list[LakeOverviewLayerGroup]
    sync_method_groups: list[LakeOverviewSyncMethodGroup]
    dataset_rows: list[LakeOverviewDatasetRow]
    physical_assets: list[LakePhysicalAssetSummary]
    risks: list[LakeRiskItem] = []


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
