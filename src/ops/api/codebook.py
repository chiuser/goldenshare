from __future__ import annotations

from fastapi import APIRouter, Depends

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.foundation.services.sync_v2.codebook import build_sync_codebook_payload
from src.ops.schemas.sync_codebook import SyncCodebookResponse


router = APIRouter(prefix="/ops/codebook", tags=["ops"])


@router.get("/sync", response_model=SyncCodebookResponse)
def get_sync_codebook(
    _user: AuthenticatedUser = Depends(require_admin),
) -> SyncCodebookResponse:
    return SyncCodebookResponse.model_validate(build_sync_codebook_payload())
