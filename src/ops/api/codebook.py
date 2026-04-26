from __future__ import annotations

from fastapi import APIRouter, Depends

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.foundation.ingestion.codebook import build_ingestion_codebook_payload
from src.ops.schemas.ingestion_codebook import IngestionCodebookResponse


router = APIRouter(prefix="/ops/codebook", tags=["ops"])


@router.get("/ingestion", response_model=IngestionCodebookResponse)
def get_ingestion_codebook(
    _user: AuthenticatedUser = Depends(require_admin),
) -> IngestionCodebookResponse:
    return IngestionCodebookResponse.model_validate(build_ingestion_codebook_payload())
