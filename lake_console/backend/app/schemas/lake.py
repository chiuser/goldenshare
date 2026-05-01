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
