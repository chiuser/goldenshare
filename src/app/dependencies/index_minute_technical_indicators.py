"""Execute the local index minute APIs using the shared calculation runtime."""

import anyio
from goldenshare_technical_indicators.errors import SourceContractError, SourceReadError
from goldenshare_technical_indicators.service import TechnicalIndicatorService
from starlette.requests import Request
from starlette.responses import Response

from src.app.runtime.technical_indicators.execution import _execute
from src.biz.queries.wealth.market.index_detail_minutes.index_detail_minutes_query_service import (
    IndexDetailMinutesQueryService,
)
from src.biz.queries.wealth.market.index_detail_minutes.index_minute_calculation_reader import (
    IndexMinuteCalculationReader,
)
from src.foundation.clients.local_lake.major_index_mins_contract import MAX_INDEX_MINUTE_LIMIT, IndexMinuteDataset
from src.foundation.clients.local_lake.major_index_mins_reader import IndexMinuteSourceContractError
from src.foundation.config.local_minute_capability import LocalMinuteCapabilityError


async def run_index_minute_page(
    request: Request, *, dataset: IndexMinuteDataset, arrived_at: float, **params,
) -> Response:
    runtime = getattr(request.app.state, "technical_indicator_runtime", None)
    if runtime is None:
        raise LocalMinuteCapabilityError(
            code="SM_LOCAL_LAKE_NOT_CONFIGURED", message="本地指数分钟数据能力未启用。",
        )

    def work(options, control):
        service = TechnicalIndicatorService(
            source=runtime.source, registry=runtime.registry, config=runtime.config, control=control,
        )

        def calculate(calculation):
            return service.calculate_index_minutes_recent(calculation, output_limit=MAX_INDEX_MINUTE_LIMIT)

        query = IndexDetailMinutesQueryService(IndexMinuteCalculationReader(calculate))
        try:
            response = query.read_bars(**options) if dataset == "bars" else query.read_indicators(**options)
            return response.model_dump_json().encode("utf-8")
        except SourceContractError as exc:
            raise IndexMinuteSourceContractError(str(exc)) from exc
        except SourceReadError as exc:
            from duckdb import BinderException, ConversionException, IOException

            # Keep the existing HTTP category for unreadable Parquet contracts.
            if isinstance(exc.__cause__, (BinderException, ConversionException, IOException)):
                raise IndexMinuteSourceContractError(str(exc)) from exc
            raise

    disconnected = False

    async def receive():
        nonlocal disconnected
        message = await request.receive()
        disconnected = message["type"] == "http.disconnect"
        return message

    try:
        body = await _execute(
            runtime, arrived_at=arrived_at, validate_before_wait=lambda: params, work=work, receive=receive,
        )
    except anyio.get_cancelled_exc_class():
        if not disconnected:
            raise
        # The client already left. The shared runtime has waited for the worker to clean up.
        return Response(status_code=204)
    return Response(content=body, media_type="application/json")
