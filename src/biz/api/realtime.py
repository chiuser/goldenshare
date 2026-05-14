from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session, get_realtime_state_store
from src.app.exceptions import WebAppError
from src.biz.queries.realtime_stock_rt_daily_query_service import (
    RealtimeQueryValidationError,
    RealtimeStockRtDailyQueryService,
)
from src.biz.schemas.realtime import StockRtDailySnapshotResponse
from src.foundation.realtime import RealtimeFeedUnavailable, RealtimeStateStore, RealtimeStateStoreUnavailable


router = APIRouter(prefix="/realtime", tags=["realtime"])


@router.get("/stock-rt-daily", response_model=StockRtDailySnapshotResponse)
def get_stock_rt_daily_snapshot(
    ts_codes: str | None = Query(default=None),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
    store: RealtimeStateStore = Depends(get_realtime_state_store),
) -> StockRtDailySnapshotResponse:
    try:
        return RealtimeStockRtDailyQueryService(store=store).build_snapshot(session, ts_codes=ts_codes)
    except RealtimeQueryValidationError as exc:
        raise WebAppError(status_code=400, code=exc.code, message=exc.message) from exc
    except RealtimeFeedUnavailable as exc:
        raise WebAppError(status_code=503, code="REALTIME_FEED_UNAVAILABLE", message=str(exc)) from exc
    except RealtimeStateStoreUnavailable as exc:
        raise WebAppError(status_code=503, code="REALTIME_STATE_UNAVAILABLE", message=str(exc)) from exc
