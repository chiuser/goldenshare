from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.ops.queries.probe_query_service import ProbeQueryService
from src.ops.schemas.probe import (
    ProbeRuleDetailResponse,
    ProbeRuleListResponse,
    ProbeRunLogListResponse,
)


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


@router.get("/ops/probes/runs", response_model=ProbeRunLogListResponse)
def list_probe_run_logs(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    probe_rule_id: int | None = Query(None),
    schedule_id: int | None = Query(None),
    status: str | None = Query(None),
    dataset_key: str | None = Query(None),
    source_key: str | None = Query(None),
    condition_matched: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> ProbeRunLogListResponse:
    return ProbeQueryService().list_probe_run_logs(
        session,
        probe_rule_id=probe_rule_id,
        schedule_id=schedule_id,
        status=status,
        dataset_key=dataset_key,
        source_key=source_key,
        condition_matched=condition_matched,
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
