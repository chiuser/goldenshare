from __future__ import annotations

from fastapi import APIRouter, Query

from lake_console.backend.app.schemas import LakePhysicalAssetListResponse
from lake_console.backend.app.services.filesystem_scanner import FilesystemScanner
from lake_console.backend.app.settings import load_settings


router = APIRouter(prefix="/api/lake/physical-assets", tags=["physical-assets"])


@router.get("", response_model=LakePhysicalAssetListResponse)
def list_physical_assets(
    registered_state: str | None = Query(default=None),
    path_prefix: str | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> LakePhysicalAssetListResponse:
    settings = load_settings()
    scanner = FilesystemScanner(settings.lake_root)
    return LakePhysicalAssetListResponse(
        items=scanner.list_physical_assets(
            registered_state=registered_state,
            path_prefix=path_prefix,
            asset_type=asset_type,
            limit=limit,
            offset=offset,
        ),
        total=scanner.physical_asset_total(
            registered_state=registered_state,
            path_prefix=path_prefix,
            asset_type=asset_type,
        ),
        limit=limit,
        offset=offset,
    )
