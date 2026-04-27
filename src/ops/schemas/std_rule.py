from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CreateStdMappingRuleRequest(BaseModel):
    dataset_key: str
    source_key: str
    src_field: str
    std_field: str
    src_type: str | None = None
    std_type: str | None = None
    transform_fn: str | None = None
    lineage_preserved: bool = True
    status: str = "active"
    rule_set_version: int = 1


class UpdateStdMappingRuleRequest(BaseModel):
    src_type: str | None = None
    std_type: str | None = None
    transform_fn: str | None = None
    lineage_preserved: bool | None = None
    status: str | None = None
    rule_set_version: int | None = None


class StdMappingRuleItem(BaseModel):
    id: int
    dataset_key: str
    dataset_display_name: str
    source_key: str
    source_display_name: str
    src_field: str
    std_field: str
    src_type: str | None = None
    std_type: str | None = None
    transform_fn: str | None = None
    lineage_preserved: bool
    status: str
    rule_set_version: int
    created_at: datetime
    updated_at: datetime


class StdMappingRuleListResponse(BaseModel):
    items: list[StdMappingRuleItem]
    total: int


class CreateStdCleansingRuleRequest(BaseModel):
    dataset_key: str
    source_key: str
    rule_type: str
    target_fields_json: list[str] = []
    condition_expr: str | None = None
    action: str
    status: str = "active"
    rule_set_version: int = 1


class UpdateStdCleansingRuleRequest(BaseModel):
    rule_type: str | None = None
    target_fields_json: list[str] | None = None
    condition_expr: str | None = None
    action: str | None = None
    status: str | None = None
    rule_set_version: int | None = None


class StdCleansingRuleItem(BaseModel):
    id: int
    dataset_key: str
    dataset_display_name: str
    source_key: str
    source_display_name: str
    rule_type: str
    target_fields_json: list[str]
    condition_expr: str | None = None
    action: str
    status: str
    rule_set_version: int
    created_at: datetime
    updated_at: datetime


class StdCleansingRuleListResponse(BaseModel):
    items: list[StdCleansingRuleItem]
    total: int
