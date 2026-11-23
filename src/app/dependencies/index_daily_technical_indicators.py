"""Connect the index daily query, indicator service and HTTP response."""

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Request

from src.app.dependencies.stock_daily_technical_indicators import open_stock_daily_read_session
from src.app.runtime.technical_indicators.execution import _execute
from src.biz.queries.wealth.market.index_detail.index_detail_kline_query_service import (
    SSE_DAILY_CALCULATIONS, IndexDetailKlineQueryService,
)
from src.biz.services.wealth.market.index_detail.index_detail_universe import IndexDetailQueryError, IndexDetailRequestError
from src.db import get_session_factory
from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeReader, IndexDailyLakeSourceError
from goldenshare_technical_indicators.contracts import CalculationRequest
from goldenshare_technical_indicators.errors import (
    OutputEncodingError, SourceReadError, TechnicalIndicatorError,
)
from goldenshare_technical_indicators.output.encoding import encode_response_utf8
from goldenshare_technical_indicators.service import TechnicalIndicatorService


_PROD_SOURCE_ORIGIN = date(2010, 1, 4)
_DG_CALCULATIONS = (*SSE_DAILY_CALCULATIONS, {"calculation_id": "price", "parameters": {}})


async def run_index_daily_kline(
    request: Request, *, daily_lake: IndexDailyLakeReader | None, arrived_at: float,
    ts_code: str, period: str, start_date: date | None, end_date: date | None, limit: int, project=None,
) -> bytes:
    runtime = getattr(request.app.state, "technical_indicator_runtime", None)
    if runtime is None:
        raise IndexDetailQueryError(f"{ts_code} 日线指标运行环境未装配")

    use_dg = runtime.config.data_location == "dg"
    if use_dg and limit > runtime.config.max_output_rows:
        raise IndexDetailRequestError(f"日线 limit 必须在 1 到 {runtime.config.max_output_rows} 之间")
    if use_dg and daily_lake is None:
        daily_lake = IndexDailyLakeReader(Path(runtime.config.goldenshare_lake_root))
    if not use_dg:
        daily_lake = None
    query_params = dict(ts_code=ts_code, period=period, start_date=start_date, end_date=end_date,
                        limit=limit)

    def work(params, control) -> bytes:
        timezone = ZoneInfo("Asia/Shanghai")
        service = TechnicalIndicatorService(
            source=runtime.source, registry=runtime.registry, config=runtime.config, control=control,
        )

        def calculate(start, end, *, latest_rows=None):
            calculation = CalculationRequest(
                security_type="index", ts_code=ts_code, period="day", adjustment="none",
                calculations=_DG_CALCULATIONS if latest_rows is not None else SSE_DAILY_CALCULATIONS,
                start=datetime.combine(start, time.min, timezone),
                end=datetime.combine(end, time.min, timezone),
                latest_rows=latest_rows,
            )
            try:
                if latest_rows is not None:
                    return service.calculate_with_source(calculation)
                prepared = service._prepare_calculation(calculation)
                return service._calculate_library(prepared, control=control, collect_target_ohlc=True)
            except SourceReadError:
                raise
            except TechnicalIndicatorError as exc:
                control.check_active()
                raise IndexDetailQueryError(f"{ts_code} 日线指标计算失败") from exc

        query = IndexDetailKlineQueryService(daily_lake=daily_lake)
        options = dict(params, check_active=control.check_active)
        if use_dg:
            options["calculate_recent"] = lambda end, start, limit: calculate(start, end, latest_rows=limit)
        else:
            options["calculate"] = lambda dates: calculate(dates[0], dates[-1])
            options["source_origin"] = _PROD_SOURCE_ORIGIN

        def build(session):
            if project is None:
                return query.build_kline(session, **options)
            return project(*query.query_kline(session, **options))

        try:
            if daily_lake is None:
                with open_stock_daily_read_session(get_session_factory(), control) as session:
                    response = build(session)
            else:
                response = build(None)
        except SourceReadError as exc:
            reason = f"：{exc.detail}" if exc.detail else ""
            raise IndexDetailQueryError(f"{ts_code} 读取数据失败{reason}") from exc
        except IndexDailyLakeSourceError as exc:
            raise IndexDetailQueryError(f"{ts_code} 日线行情读取失败") from exc

        payload = response.model_dump(mode="json", by_alias=True, exclude_none=False, exclude_unset=False)
        try:
            return encode_response_utf8(payload, control=control)
        except OutputEncodingError as exc:
            raise IndexDetailQueryError(f"{ts_code} 日线回包编码失败") from exc

    return await _execute(
        runtime, arrived_at=arrived_at, validate_before_wait=lambda: query_params,
        work=work, receive=request.receive,
    )
