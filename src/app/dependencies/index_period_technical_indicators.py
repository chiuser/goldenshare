"""Wire index weekly/monthly selection and calculation into the HTTP request."""

from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from src.app.dependencies.stock_daily_technical_indicators import open_stock_daily_read_session
from src.app.runtime.technical_indicators.execution import _execute
from src.biz.queries.wealth.market.index_detail.index_detail_kline_query_service import SSE_DAILY_CALCULATIONS
from src.biz.queries.wealth.market.index_detail.index_detail_period_kline_query_service import (
    IndexDetailPeriodKlineQueryService,
)
from src.biz.services.wealth.market.index_detail.index_detail_universe import IndexDetailQueryError
from src.db import get_session_factory
from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeReader, IndexDailyLakeSourceError
from goldenshare_technical_indicators.contracts import CalculationRequest
from goldenshare_technical_indicators.errors import SourceReadError, TechnicalIndicatorError
from goldenshare_technical_indicators.output.encoding import encode_response_utf8
from goldenshare_technical_indicators.service import TechnicalIndicatorService


def supports_index_period_kline(request):
    runtime = getattr(request.app.state, "technical_indicator_runtime", None)
    if runtime is None or runtime.config.max_output_rows < 500:
        return False
    config = runtime.config
    return all("none" in config.enabled_adjustments(config.market_datasets.get(("index", period), ""))
               for period in ("week", "month"))


async def run_index_period_kline(request, *, arrived_at, ts_code, period, start_date, end_date, limit, project=None):
    runtime = request.app.state.technical_indicator_runtime
    use_dg = runtime.config.data_location == "dg"
    query = IndexDetailPeriodKlineQueryService(
        daily_lake=IndexDailyLakeReader(Path(runtime.config.goldenshare_lake_root)) if use_dg else None,
    )
    params = dict(ts_code=ts_code, period=period, start_date=start_date, end_date=end_date, limit=limit)

    def work(options, control):
        def calculate(start, end, latest_rows=None):
            zone = ZoneInfo("Asia/Shanghai")
            service = TechnicalIndicatorService(
                source=runtime.source, registry=runtime.registry, config=runtime.config, control=control,
            )
            calculation = CalculationRequest(
                security_type="index", ts_code=ts_code, period=period, adjustment="none",
                start=datetime.combine(start, time.min, zone) if start is not None else None,
                end=datetime.combine(end, time.min, zone), latest_rows=latest_rows,
                calculations=({"calculation_id": "price", "parameters": {}}, *SSE_DAILY_CALCULATIONS),
            )
            return (service.calculate_with_source(calculation) if latest_rows is not None
                    else service.calculate(calculation))

        try:
            read_options = dict(options, source=runtime.source, control=control,
                                calculate_recent=calculate if use_dg else None)
            if use_dg and end_date is not None:
                page = query.read_page(None, **read_options)
            else:
                with open_stock_daily_read_session(get_session_factory(), control) as session:
                    page = query.read_page(session, **read_options)
            control.check_active()
            response, missing = query.query_period_kline(
                page, ts_code=ts_code, period=period, start_date=start_date, limit=limit,
                calculate=None if use_dg else calculate,
            )
            if project is not None:
                response = project(response, missing)
            return encode_response_utf8(response.model_dump(mode="json"), control=control)
        except SourceReadError as exc:
            reason = f"：{exc.detail}" if exc.detail else ""
            raise IndexDetailQueryError(f"{ts_code} {period} 行情读取失败{reason}") from exc
        except (TechnicalIndicatorError, IndexDailyLakeSourceError) as exc:
            control.check_active()
            raise IndexDetailQueryError(f"{ts_code} {period} 行情或指标查询失败") from exc

    return await _execute(
        runtime, arrived_at=arrived_at, validate_before_wait=lambda: params, work=work, receive=request.receive,
    )
