from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any
from zoneinfo import ZoneInfo

from src.biz.schemas.wealth.market.nine_turn import (
    NineTurnDataStatusDto,
    NineTurnMarkerDto,
    NineTurnMetaDto,
    NineTurnPeriod,
    NineTurnSeriesDto,
)
from src.foundation.clients.local_lake.stock_nine_turn_contract import (
    MAX_NINE_TURN_RESPONSE_BYTES,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


class NineTurnContractError(RuntimeError):
    """Raised when a serving/Lake row violates the frozen nine-turn contract."""


def build_stock_nine_turn_response(
    *,
    ts_code: str,
    period: NineTurnPeriod,
    rows: list[dict[str, Any]],
    source_row_count: int,
    matched_row_count: int,
    missing_row_count: int,
    has_more: bool,
    next_cursor: str | None,
    start_date: date | None,
    end_date: date,
    expected_end_date: date | None,
    observed_start_date: date | None,
    observed_end_date: date | None,
    limit: int,
    debug_info: dict[str, Any] | None,
) -> NineTurnSeriesDto:
    markers = [marker for row in rows if (marker := _marker_from_row(row)) is not None]
    latest_marker = _marker_from_row(rows[-1]) if rows else None
    response = NineTurnSeriesDto(
        tsCode=ts_code,
        period=period,
        markers=markers,
        latestMarker=latest_marker,
        dataStatus=_build_status(
            source_row_count=source_row_count,
            matched_row_count=matched_row_count,
            missing_row_count=missing_row_count,
            expected_end_date=expected_end_date,
            observed_end_date=observed_end_date,
        ),
        meta=NineTurnMetaDto(
            sourceRowCount=source_row_count,
            matchedRowCount=matched_row_count,
            missingRowCount=missing_row_count,
            markerCount=len(markers),
            limit=limit,
            hasMore=has_more,
            nextCursor=next_cursor,
            startDate=start_date,
            endDate=end_date,
            observedStartDate=observed_start_date,
            observedEndDate=observed_end_date,
        ),
        debugInfo=debug_info,
    )
    if len(json.dumps(response.model_dump(mode="json"), ensure_ascii=False).encode()) > MAX_NINE_TURN_RESPONSE_BYTES:
        raise ValueError("九转响应超过 5MB，请缩小查询窗口。")
    return response


def _marker_from_row(row: dict[str, Any]) -> NineTurnMarkerDto | None:
    if not row.get("nine_turn_matched", False):
        return None
    up_count = _validated_count(row.get("up_count"), "up_count")
    down_count = _validated_count(row.get("down_count"), "down_count")
    if up_count > 0 and down_count > 0:
        raise NineTurnContractError("九转行不能同时处于上下两个方向。")
    if 1 <= up_count <= 9:
        direction = "UP"
        sequence_number = up_count
    elif 1 <= down_count <= 9:
        direction = "DOWN"
        sequence_number = down_count
    else:
        return None
    trade_time = row.get("trade_time")
    if trade_time is not None:
        if not isinstance(trade_time, datetime):
            raise NineTurnContractError("trade_time 必须是 datetime。")
        trade_time = (
            trade_time.astimezone(SHANGHAI)
            if trade_time.tzinfo is not None
            else trade_time.replace(tzinfo=SHANGHAI)
        )
    return NineTurnMarkerDto(
        tradeDate=row["trade_date"],
        tradeTime=trade_time,
        direction=direction,
        sequenceNumber=sequence_number,  # type: ignore[arg-type]
        completed=sequence_number == 9,
    )


def _validated_count(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NineTurnContractError(f"{field_name} 必须是非负整数。")
    return value


def _build_status(
    *,
    source_row_count: int,
    matched_row_count: int,
    missing_row_count: int,
    expected_end_date: date | None,
    observed_end_date: date | None,
) -> NineTurnDataStatusDto:
    if source_row_count == 0 or matched_row_count == 0:
        return NineTurnDataStatusDto(
            status="EMPTY",
            code="NT_SOURCE_NOT_READY",
            message="九转数据尚未覆盖当前 K 线窗口。",
            expectedEndDate=expected_end_date,
            observedEndDate=observed_end_date,
        )
    if missing_row_count > 0:
        return NineTurnDataStatusDto(
            status="PARTIAL",
            code="NT_ALIGNMENT_PARTIAL",
            message=f"九转与 K 线有 {missing_row_count} 个时间键未对齐。",
            expectedEndDate=expected_end_date,
            observedEndDate=observed_end_date,
        )
    if (
        expected_end_date is not None
        and observed_end_date is not None
        and observed_end_date < expected_end_date
    ):
        return NineTurnDataStatusDto(
            status="DELAYED",
            code="NT_SOURCE_NOT_READY",
            message="九转数据尚未覆盖页面期望交易日。",
            expectedEndDate=expected_end_date,
            observedEndDate=observed_end_date,
        )
    return NineTurnDataStatusDto(
        status="READY",
        expectedEndDate=expected_end_date,
        observedEndDate=observed_end_date,
    )
