from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.web.api.v1.health import build_health_response
from src.web.api.v1.router import router as v1_router
from src.web.dependencies import get_db_session
from src.web.schemas.common import HealthResponse


router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse, tags=["platform"])
def health(session: Session = Depends(get_db_session)) -> HealthResponse:
    return build_health_response(session)


router.include_router(v1_router)
