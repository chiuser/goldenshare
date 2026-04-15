from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CreateProbeRuleRequest(BaseModel):
    name: str
    dataset_key: str
    source_key: str | None = None
    status: str = "active"
    window_start: str | None = None
    window_end: str | None = None
    probe_interval_seconds: int = 300
    probe_condition_json: dict = {}
    on_success_action_json: dict = {}
    max_triggers_per_day: int = 1
    timezone_name: str = "Asia/Shanghai"


class UpdateProbeRuleRequest(BaseModel):
    name: str | None = None
    dataset_key: str | None = None
    source_key: str | None = None
    status: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    probe_interval_seconds: int | None = None
    probe_condition_json: dict | None = None
    on_success_action_json: dict | None = None
    max_triggers_per_day: int | None = None
    timezone_name: str | None = None


class ProbeRuleListItem(BaseModel):
    id: int
    schedule_id: int | None = None
    name: str
    dataset_key: str
    source_key: str | None = None
    status: str
    window_start: str | None = None
    window_end: str | None = None
    probe_interval_seconds: int
    probe_condition_json: dict
    on_success_action_json: dict
    max_triggers_per_day: int
    timezone_name: str
    last_probed_at: datetime | None = None
    last_triggered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProbeRuleDetailResponse(ProbeRuleListItem):
    created_by_username: str | None = None
    updated_by_username: str | None = None


class ProbeRuleListResponse(BaseModel):
    items: list[ProbeRuleListItem]
    total: int


class DeleteProbeRuleResponse(BaseModel):
    id: int
    status: str = "deleted"


class ProbeRunLogItem(BaseModel):
    id: int
    probe_rule_id: int
    probe_rule_name: str | None = None
    dataset_key: str | None = None
    source_key: str | None = None
    status: str
    condition_matched: bool
    message: str | None = None
    payload_json: dict
    probed_at: datetime
    triggered_execution_id: int | None = None
    duration_ms: int | None = None


class ProbeRunLogListResponse(BaseModel):
    items: list[ProbeRunLogItem]
    total: int
