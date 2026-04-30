from __future__ import annotations

from fastapi import APIRouter, Query

from lake_console.backend.app.schemas import LakePartitionListResponse
from lake_console.backend.app.services.filesystem_scanner import FilesystemScanner
from lake_console.backend.app.settings import load_settings


router = APIRouter(prefix="/api/partitions", tags=["partitions"])


@router.get("", response_model=LakePartitionListResponse)
def list_partitions(
    dataset_key: str | None = Query(default=None),
    layer: str | None = Query(default=None),
    layout: str | None = Query(default=None),
    freq: int | None = Query(default=None),
    trade_date_from: str | None = Query(default=None),
    trade_date_to: str | None = Query(default=None),
    trade_month: str | None = Query(default=None),
    bucket: int | None = Query(default=None),
) -> LakePartitionListResponse:
    settings = load_settings()
    scanner = FilesystemScanner(settings.lake_root)
    return LakePartitionListResponse(
        items=scanner.list_partitions(
            dataset_key=dataset_key,
            layer=layer,
            layout=layout,
            freq=freq,
            trade_date_from=trade_date_from,
            trade_date_to=trade_date_to,
            trade_month=trade_month,
            bucket=bucket,
        )
    )
