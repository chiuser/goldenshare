"""Prepare detached business facts and map kernel results to the stock daily response."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date

from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.stock_detail.stock_detail_query_service import StockDetailQueryService
from src.biz.schemas.wealth.market.stock_detail import (
    LocalStockDetailFirstKlineResponseDto, LocalStockDetailPagedKlineResponseDto, LocalStockKlineMetaDto,
    StockBollDto, StockDetailDebugInfoDto, StockDetailKlineResponseDto,
    StockDetailStockRefDto, StockKdjDto, StockKlineFactorDto, StockKlineMetaDto,
    StockMacdDto, StockMovingAverageDto,
)
from src.biz.services.wealth.market.nine_turn.nine_turn_response_policy import build_nine_turn_marker
from src.foundation.clients.reference_data import ReferenceData
from goldenshare_technical_indicators.contracts import CalculationResult
from goldenshare_technical_indicators.errors import OutputContractError

from .stock_daily_kline_calculations import (
    STOCK_DAILY_ALGORITHM_VERSIONS, STOCK_DAILY_OUTPUT_FIELDS, stock_daily_calculations,
)
from .stock_daily_kline_contracts import StockDailyKlineInput, StockDailyKlinePage, StockDailyKlineRequest
from .stock_detail_field_mapper import (
    build_data_status, build_kline_bar, build_page_context, build_quote_from_kline_bar, to_float,
)


def _contract_error(reason, *, calculation_index=None, **diagnostics):
    return OutputContractError(
        "Stock daily result does not match the response contract", reason=reason,
        stage="stock_daily_assemble", calculation_index=calculation_index, **diagnostics,
    )


def _calculation_key(calculation_id, parameters):
    return calculation_id, tuple(sorted(dict(parameters).items()))


class StockDailyKlineService:
    def __init__(self, reference_data: ReferenceData | None = None) -> None:
        self._query = StockDetailQueryService(reference_data)

    def prepare(
        self, session: Session | None, request: StockDailyKlineRequest, *,
        load_rows: Callable[[str, date, date | None, int], StockDailyKlinePage],
        remaining_seconds: Callable[[], float] | None = None,
        paginated: bool = False,
    ) -> StockDailyKlineInput:
        return self._query.prepare_kline_input(
            session, request, load_rows=load_rows, remaining_seconds=remaining_seconds, paginated=paginated,
        )

    def _validate_result(
        self, source: StockDailyKlineInput, result: CalculationResult, *, include_nine_turn: bool = False,
    ) -> None:
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
        expected = {_calculation_key(item["calculation_id"], item["parameters"])
                    for item in stock_daily_calculations(include_nine_turn=include_nine_turn)}
        keys = [_calculation_key(item.calculation_id, item.parameters) for item in result.calculations]
        if len(keys) != len(expected) or set(keys) != expected:
            raise _contract_error("instances_mismatch", expected=len(expected), actual=len(keys))
        for index, item in enumerate(result.calculations):
            if item.algorithm_version != STOCK_DAILY_ALGORITHM_VERSIONS[item.calculation_id]:
                raise _contract_error("definition_mismatch", calculation_index=index)
            fields = [name for name, _ in item.fields]
            required = STOCK_DAILY_OUTPUT_FIELDS[item.calculation_id]
            if len(fields) != len(required) or set(fields) != set(required):
                raise _contract_error("fields_mismatch", calculation_index=index)
            for name, values in item.fields:
                if len(values) != len(times):
                    raise _contract_error("value_count_mismatch", calculation_index=index,
                                          field=name, expected=len(times), actual=len(values))
                if (item.calculation_id in ("macd", "kdj")
                        or item.calculation_id == "price" and name in ("open", "high", "low", "close")):
                    if any(value is None for value in values):
                        raise _contract_error("unexpected_null", calculation_index=index, field=name)
                if item.calculation_id == "nineturn" and any(
                    type(value) not in (int, float) or not 0 <= value <= 13 or value != int(value)
                    for value in values
                ):
                    raise _contract_error("invalid_value", calculation_index=index, field=name)
            if item.calculation_id == "nineturn":
                counts = dict(item.fields)
                if any(up and down for up, down in zip(counts["up_count"], counts["down_count"], strict=True)):
                    raise _contract_error("invalid_value", calculation_index=index)

    def assemble(
        self, source: StockDailyKlineInput, result: CalculationResult | None,
        *, source_tables: tuple[str, ...], include_quote: bool = False, paginated: bool = False,
    ) -> StockDetailKlineResponseDto:
        if source.bars:
            self._validate_result(source, result, include_nine_turn=paginated)
        elif result is not None:
            raise _contract_error("count_mismatch", expected=0,
                                  actual=len(result.times) if isinstance(result, CalculationResult) else 0)
        # Values remain references to validated, immutable tuples; no full-column copies.
        fields = ({_calculation_key(item.calculation_id, item.parameters): dict(item.fields)
                   for item in result.calculations}
                  if result is not None else {})
        issues = None
        try:
            bars = []
            nine_turn_markers = []
            fixed_fields = {key[0]: values for key, values in fields.items() if key[0] != "ma"}
            nine_turn = fixed_fields.get("nineturn")
            for index, row in enumerate(source.bars):
                factors = StockKlineFactorDto(
                    ma=StockMovingAverageDto(**{
                        f"ma{period}": to_float(fields[("ma", (("period", period),))]["value"][index])
                        for period in (5, 10, 20, 30, 60, 90, 250)
                    }),
                    boll=StockBollDto(**{name: to_float(fixed_fields["boll"][name][index])
                                       for name in ("upper", "middle", "lower")}),
                    macd=StockMacdDto(
                        dif=to_float(fixed_fields["macd"]["dif"][index]),
                        dea=to_float(fixed_fields["macd"]["dea"][index]),
                        macd=to_float(fixed_fields["macd"]["hist"][index]),
                    ),
                    kdj=StockKdjDto(**{name: to_float(fixed_fields["kdj"][name][index])
                                     for name in ("k", "d", "j")}),
                )
                price = fixed_fields["price"]
                volume, amount = price["volume"][index], price["amount"][index]
                row = replace(row, **{name + "_qfq": price[name][index] for name in ("open", "high", "low", "close")},
                              vol=None if volume is None else volume / 100,
                              amount=None if amount is None else amount / 1000)
                bars.append(build_kline_bar(row, factors))
                if nine_turn is not None:
                    marker = build_nine_turn_marker(
                        trade_date=row.trade_date, trade_time=None,
                        up_count=int(nine_turn["up_count"][index]), down_count=int(nine_turn["down_count"][index]),
                    )
                    if marker is not None:
                        nine_turn_markers.append(marker)
            request = source.request
            observed = source.bars[-1].trade_date if source.bars else None
            meta_fields = dict(count=len(bars), limit=request.limit,
                               startDate=request.start_date, endDate=source.query_end_date)
            meta = (LocalStockKlineMetaDto(**meta_fields, nextEndDate=source.next_end_date)
                    if paginated else StockKlineMetaDto(**meta_fields))
            response_fields = dict(
                pageContext=build_page_context(source.context),
                stockRef=StockDetailStockRefDto(tsCode=source.ts_code, name=source.name),
                period="day", adjustment="forward", sourceAdjustment="qfq", bars=bars,
                meta=meta,
                dataStatus=build_data_status(expected_trade_date=source.query_end_date,
                                             observed_trade_date=observed),
                debugInfo=StockDetailDebugInfoDto(sourceTables=list(source_tables), query={
                    "tsCode": source.ts_code, "expectedTradeDate": source.query_end_date.isoformat(),
                    "observedTradeDate": observed.isoformat() if observed is not None else None,
                    "limit": request.limit,
                }) if request.debug else None,
            )
            if include_quote:
                return LocalStockDetailFirstKlineResponseDto(
                    **response_fields, nineTurnMarkers=nine_turn_markers,
                    quote=build_quote_from_kline_bar(bars[-1]) if bars else None,
                )
            if paginated:
                return LocalStockDetailPagedKlineResponseDto(**response_fields, nineTurnMarkers=nine_turn_markers)
            return StockDetailKlineResponseDto(**response_fields)
        except ValidationError as error:
            # Pydantic itself can retain input. Only bounded, input-free diagnostics survive.
            issues = tuple((tuple(item["loc"]), item["type"]) for item in error.errors(
                include_input=False, include_context=False, include_url=False,
            )[:4])
        # Outside the except block: do not attach the input-owning ValidationError.
        raise _contract_error("dto_validation_failed", error_type="ValidationError", issues=issues)
