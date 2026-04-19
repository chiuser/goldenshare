from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.ops.queries import OpsFreshnessQueryService
from src.ops.schemas.freshness import OpsFreshnessResponse


router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/freshness", response_model=OpsFreshnessResponse)
def get_ops_freshness(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> OpsFreshnessResponse:
    return OpsFreshnessQueryService().build_freshness(session)
