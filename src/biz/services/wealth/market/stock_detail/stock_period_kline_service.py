"""Stock detail dates and response mapping for pre-adjusted period candles."""

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from goldenshare_technical_indicators.contracts import CalculationRequest

from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContext, MarketPageContextQuery
from src.biz.queries.wealth.market.stock_detail.stock_detail_query_service import StockDetailQueryService
from src.biz.schemas.wealth.market.stock_detail import (
    LocalStockKlineMetaDto, StockDetailDataStatusDto, StockDetailDebugInfoDto,
    StockDetailPeriodKlineResponseDto, StockDetailStockRefDto,
)
from src.biz.services.wealth.market.nine_turn.nine_turn_response_policy import build_nine_turn_marker
from src.foundation.clients.technical_indicator_index_period import period_bounds
from src.foundation.clients.technical_indicator_stock_daily import scheduled_stock_days

from .stock_daily_kline_calculations import stock_common_calculations
from .stock_daily_kline_contracts import StockDailyKlineRow
from .stock_daily_kline_service import _calculation_key, build_kline_factors
from .stock_detail_field_mapper import build_kline_bar, build_page_context


@dataclass(frozen=True, slots=True)
class StockPeriodContext:
    page: MarketPageContext
    stock: StockDetailStockRefDto
    end: date
    expected_days: tuple[date, ...]

    @property
    def first_page(self):
        return self.end == self.page.trade_date


def validate_stock_period_request(request):
    if request.adjustment != "forward":
        raise ValueError("股票周月线只支持 adjustment=forward")
    if request.period == "week" and not 1 <= request.limit <= 100:
        raise ValueError("股票周线 limit 必须在 1 到 100 之间")
    if request.start_date is not None:
        raise ValueError("股票周月线按截止日期读取")


class StockPeriodKlineService:
    def __init__(self, reference_data):
        self.reference_data = reference_data
        self.market = MarketPageContextQuery()
        self.stocks = StockDetailQueryService(reference_data)

    def prepare(self, session, request, *, remaining_seconds, load_suspensions):
        page_end = request.trade_date
        if page_end is None or request.end_date in (None, page_end):
            page, calendar = self.market.resolve_sse_period_context(
                session, period=request.period, requested_trade_date=page_end,
                reference_data=self.reference_data, timeout_seconds=remaining_seconds(),
            )
        else:
            page = self.market.resolve_context(session, market="CN_A", requested_trade_date=page_end,
                                               reference_data=self.reference_data, timeout_seconds=remaining_seconds())
            calendar = ()
        stock = self.stocks.load_security_or_raise(session, ts_code=request.ts_code, timeout_seconds=remaining_seconds())
        end = request.end_date or page.trade_date
        eligible_days = ()
        if end == page.trade_date:
            start, _ = period_bounds(end, request.period)
            days = tuple(scheduled_stock_days(((stamp, opened) for stamp, opened, _ in calendar),
                                             ((stock.list_date, stock.delist_date),), start, end))
            suspended = load_suspensions(stock.ts_code, days) if days else set()
            eligible_days = tuple(day for day in days if day not in suspended)
        return StockPeriodContext(page, StockDetailStockRefDto(tsCode=stock.ts_code, name=stock.name), end, eligible_days)

    @staticmethod
    def calculate(context, request, indicators):
        weekly = request.period == "week"
        return indicators.calculate_with_source(CalculationRequest(
            security_type="stock", ts_code=context.stock.tsCode, period=request.period, adjustment="qfq",
            end=datetime.combine(context.end, time.min, ZoneInfo("Asia/Shanghai")),
            latest_rows=request.limit if weekly else None,
            calculations=stock_common_calculations(include_nine_turn=True),
        ), output_rows=100 if weekly else None, warmup_error_budget=0.00001 if weekly else None,
            require_current_period_end_date=context.first_page)

    @staticmethod
    def assemble(context, request, calculation, *, max_output_rows, price_source):
        result = calculation.result
        facts = calculation.source_facts
        current = facts.current_period_bar
        coverage = current.end_date if current else None
        expected = context.expected_days[-1] if context.expected_days else None
        current_display = next((day for day in reversed(context.expected_days) if coverage is not None and day <= coverage),
                               coverage)
        bars, markers = [], []
        if result is not None:
            fields = {_calculation_key(item.calculation_id, item.parameters): dict(item.fields)
                      for item in result.calculations}
            fixed = {key[0]: values for key, values in fields.items() if key[0] != "ma"}
            price, nine_turn = fixed["price"], fixed["nineturn"]
            for index, (label, metadata) in enumerate(zip(result.source_as_of, result.period_bars, strict=True)):
                display = current_display if current and current.period_start == metadata.period_start else label
                volume, amount = price["volume"][index], price["amount"][index]
                bars.append(build_kline_bar(StockDailyKlineRow(
                    trade_date=display, open_qfq=price["open"][index], high_qfq=price["high"][index],
                    low_qfq=price["low"][index], close_qfq=price["close"][index], pct_chg=metadata.pct_chg,
                    vol=None if volume is None else volume / 100, amount=None if amount is None else amount / 1000,
                    pre_close=None, change=None, turnover_rate=None, volume_ratio=None,
                ), build_kline_factors(fields, fixed, index)))
                marker = build_nine_turn_marker(trade_date=display, trade_time=None,
                                               up_count=int(nine_turn["up_count"][index]),
                                               down_count=int(nine_turn["down_count"][index]))
                if marker is not None:
                    markers.append(marker)
        observed = bars[-1].tradeDate if bars else None
        status, note = ("READY" if bars else "EMPTY"), None
        if expected is not None and (coverage is None or coverage < expected):
            status = "DELAYED"
            label = "周线" if request.period == "week" else "月线"
            if current is not None and coverage is None:
                note = f"暂未确认最新{label}已更新"
            else:
                note = f"{label}尚未更新到 {expected.isoformat()}"
            if observed is not None:
                note += f"，当前显示到 {observed.isoformat()}"
        limit = request.limit if request.period == "week" else max_output_rows
        return StockDetailPeriodKlineResponseDto(
            pageContext=build_page_context(context.page), stockRef=context.stock, period=request.period,
            adjustment="forward", sourceAdjustment="qfq", bars=bars, nineTurnMarkers=markers,
            meta=LocalStockKlineMetaDto(count=len(bars), limit=limit, endDate=context.end,
                                       nextEndDate=facts.previous_target_date),
            dataStatus=StockDetailDataStatusDto(status=status, note=note, observedTradeDate=observed,
                                                 expectedTradeDate=expected or context.page.trade_date),
            debugInfo=StockDetailDebugInfoDto(sourceTables=[price_source], query={
                "tsCode": context.stock.tsCode, "period": request.period, "endDate": context.end.isoformat(),
                "expectedTradeDate": (expected or context.page.trade_date).isoformat(),
                "observedTradeDate": observed.isoformat() if observed is not None else None, "limit": limit,
            }) if request.debug else None,
        )
