from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.platform.auth.dependencies import require_admin, require_authenticated
from src.platform.auth.domain import AuthenticatedUser
from src.platform.dependencies import get_db_session
from src.ops.queries import OpsOverviewQueryService
from src.ops.schemas.overview import OpsOverviewResponse, OpsOverviewSummaryResponse


router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/overview", response_model=OpsOverviewResponse)
def get_ops_overview(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> OpsOverviewResponse:
    return OpsOverviewQueryService().build_overview(session)


@router.get("/overview-summary", response_model=OpsOverviewSummaryResponse)
def get_ops_overview_summary(
    _user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
) -> OpsOverviewSummaryResponse:
    return OpsOverviewQueryService().build_overview_summary(session)
