"""Prepare detached business facts and map kernel results to the unchanged DTO."""

from datetime import date

from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.stock_detail.stock_detail_query_service import StockDetailQueryService
from src.biz.schemas.wealth.market.stock_detail import (
    StockBollDto, StockDetailDebugInfoDto, StockDetailKlineResponseDto,
    StockDetailStockRefDto, StockKdjDto, StockKlineFactorDto, StockKlineMetaDto,
    StockMacdDto, StockMovingAverageDto,
)
from goldenshare_technical_indicators.contracts import CalculationResult
from goldenshare_technical_indicators.errors import OutputContractError

from .stock_daily_kline_calculations import (
    STOCK_DAILY_ALGORITHM_VERSIONS, STOCK_DAILY_CALCULATIONS, STOCK_DAILY_OUTPUT_FIELDS,
)
from .stock_daily_kline_contracts import StockDailyKlineInput, StockDailyKlineRequest
from .stock_detail_field_mapper import build_data_status, build_kline_bar, build_page_context, to_float


def _contract_error(reason, *, instance_id=None, **diagnostics):
    return OutputContractError(
        "Stock daily result does not match the response contract", reason=reason,
        stage="stock_daily_assemble", instance_id=instance_id, **diagnostics,
    )


class StockDailyKlineService:
    def __init__(self) -> None:
        self._query = StockDetailQueryService()

    def prepare(self, session: Session, request: StockDailyKlineRequest) -> StockDailyKlineInput:
        return self._query.prepare_kline_input(session, request)

    def _validate_result(self, source: StockDailyKlineInput, result: CalculationResult) -> None:
        if not isinstance(result, CalculationResult):
            raise _contract_error("count_mismatch", expected=len(source.bars), actual=0)
        series = result.series
        if (series.security_type, series.ts_code, series.period, series.adjustment, series.timezone) != (
            "stock", source.ts_code, "day", "qfq", "Asia/Shanghai",
        ):
            raise _contract_error("series_mismatch")
        times = tuple(row.trade_date for row in source.bars)
        if any(type(value) is not date for value in result.times) or result.times != times:
            raise _contract_error("time_mismatch", expected=len(times), actual=len(result.times))
        if (result.range.count != len(times) or result.range.actual_start != times[0]
                or result.range.actual_end != times[-1]):
            raise _contract_error("count_mismatch", expected=len(times), actual=result.range.count)
        expected = {item.instance_id: item for item in STOCK_DAILY_CALCULATIONS}
        ids = [item.instance_id for item in result.calculations]
        if len(ids) != len(expected) or set(ids) != set(expected):
            raise _contract_error("instances_mismatch", expected=len(expected), actual=len(ids))
        for item in result.calculations:
            definition = expected[item.instance_id]
            parameters = dict(item.parameters)
            if (item.calculation_id != definition.calculation_id
                    or item.algorithm_version != STOCK_DAILY_ALGORITHM_VERSIONS[definition.calculation_id]
                    or len(parameters) != len(item.parameters)
                    or parameters != dict(definition.parameters)):
                raise _contract_error("definition_mismatch", instance_id=item.instance_id)
            fields = [name for name, _ in item.fields]
            required = STOCK_DAILY_OUTPUT_FIELDS[definition.calculation_id]
            if len(fields) != len(required) or set(fields) != set(required):
                raise _contract_error("fields_mismatch", instance_id=item.instance_id)
            for name, values in item.fields:
                if len(values) != len(times):
                    raise _contract_error("value_count_mismatch", instance_id=item.instance_id,
                                          field=name, expected=len(times), actual=len(values))
                if item.calculation_id in ("macd", "kdj") and any(value is None for value in values):
                    raise _contract_error("unexpected_null", instance_id=item.instance_id, field=name)

    def assemble(
        self, source: StockDailyKlineInput, result: CalculationResult | None,
    ) -> StockDetailKlineResponseDto:
        if source.bars:
            self._validate_result(source, result)
        elif result is not None:
            raise _contract_error("count_mismatch", expected=0,
                                  actual=len(result.times) if isinstance(result, CalculationResult) else 0)
        # Values remain references to validated, immutable tuples; no full-column copies.
        fields = ({item.instance_id: dict(item.fields) for item in result.calculations}
                  if result is not None else {})
        issues = None
        try:
            bars = []
            for index, row in enumerate(source.bars):
                factors = StockKlineFactorDto(
                    ma=StockMovingAverageDto(**{
                        name: to_float(fields[name]["value"][index])
                        for name in ("ma5", "ma10", "ma20", "ma30", "ma60", "ma90", "ma250")
                    }),
                    boll=StockBollDto(**{name: to_float(fields["boll"][name][index])
                                       for name in ("upper", "middle", "lower")}),
                    macd=StockMacdDto(
                        dif=to_float(fields["macd"]["dif"][index]),
                        dea=to_float(fields["macd"]["dea"][index]),
                        macd=to_float(fields["macd"]["hist"][index]),
                    ),
                    kdj=StockKdjDto(**{name: to_float(fields["kdj"][name][index])
                                     for name in ("k", "d", "j")}),
                )
                bars.append(build_kline_bar(row, factors))
            request = source.request
            observed = source.bars[-1].trade_date if source.bars else None
            tables = ["core_serving.security_serving", "core_serving.equity_factor_pro"]
            if result is not None:
                tables.extend(("lake.silver.quote.stock_daily", "lake.silver.quote.adj_factor"))
            return StockDetailKlineResponseDto(
                pageContext=build_page_context(source.context),
                stockRef=StockDetailStockRefDto(tsCode=source.ts_code, name=source.name),
                period="day", adjustment="forward", sourceAdjustment="qfq", bars=bars,
                meta=StockKlineMetaDto(count=len(bars), limit=request.limit,
                                      startDate=request.start_date, endDate=source.query_end_date),
                dataStatus=build_data_status(expected_trade_date=source.query_end_date,
                                             observed_trade_date=observed),
                debugInfo=StockDetailDebugInfoDto(sourceTables=tables, query={
                    "tsCode": source.ts_code, "expectedTradeDate": source.query_end_date.isoformat(),
                    "observedTradeDate": observed.isoformat() if observed is not None else None,
                    "limit": request.limit,
                }) if request.debug else None,
            )
        except ValidationError as error:
            # Pydantic itself can retain input. Only bounded, input-free diagnostics survive.
            issues = tuple((tuple(item["loc"]), item["type"]) for item in error.errors(
                include_input=False, include_context=False, include_url=False,
            )[:4])
        # Outside the except block: do not attach the input-owning ValidationError.
        raise _contract_error("dto_validation_failed", error_type="ValidationError", issues=issues)
