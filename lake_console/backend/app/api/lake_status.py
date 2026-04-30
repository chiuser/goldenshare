from __future__ import annotations

from fastapi import APIRouter

from lake_console.backend.app.schemas import LakeStatusResponse
from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.settings import load_settings


router = APIRouter(prefix="/api/lake", tags=["lake"])


@router.get("/status", response_model=LakeStatusResponse)
def lake_status() -> LakeStatusResponse:
    settings = load_settings()
    return LakeRootService(settings.lake_root).get_status()
