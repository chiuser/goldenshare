from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.web.auth.dependencies import require_admin
from src.web.dependencies import get_db_session
from src.web.domain.user import AuthenticatedUser
from src.web.queries.ops import OpsFreshnessQueryService
from src.web.schemas.ops.freshness import OpsFreshnessResponse


router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/freshness", response_model=OpsFreshnessResponse)
def get_ops_freshness(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> OpsFreshnessResponse:
    return OpsFreshnessQueryService().build_freshness(session)
