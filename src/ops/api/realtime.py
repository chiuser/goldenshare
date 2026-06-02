from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session, get_realtime_state_store
from src.app.exceptions import WebAppError
from src.foundation.realtime import RealtimeStateStore
from src.ops.queries.realtime_feed_health_query_service import (
    RealtimeFeedHealthQueryService,
    RealtimeFeedHealthValidationError,
)
from src.ops.schemas.realtime import OpsRealtimeStockRtDailyHealthResponse, OpsRealtimeStockRtMinHealthResponse
from src.ops.schemas.realtime_config import (
    RealtimeConfigDraftRequest,
    RealtimeConfigObjectDetailResponse,
    RealtimeConfigObjectListResponse,
    RealtimeConfigPublishRequest,
    RealtimeConfigPublishResponse,
    RealtimeConfigRevisionListResponse,
    RealtimeConfigValidateResponse,
)
from src.ops.services.realtime_config_service import RealtimeConfigCommandService


router = APIRouter(prefix="/ops/realtime", tags=["ops"])


@router.get("/config/objects", response_model=RealtimeConfigObjectListResponse)
def list_realtime_config_objects(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> RealtimeConfigObjectListResponse:
    return RealtimeConfigCommandService().list_objects(session)


@router.get("/config/objects/{object_key}", response_model=RealtimeConfigObjectDetailResponse)
def get_realtime_config_object(
    object_key: str,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> RealtimeConfigObjectDetailResponse:
    return RealtimeConfigCommandService().get_object_detail(session, object_key)


@router.post("/config/objects/{object_key}/validate", response_model=RealtimeConfigValidateResponse)
def validate_realtime_config_object(
    object_key: str,
    body: RealtimeConfigDraftRequest,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> RealtimeConfigValidateResponse:
    return RealtimeConfigCommandService().validate_object_config(
        session,
        object_key,
        runtime_config=body.runtime_config,
    )


@router.put("/config/objects/{object_key}", response_model=RealtimeConfigPublishResponse)
def publish_realtime_config_object(
    object_key: str,
    body: RealtimeConfigPublishRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> RealtimeConfigPublishResponse:
    return RealtimeConfigCommandService().publish_object_config(
        session,
        object_key,
        version=body.version,
        runtime_config=body.runtime_config,
        changed_by_user_id=user.id,
    )


@router.get("/config/objects/{object_key}/revisions", response_model=RealtimeConfigRevisionListResponse)
def list_realtime_config_revisions(
    object_key: str,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> RealtimeConfigRevisionListResponse:
    return RealtimeConfigCommandService().list_revisions(session, object_key)


@router.get("/stock-rt-daily/health", response_model=OpsRealtimeStockRtDailyHealthResponse)
def get_stock_rt_daily_health(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    store: RealtimeStateStore = Depends(get_realtime_state_store),
) -> OpsRealtimeStockRtDailyHealthResponse:
    return RealtimeFeedHealthQueryService(store=store).build_stock_rt_daily_health(session)


@router.get("/stock-rt-min/health", response_model=OpsRealtimeStockRtMinHealthResponse)
def get_stock_rt_min_health(
    freq: str | None = None,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    store: RealtimeStateStore = Depends(get_realtime_state_store),
) -> OpsRealtimeStockRtMinHealthResponse:
    try:
        return RealtimeFeedHealthQueryService(store=store).build_stock_rt_min_health(session, freq=freq)
    except RealtimeFeedHealthValidationError as exc:
        raise WebAppError(status_code=400, code=exc.code, message=exc.message) from exc
