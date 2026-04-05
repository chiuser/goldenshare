from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.platform.auth.dependencies import require_admin
from src.platform.auth.domain import AuthenticatedUser
from src.platform.dependencies import get_db_session
from src.ops.queries import OpsCatalogQueryService
from src.ops.schemas.catalog import OpsCatalogResponse


router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/catalog", response_model=OpsCatalogResponse)
def get_ops_catalog(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> OpsCatalogResponse:
    return OpsCatalogQueryService().build_catalog(session)
