from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, Field


class EtfRealtimeMonitorActiveEtfItem(BaseModel):
    ts_code: str
    csname: str | None = None
    extname: str | None = None
    cname: str | None = None
    exchange: str | None = None
    etf_type: str | None = None
    list_date: date | None = None
    list_status: str | None = None
    latest_fund_daily_date: date | None = None
    size_trade_date: date | None = None
    total_share_wan: Decimal | None = None
    total_size_wan: Decimal | None = None
    in_monitor_pool: bool


class EtfRealtimeMonitorActiveEtfListResponse(BaseModel):
    items: list[EtfRealtimeMonitorActiveEtfItem]
    page: int
    page_size: int
    total: int


class EtfRealtimeMonitorPoolItem(BaseModel):
    id: int
    ts_code: str
    etf_name: str | None = None
    group_key: str
    group_name: str
    enabled: bool
    display_order: int
    note: str | None = None
    has_etf_rule_override: bool
    latest_alert_at: datetime | None = None
    latest_alert_severity: str | None = None
    size_trade_date: date | None = None
    total_share_wan: Decimal | None = None
    total_size_wan: Decimal | None = None
    created_at: datetime
    updated_at: datetime


class EtfRealtimeMonitorPoolListResponse(BaseModel):
    items: list[EtfRealtimeMonitorPoolItem]
    page: int
    page_size: int
    total: int


class EtfRealtimeMonitorPoolRequest(BaseModel):
    ts_code: str
    group_key: str
    group_name: str
    enabled: bool = True
    display_order: int = 0
    note: str | None = None


class EtfRealtimeMonitorPoolUpdateRequest(BaseModel):
    group_key: str
    group_name: str
    enabled: bool
    display_order: int = 0
    note: str | None = None


class EtfRealtimeMonitorMutationResponse(BaseModel):
    id: int
    ts_code: str


class EtfRealtimeMonitorRuleItem(BaseModel):
    id: int
    scope_type: str
    scope_key: str
    scope_display_name: str | None = None
    window_minutes: int
    observe_ratio: Decimal
    alert_ratio: Decimal
    strong_ratio: Decimal
    cooldown_minutes: int
    feishu_enabled: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime


class EtfRealtimeMonitorRuleListResponse(BaseModel):
    items: list[EtfRealtimeMonitorRuleItem]
    total: int


class EtfRealtimeMonitorRuleRequest(BaseModel):
    scope_type: str
    scope_key: str
    window_minutes: int
    observe_ratio: Decimal = Field(gt=0)
    alert_ratio: Decimal = Field(gt=0)
    strong_ratio: Decimal = Field(gt=0)
    cooldown_minutes: int = Field(gt=0)
    feishu_enabled: bool = True
    enabled: bool = True


class EtfRealtimeMonitorAlertItem(BaseModel):
    id: int
    trade_date: date
    triggered_at: datetime
    bucket_end_time: time
    window_minutes: int
    ts_code: str
    etf_name: str | None = None
    group_key: str
    group_name: str
    severity: str
    current_amount_yuan: Decimal
    baseline_amount_yuan: Decimal
    ratio: Decimal
    feishu_status: str


class EtfRealtimeMonitorAlertListResponse(BaseModel):
    items: list[EtfRealtimeMonitorAlertItem]
    page: int
    page_size: int
    total: int


class EtfRealtimeMonitorAlertDetailResponse(EtfRealtimeMonitorAlertItem):
    rule_id: int | None = None
    baseline_trade_dates_json: list
    cooldown_key: str
    feishu_message_id: str | None = None
    feishu_error: str | None = None
    notified_at: datetime | None = None
    created_at: datetime


class EtfRealtimeMonitorSummaryResponse(BaseModel):
    monitor_total: int
    monitor_enabled: int
    observe_count: int
    alert_count: int
    strong_count: int
    feishu_success_count: int
    feishu_failed_count: int
    latest_archive_date: date | None = None


class EtfRealtimeMonitorDefaultRulesResponse(BaseModel):
    created: int
    skipped: int
