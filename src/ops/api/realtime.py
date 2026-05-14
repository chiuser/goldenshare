from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session, get_realtime_state_store
from src.foundation.realtime import RealtimeStateStore
from src.ops.queries.realtime_feed_health_query_service import RealtimeFeedHealthQueryService
from src.ops.schemas.realtime import OpsRealtimeStockRtDailyHealthResponse


router = APIRouter(prefix="/ops/realtime", tags=["ops"])


@router.get("/stock-rt-daily/health", response_model=OpsRealtimeStockRtDailyHealthResponse)
def get_stock_rt_daily_health(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    store: RealtimeStateStore = Depends(get_realtime_state_store),
) -> OpsRealtimeStockRtDailyHealthResponse:
    return RealtimeFeedHealthQueryService(store=store).build_stock_rt_daily_health(session)
