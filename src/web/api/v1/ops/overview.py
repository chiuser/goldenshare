from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.web.auth.dependencies import require_admin
from src.web.dependencies import get_db_session
from src.web.domain.user import AuthenticatedUser
from src.web.queries.ops import OpsOverviewQueryService
from src.web.schemas.ops.overview import OpsOverviewResponse


router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/overview", response_model=OpsOverviewResponse)
def get_ops_overview(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> OpsOverviewResponse:
    return OpsOverviewQueryService().build_overview(session)
