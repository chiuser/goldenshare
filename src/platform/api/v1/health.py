from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.platform.dependencies import get_db_session
from src.platform.exceptions import WebAppError
from src.platform.schemas.common import HealthResponse
from src.platform.web.settings import get_web_settings


router = APIRouter(tags=["platform"])


def build_health_response(session: Session) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - exercised via API tests
        raise WebAppError(status_code=503, code="service_unavailable", message="Database unavailable") from exc
    settings = get_web_settings()
    return HealthResponse(
        status="ok",
        service="goldenshare-web",
        env=settings.app_env,
    )


@router.get("/health", response_model=HealthResponse)
def health(session: Session = Depends(get_db_session)) -> HealthResponse:
    return build_health_response(session)
