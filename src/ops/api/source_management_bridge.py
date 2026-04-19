from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.ops.queries.source_management_bridge_query_service import SourceManagementBridgeQueryService
from src.ops.schemas.source_management_bridge import SourceManagementBridgeResponse


router = APIRouter(tags=["ops"])


@router.get("/ops/source-management/bridge", response_model=SourceManagementBridgeResponse)
def get_source_management_bridge(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    probe_limit: int = Query(20, ge=1, le=200),
    release_limit: int = Query(20, ge=1, le=200),
    std_rule_limit: int = Query(200, ge=1, le=500),
    layer_limit: int = Query(500, ge=1, le=5000),
) -> SourceManagementBridgeResponse:
    return SourceManagementBridgeQueryService().get_bridge_payload(
        session,
        probe_limit=probe_limit,
        release_limit=release_limit,
        std_rule_limit=std_rule_limit,
        layer_limit=layer_limit,
    )
