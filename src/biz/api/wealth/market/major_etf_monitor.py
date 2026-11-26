from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, Response

from src.biz.queries.wealth.market.major_etf_monitor.major_etf_monitor_query import query_major_etf_monitor
from src.biz.schemas.wealth.market.major_etf_monitor import MajorEtfMonitorResponseDto
from src.foundation.clients.local_lake.etf_daily_reader import EtfDailyLakeReader, EtfDailyReadError

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def build_router(
    *,
    reader: EtfDailyLakeReader,
    auth_dependency: Callable,
    error_factory: Callable[..., Exception],
) -> APIRouter:
    router = APIRouter(prefix="/wealth/market", tags=["wealth-market"])

    @router.get("/major-etf-monitor", response_model=MajorEtfMonitorResponseDto)
    def get_major_etf_monitor(
        request: Request, response: Response, _user=Depends(auth_dependency),
    ) -> MajorEtfMonitorResponseDto:
        response.headers["Cache-Control"] = "no-store"
        try:
            return query_major_etf_monitor(
                reader, today=datetime.now(_SHANGHAI).date(), request_id=getattr(request.state, "request_id", None),
            )
        except (EtfDailyReadError, TimeoutError) as exc:
            raise error_factory(
                status_code=503,
                code="MAJOR_ETF_MONITOR_SOURCE_UNAVAILABLE",
                message="主要ETF（国家队）监测暂不可读取，请重试",
            ) from exc

    return router
