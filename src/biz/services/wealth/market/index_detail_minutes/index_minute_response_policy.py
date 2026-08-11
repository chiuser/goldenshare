from __future__ import annotations

from datetime import date
from typing import Any

from src.biz.schemas.wealth.market.index_detail_minutes import (
    IndexMinuteDataStatusDto,
    IndexMinutePageMetaDto,
)
from src.foundation.clients.local_lake.major_index_mins_reader import (
    IndexMinuteReadPage,
    IndexMinuteRequestError,
)


MAX_INDEX_MINUTE_RESPONSE_BYTES = 5_000_000


def build_index_minute_meta(
    page: IndexMinuteReadPage,
    *,
    start_date: date | None,
    end_date: date | None,
    limit: int,
) -> IndexMinutePageMetaDto:
    return IndexMinutePageMetaDto(
        count=page.count,
        limit=limit,
        hasMore=page.has_more,
        nextCursor=page.next_cursor,
        startDate=start_date,
        endDate=end_date,
        observedStartDate=page.observed_start_date,
        observedEndDate=page.observed_end_date,
    )


def build_index_minute_status(
    page: IndexMinuteReadPage,
    *,
    expected_end_date: date | None,
    known_unsupported: bool = False,
) -> IndexMinuteDataStatusDto:
    if known_unsupported:
        return IndexMinuteDataStatusDto(
            status="EMPTY",
            code="IM_SOURCE_NOT_READY",
            expectedEndDate=expected_end_date,
            observedEndDate=None,
            message="当前分钟数据源暂不覆盖该指数。",
        )
    if not page.rows:
        return IndexMinuteDataStatusDto(
            status="DELAYED" if expected_end_date is not None else "EMPTY",
            code="IM_SOURCE_NOT_READY",
            expectedEndDate=expected_end_date,
            observedEndDate=None,
            message="指数分钟数据尚未覆盖请求范围。",
        )
    if (
        expected_end_date is not None
        and page.observed_end_date is not None
        and page.observed_end_date < expected_end_date
    ):
        return IndexMinuteDataStatusDto(
            status="DELAYED",
            code="IM_SOURCE_NOT_READY",
            expectedEndDate=expected_end_date,
            observedEndDate=page.observed_end_date,
            message="指数分钟数据尚未覆盖期望交易日。",
        )
    return IndexMinuteDataStatusDto(
        status="READY",
        code=None,
        expectedEndDate=expected_end_date,
        observedEndDate=page.observed_end_date,
        message=None,
    )


def enforce_index_minute_response_size(response: Any) -> None:
    payload_size = len(response.model_dump_json().encode("utf-8"))
    if payload_size > MAX_INDEX_MINUTE_RESPONSE_BYTES:
        raise IndexMinuteRequestError("响应超过 5MB，请降低 limit 或使用 cursor 分页。")
