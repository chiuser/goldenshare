from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class DatasetPipelineModeItem(BaseModel):
    dataset_key: str
    display_name: str
    domain_key: str
    domain_display_name: str
    mode: str
    source_scope: str
    layer_plan: str
    raw_table: str | None
    std_table_hint: str | None
    serving_table: str | None
    freshness_status: str
    latest_business_date: date | None
    std_mapping_configured: bool
    std_cleansing_configured: bool
    resolution_policy_configured: bool


class DatasetPipelineModeListResponse(BaseModel):
    total: int
    items: list[DatasetPipelineModeItem]
