from collections.abc import Callable
from datetime import datetime
import logging
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response

from src.biz.queries.wealth.market.etf_activity.etf_activity_query import query_etf_activity
from src.biz.schemas.wealth.market.etf_activity import EtfActivityResponseDto
from src.foundation.clients.local_lake.etf_daily_reader import EtfDailyLakeReader, EtfDailyReadError
from src.foundation.clients.reference_data import ReferenceDataReadError

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_logger = logging.getLogger(__name__)


def build_router(
    *,
    reader: EtfDailyLakeReader,
    auth_dependency: Callable,
    error_factory: Callable[..., Exception],
) -> APIRouter:
    router = APIRouter(prefix="/wealth/market", tags=["wealth-market"])

    @router.get("/etf-activity", response_model=EtfActivityResponseDto)
    def get_etf_activity(response: Response, _user=Depends(auth_dependency)) -> EtfActivityResponseDto:
        response.headers["Cache-Control"] = "no-store"
        try:
            return query_etf_activity(reader, today=datetime.now(_SHANGHAI).date())
        except (EtfDailyReadError, ReferenceDataReadError, TimeoutError) as exc:
            _logger.warning("ETF 动态来源读取失败: %s", exc)
            raise error_factory(
                status_code=503,
                code="ETF_ACTIVITY_SOURCE_UNAVAILABLE",
                message="ETF 动态暂不可读取，请重试",
            ) from exc

    return router
