from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from lake_console.backend.app.schemas import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="goldenshare-lake-console", time=datetime.now(timezone.utc))
