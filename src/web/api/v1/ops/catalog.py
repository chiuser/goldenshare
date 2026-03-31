from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.web.auth.dependencies import require_admin
from src.web.dependencies import get_db_session
from src.web.domain.user import AuthenticatedUser
from src.web.queries.ops import OpsCatalogQueryService
from src.web.schemas.ops.catalog import OpsCatalogResponse


router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/catalog", response_model=OpsCatalogResponse)
def get_ops_catalog(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> OpsCatalogResponse:
    return OpsCatalogQueryService().build_catalog(session)
