from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.ops.queries.date_completeness_query_service import DateCompletenessRuleQueryService
from src.ops.queries.date_completeness_run_query_service import DateCompletenessRunQueryService
from src.ops.schemas.date_completeness import (
    DateCompletenessGapListResponse,
    DateCompletenessRunCreateRequest,
    DateCompletenessRunCreateResponse,
    DateCompletenessRunItem,
    DateCompletenessRunListResponse,
    DateCompletenessRuleListResponse,
)
from src.ops.services.date_completeness_run_service import DateCompletenessRunCommandService


router = APIRouter(prefix="/ops/review/date-completeness", tags=["ops"])


@router.get("/rules", response_model=DateCompletenessRuleListResponse)
def list_date_completeness_rules(
    _user: AuthenticatedUser = Depends(require_admin),
) -> DateCompletenessRuleListResponse:
    return DateCompletenessRuleQueryService().list_rules()


@router.post("/runs", response_model=DateCompletenessRunCreateResponse)
def create_date_completeness_run(
    body: DateCompletenessRunCreateRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> DateCompletenessRunCreateResponse:
    run = DateCompletenessRunCommandService().create_manual_run(session, user=user, payload=body)
    return DateCompletenessRunCreateResponse(
        id=run.id,
        run_status=run.run_status,
        dataset_key=run.dataset_key,
        display_name=run.display_name,
        start_date=run.start_date,
        end_date=run.end_date,
        requested_at=run.requested_at,
    )


@router.get("/runs", response_model=DateCompletenessRunListResponse)
def list_date_completeness_runs(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    dataset_key: str | None = Query(None),
    run_status: str | None = Query(None),
    result_status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> DateCompletenessRunListResponse:
    return DateCompletenessRunQueryService().list_runs(
        session,
        dataset_key=dataset_key,
        run_status=run_status,
        result_status=result_status,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=DateCompletenessRunItem)
def get_date_completeness_run(
    run_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> DateCompletenessRunItem:
    return DateCompletenessRunQueryService().get_run(session, run_id)


@router.get("/runs/{run_id}/gaps", response_model=DateCompletenessGapListResponse)
def list_date_completeness_run_gaps(
    run_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> DateCompletenessGapListResponse:
    return DateCompletenessRunQueryService().list_gaps(session, run_id, limit=limit, offset=offset)
