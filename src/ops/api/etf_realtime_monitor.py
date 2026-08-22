from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.ops.schemas.etf_realtime_monitor import (
    EtfRealtimeMonitorActiveEtfListResponse,
    EtfRealtimeMonitorAlertDetailResponse,
    EtfRealtimeMonitorAlertListResponse,
    EtfRealtimeMonitorDefaultRulesResponse,
    EtfRealtimeMonitorMutationResponse,
    EtfRealtimeMonitorPoolListResponse,
    EtfRealtimeMonitorPoolRequest,
    EtfRealtimeMonitorPoolUpdateRequest,
    EtfRealtimeMonitorRuleListResponse,
    EtfRealtimeMonitorRuleRequest,
    EtfRealtimeMonitorSummaryResponse,
)
from src.ops.services.etf_realtime_monitor_alert_query_service import EtfRealtimeMonitorAlertQueryService
from src.ops.services.etf_realtime_monitor_pool_service import EtfRealtimeMonitorPoolService
from src.ops.services.etf_realtime_monitor_rule_service import EtfRealtimeMonitorRuleService


router = APIRouter(prefix="/ops/realtime/etf-monitor", tags=["ops"])


@router.get("/active-etfs", response_model=EtfRealtimeMonitorActiveEtfListResponse)
def list_active_etfs_for_monitor(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    keyword: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=50),
) -> EtfRealtimeMonitorActiveEtfListResponse:
    return EtfRealtimeMonitorPoolService().list_active_etfs(
        session,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


@router.get("/pool", response_model=EtfRealtimeMonitorPoolListResponse)
def list_etf_monitor_pool(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    keyword: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> EtfRealtimeMonitorPoolListResponse:
    return EtfRealtimeMonitorPoolService().list_pool(
        session,
        keyword=keyword,
        enabled=enabled,
        page=page,
        page_size=page_size,
    )


@router.post("/pool", response_model=EtfRealtimeMonitorMutationResponse)
def add_etf_monitor_pool_item(
    body: EtfRealtimeMonitorPoolRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> EtfRealtimeMonitorMutationResponse:
    return EtfRealtimeMonitorPoolService().add_to_pool(
        session,
        ts_code=body.ts_code,
        group_key=body.group_key,
        group_name=body.group_name,
        enabled=body.enabled,
        note=body.note,
        user_id=user.id,
    )


@router.put("/pool/{item_id}", response_model=EtfRealtimeMonitorMutationResponse)
def update_etf_monitor_pool_item(
    item_id: int,
    body: EtfRealtimeMonitorPoolUpdateRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> EtfRealtimeMonitorMutationResponse:
    return EtfRealtimeMonitorPoolService().update_pool_item(
        session,
        item_id=item_id,
        group_key=body.group_key,
        group_name=body.group_name,
        enabled=body.enabled,
        note=body.note,
        user_id=user.id,
    )


@router.delete("/pool/{item_id}", response_model=EtfRealtimeMonitorMutationResponse)
def delete_etf_monitor_pool_item(
    item_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> EtfRealtimeMonitorMutationResponse:
    return EtfRealtimeMonitorPoolService().delete_pool_item(session, item_id=item_id)


@router.get("/rules", response_model=EtfRealtimeMonitorRuleListResponse)
def list_etf_monitor_rules(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    scope_type: str | None = Query(default=None),
    window_minutes: int | None = Query(default=None),
) -> EtfRealtimeMonitorRuleListResponse:
    return EtfRealtimeMonitorRuleService().list_rules(
        session,
        scope_type=scope_type,
        window_minutes=window_minutes,
    )


@router.post("/rules/default-global", response_model=EtfRealtimeMonitorDefaultRulesResponse)
def create_default_global_etf_monitor_rules(
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> EtfRealtimeMonitorDefaultRulesResponse:
    return EtfRealtimeMonitorRuleService().create_default_global_rules(session, user_id=user.id)


@router.post("/rules", response_model=EtfRealtimeMonitorMutationResponse)
def create_etf_monitor_rule(
    body: EtfRealtimeMonitorRuleRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> EtfRealtimeMonitorMutationResponse:
    return EtfRealtimeMonitorRuleService().create_rule(
        session,
        scope_type=body.scope_type,
        scope_key=body.scope_key,
        window_minutes=body.window_minutes,
        observe_ratio=body.observe_ratio,
        alert_ratio=body.alert_ratio,
        strong_ratio=body.strong_ratio,
        cooldown_minutes=body.cooldown_minutes,
        feishu_enabled=body.feishu_enabled,
        enabled=body.enabled,
        user_id=user.id,
    )


@router.put("/rules/{rule_id}", response_model=EtfRealtimeMonitorMutationResponse)
def update_etf_monitor_rule(
    rule_id: int,
    body: EtfRealtimeMonitorRuleRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> EtfRealtimeMonitorMutationResponse:
    return EtfRealtimeMonitorRuleService().update_rule(
        session,
        rule_id=rule_id,
        scope_type=body.scope_type,
        scope_key=body.scope_key,
        window_minutes=body.window_minutes,
        observe_ratio=body.observe_ratio,
        alert_ratio=body.alert_ratio,
        strong_ratio=body.strong_ratio,
        cooldown_minutes=body.cooldown_minutes,
        feishu_enabled=body.feishu_enabled,
        enabled=body.enabled,
        user_id=user.id,
    )


@router.delete("/rules/{rule_id}", response_model=EtfRealtimeMonitorMutationResponse)
def delete_etf_monitor_rule(
    rule_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> EtfRealtimeMonitorMutationResponse:
    return EtfRealtimeMonitorRuleService().delete_rule(session, rule_id=rule_id)


@router.get("/alerts", response_model=EtfRealtimeMonitorAlertListResponse)
def list_etf_monitor_alerts(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    trade_date: date | None = Query(default=None),
    severity: str | None = Query(default=None),
    feishu_status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> EtfRealtimeMonitorAlertListResponse:
    return EtfRealtimeMonitorAlertQueryService().list_alerts(
        session,
        trade_date=trade_date,
        severity=severity,
        feishu_status=feishu_status,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


@router.get("/alerts/{alert_id}", response_model=EtfRealtimeMonitorAlertDetailResponse)
def get_etf_monitor_alert(
    alert_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> EtfRealtimeMonitorAlertDetailResponse:
    return EtfRealtimeMonitorAlertQueryService().get_alert(session, alert_id)


@router.get("/summary", response_model=EtfRealtimeMonitorSummaryResponse)
def get_etf_monitor_summary(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    trade_date: date = Query(...),
) -> EtfRealtimeMonitorSummaryResponse:
    return EtfRealtimeMonitorAlertQueryService().get_summary(session, trade_date=trade_date)
