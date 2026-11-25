"""Run the local stock minute APIs in the shared calculation runtime."""

import anyio
from goldenshare_technical_indicators.service import TechnicalIndicatorService
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import Response

from src.app.exceptions import WebAppError
from src.app.runtime.technical_indicators.execution import _execute
from src.biz.queries.wealth.market.stock_detail_minutes.stock_detail_minutes_query_service import StockMinuteQueryService
from src.biz.queries.wealth.market.stock_detail_minutes.stock_minute_calculation_reader import (
    StockMinuteCalculationReader,
    StockMinuteOutput,
)
from src.biz.queries.wealth.market.stock_minute_nine_turn.stock_minute_nine_turn_query_service import (
    StockMinuteNineTurnQueryService,
)
from src.foundation.clients.local_lake.stock_mins_reader import MAX_MINUTE_LIMIT, MinuteReadRequest, MinuteRequestError


MAX_RESPONSE_BYTES = 5_000_000


async def run_stock_minute_page(
    request: Request, *, output: StockMinuteOutput, arrived_at: float,
    query: MinuteReadRequest, debug: bool, session: Session | None = None,
) -> Response:
    runtime = getattr(request.app.state, "technical_indicator_runtime", None)
    if runtime is None:
        raise WebAppError(
            status_code=503, code="SM_LOCAL_LAKE_NOT_CONFIGURED", message="本地分钟数据能力未启用。",
        )

    def work(options, control):
        service = TechnicalIndicatorService(
            source=runtime.source, registry=runtime.registry, config=runtime.config, control=control,
        )

        def calculate(calculation):
            return service.calculate_stock_minutes_recent(calculation, output_limit=MAX_MINUTE_LIMIT)

        reader = StockMinuteCalculationReader(calculate)
        if output == "nine_turn":
            result = StockMinuteNineTurnQueryService(reader).read(session, options, debug=debug)
        else:
            query_service = StockMinuteQueryService(reader)
            result = (
                query_service.read_chart(options, debug=debug) if output == "chart"
                else query_service.read_indicators(options, debug=debug)
            )
        body = result.model_dump_json(by_alias=True).encode("utf-8")
        if len(body) > MAX_RESPONSE_BYTES:
            raise MinuteRequestError("响应超过 5MB，请降低 limit 或使用 cursor 分页。")
        return body

    disconnected = False

    async def receive():
        nonlocal disconnected
        message = await request.receive()
        disconnected = message["type"] == "http.disconnect"
        return message

    try:
        body = await _execute(
            runtime, arrived_at=arrived_at, validate_before_wait=lambda: query, work=work, receive=receive,
        )
    except anyio.get_cancelled_exc_class():
        if not disconnected:
            raise
        return Response(status_code=204)
    return Response(content=body, media_type="application/json")
