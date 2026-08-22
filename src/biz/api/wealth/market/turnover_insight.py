from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.turnover_insight.turnover_insight_query_service import (
    TurnoverInsightQueryService,
)
from src.biz.schemas.wealth.market.turnover_insight import TurnoverInsightResponseDto
from src.foundation.config.settings import get_settings


router = APIRouter(prefix="/wealth/market", tags=["wealth-market"])
_DEBUG_ENVIRONMENTS = frozenset({"local", "dev", "test"})


@router.get("/turnover-insight", response_model=TurnoverInsightResponseDto)
def get_turnover_insight(
    market: str = Query(default="CN_A"),
    trade_date: date | None = Query(default=None, alias="tradeDate"),
    debug: int = Query(default=0, ge=0, le=1),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> TurnoverInsightResponseDto:
    normalized_market = market.strip().upper()
    if normalized_market != "CN_A":
        raise WebAppError(status_code=400, code="400001", message=f"不支持的市场：{market}")

    effective_debug = debug == 1 and get_settings().app_env.strip().lower() in _DEBUG_ENVIRONMENTS
    try:
        return TurnoverInsightQueryService().build_turnover_insight(
            session,
            market=normalized_market,
            trade_date=trade_date,
            debug=effective_debug,
        )
    except ValueError as exc:
        raise WebAppError(status_code=400, code="400001", message=str(exc)) from exc
