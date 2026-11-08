"""Connect the index daily query, indicator service and HTTP response."""

from datetime import date

from fastapi import Request

from src.app.dependencies.stock_daily_technical_indicators import open_stock_daily_read_session
from src.app.runtime.technical_indicators.execution import _execute
from src.biz.queries.wealth.market.index_detail.index_detail_kline_query_service import (
    SSE_DAILY_CALCULATIONS, IndexDetailKlineQueryService, PriceRows, ReadPrevious,
)
from src.biz.services.wealth.market.index_detail.index_detail_universe import IndexDetailQueryError
from src.db import get_session_factory
from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeReader, IndexDailyLakeSourceError
from goldenshare_technical_indicators.contracts import CalculationRequest
from goldenshare_technical_indicators.errors import (
    OutputEncodingError, ResourceLimitError, SourceReadError, TechnicalIndicatorError,
)
from goldenshare_technical_indicators.output.encoding import encode_response_utf8
from goldenshare_technical_indicators.service import TechnicalIndicatorService
from goldenshare_technical_indicators.sources.index_daily import IndexDailyPriceSource


_DG_SOURCE_ORIGIN = date(2000, 1, 4)
_PROD_SOURCE_ORIGIN = date(2010, 1, 4)


async def run_index_daily_kline(
    request: Request, *, daily_lake: IndexDailyLakeReader | None, arrived_at: float,
    ts_code: str, period: str, start_date: date | None, end_date: date | None, limit: int, debug: bool,
) -> bytes:
    runtime = getattr(request.app.state, "technical_indicator_runtime", None)
    if runtime is None:
        raise IndexDetailQueryError(f"{ts_code} 日线指标运行环境未装配")

    source_origin = _PROD_SOURCE_ORIGIN if daily_lake is None else _DG_SOURCE_ORIGIN
    source_id = "prod_index_factor_pro" if daily_lake is None else "dg_index_factor_pro"
    query_params = dict(ts_code=ts_code, period=period, start_date=start_date, end_date=end_date,
                        limit=limit, debug=debug)

    def work(params, control) -> bytes:
        def calculate(rows: PriceRows, read_previous: ReadPrevious):
            source = IndexDailyPriceSource(rows, read_previous, source_origin=source_origin, source_id=source_id)
            calculation = CalculationRequest(
                security_type="index", ts_code=ts_code, period="day", adjustment="none",
                calculations=SSE_DAILY_CALCULATIONS, start=rows[0]["trade_date"],
                end=rows[-1]["trade_date"], limit=len(rows),
            )
            service = TechnicalIndicatorService(
                source=source, registry=runtime.registry, config=runtime.config, control=control,
            )
            try:
                prepared = service._prepare_calculation(calculation)
                result = service._calculate_result(prepared, control=control)
            except TechnicalIndicatorError as exc:
                control.check_active()
                raise IndexDetailQueryError(f"{ts_code} 日线指标计算失败") from exc
            return result, source.preceding_rows

        query = IndexDetailKlineQueryService(daily_lake=daily_lake)
        options = dict(params, calculate=calculate, source_origin=source_origin, check_active=control.check_active)
        try:
            if daily_lake is None:
                with open_stock_daily_read_session(get_session_factory(), control) as session:
                    response = query.build_kline(session, **options)
            else:
                response = query.build_kline(None, **options)
        except (IndexDailyLakeSourceError, SourceReadError) as exc:
            raise IndexDetailQueryError(f"{ts_code} 日线行情读取失败") from exc

        payload = response.model_dump(mode="json", by_alias=True, exclude_none=False, exclude_unset=False)
        try:
            return encode_response_utf8(payload, control=control, max_bytes=runtime.config.max_output_bytes)
        except (OutputEncodingError, ResourceLimitError) as exc:
            raise IndexDetailQueryError(f"{ts_code} 日线回包编码失败") from exc

    return await _execute(
        runtime, arrived_at=arrived_at, validate_before_wait=lambda: query_params,
        work=work, receive=request.receive,
    )
