from __future__ import annotations

from fastapi import APIRouter, Query

from lake_console.backend.app.schemas import LakeDatasetListResponse
from lake_console.backend.app.services.filesystem_scanner import FilesystemScanner
from lake_console.backend.app.settings import load_settings


router = APIRouter(prefix="/api/lake/datasets", tags=["datasets"])


@router.get("", response_model=LakeDatasetListResponse)
def list_datasets(
    dataset_key: str | None = Query(default=None),
    node_key: str | None = Query(default=None),
    layer: str | None = Query(default=None),
    registered_state: str | None = Query(default=None),
) -> LakeDatasetListResponse:
    settings = load_settings()
    scanner = FilesystemScanner(settings.lake_root)
    return LakeDatasetListResponse(
        items=scanner.list_datasets(
            dataset_key=dataset_key,
            node_key=node_key,
            layer=layer,
            registered_state=registered_state,
        )
    )
