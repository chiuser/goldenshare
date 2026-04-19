from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.ops.queries.probe_query_service import ProbeQueryService
from src.ops.schemas.probe import (
    CreateProbeRuleRequest,
    DeleteProbeRuleResponse,
    ProbeRuleDetailResponse,
    ProbeRuleListResponse,
    ProbeRunLogListResponse,
    UpdateProbeRuleRequest,
)
from src.ops.services.probe_service import OpsProbeCommandService


router = APIRouter(tags=["ops"])


@router.get("/ops/probes", response_model=ProbeRuleListResponse)
def list_probe_rules(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    status: str | None = Query(None),
    dataset_key: str | None = Query(None),
    source_key: str | None = Query(None),
    schedule_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ProbeRuleListResponse:
    return ProbeQueryService().list_probe_rules(
        session,
        status=status,
        dataset_key=dataset_key,
        source_key=source_key,
        schedule_id=schedule_id,
        limit=limit,
        offset=offset,
    )


@router.post("/ops/probes", response_model=ProbeRuleDetailResponse)
def create_probe_rule(
    body: CreateProbeRuleRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ProbeRuleDetailResponse:
    probe_rule_id = OpsProbeCommandService().create_probe_rule(
        session,
        user=user,
        name=body.name,
        dataset_key=body.dataset_key,
        source_key=body.source_key,
        status=body.status,
        window_start=body.window_start,
        window_end=body.window_end,
        probe_interval_seconds=body.probe_interval_seconds,
        probe_condition_json=body.probe_condition_json,
        on_success_action_json=body.on_success_action_json,
        max_triggers_per_day=body.max_triggers_per_day,
        timezone_name=body.timezone_name,
    )
    return ProbeQueryService().get_probe_rule_detail(session, probe_rule_id)


@router.get("/ops/probes/runs", response_model=ProbeRunLogListResponse)
def list_probe_run_logs(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    probe_rule_id: int | None = Query(None),
    status: str | None = Query(None),
    dataset_key: str | None = Query(None),
    source_key: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> ProbeRunLogListResponse:
    return ProbeQueryService().list_probe_run_logs(
        session,
        probe_rule_id=probe_rule_id,
        status=status,
        dataset_key=dataset_key,
        source_key=source_key,
        limit=limit,
        offset=offset,
    )


@router.get("/ops/probes/{probe_rule_id}", response_model=ProbeRuleDetailResponse)
def get_probe_rule_detail(
    probe_rule_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ProbeRuleDetailResponse:
    return ProbeQueryService().get_probe_rule_detail(session, probe_rule_id)


@router.patch("/ops/probes/{probe_rule_id}", response_model=ProbeRuleDetailResponse)
def update_probe_rule(
    probe_rule_id: int,
    body: UpdateProbeRuleRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ProbeRuleDetailResponse:
    updated_probe_rule_id = OpsProbeCommandService().update_probe_rule(
        session,
        user=user,
        probe_rule_id=probe_rule_id,
        changes=body.model_dump(exclude_unset=True),
    )
    return ProbeQueryService().get_probe_rule_detail(session, updated_probe_rule_id)


@router.post("/ops/probes/{probe_rule_id}/pause", response_model=ProbeRuleDetailResponse)
def pause_probe_rule(
    probe_rule_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ProbeRuleDetailResponse:
    updated_probe_rule_id = OpsProbeCommandService().pause_probe_rule(session, user=user, probe_rule_id=probe_rule_id)
    return ProbeQueryService().get_probe_rule_detail(session, updated_probe_rule_id)


@router.post("/ops/probes/{probe_rule_id}/resume", response_model=ProbeRuleDetailResponse)
def resume_probe_rule(
    probe_rule_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ProbeRuleDetailResponse:
    updated_probe_rule_id = OpsProbeCommandService().resume_probe_rule(session, user=user, probe_rule_id=probe_rule_id)
    return ProbeQueryService().get_probe_rule_detail(session, updated_probe_rule_id)


@router.delete("/ops/probes/{probe_rule_id}", response_model=DeleteProbeRuleResponse)
def delete_probe_rule(
    probe_rule_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> DeleteProbeRuleResponse:
    deleted_probe_rule_id = OpsProbeCommandService().delete_probe_rule(session, user=user, probe_rule_id=probe_rule_id)
    return DeleteProbeRuleResponse(id=deleted_probe_rule_id)


@router.get("/ops/probes/{probe_rule_id}/runs", response_model=ProbeRunLogListResponse)
def list_probe_run_logs_by_rule(
    probe_rule_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> ProbeRunLogListResponse:
    return ProbeQueryService().list_probe_run_logs(
        session,
        probe_rule_id=probe_rule_id,
        status=status,
        limit=limit,
        offset=offset,
    )
