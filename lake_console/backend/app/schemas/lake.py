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


class LakeStatusResponse(BaseModel):
    path: LakePathInfo
    disk: DiskUsageInfo | None = None
    risks: list[LakeRiskItem] = []


class LakeDatasetSummary(BaseModel):
    dataset_key: str
    display_name: str
    layers: list[str]
    freqs: list[int]
    partition_count: int
    file_count: int
    total_bytes: int
    earliest_trade_date: str | None = None
    latest_trade_date: str | None = None
    latest_modified_at: datetime | None = None
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
