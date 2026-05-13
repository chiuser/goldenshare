from __future__ import annotations

from fastapi import APIRouter

from lake_console.backend.app.schemas import LakeOverviewResponse
from lake_console.backend.app.services.filesystem_scanner import FilesystemScanner
from lake_console.backend.app.settings import load_settings


router = APIRouter(prefix="/api/lake", tags=["lake"])


@router.get("/overview", response_model=LakeOverviewResponse)
def lake_overview() -> LakeOverviewResponse:
    settings = load_settings()
    scanner = FilesystemScanner(settings.lake_root)
    return scanner.overview()
