"""Compose calculated index daily K-lines from the already selected page."""

from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Any, cast

from goldenshare_technical_indicators.contracts import CalculationResult
from goldenshare_technical_indicators.sources.contracts import CalculationWithSource

from src.biz.schemas.wealth.market.index_detail import (
    IndexDetailIdentityDto,
    IndexDetailIndexRefDto,
    IndexDetailKlineResponseDto,
    IndexDetailSseDailyKlineResponseDto,
    IndexDetailSseKlineMetaDto,
    IndexKlineBarDto,
    IndexKlineFactorsDto,
    IndexSseDailyKlineBarDto,
    IndexSseDailyKlineFactorsDto,
    LocalIndexDetailDailyKlineResponseDto,
    LocalIndexDetailSseDailyKlineResponseDto,
)
from src.biz.schemas.wealth.market.nine_turn import NineTurnMarkerDto
from src.biz.services.wealth.market.nine_turn.nine_turn_response_policy import build_nine_turn_marker

from .compose.common import build_index_common_factors
from .compose.trend_channel import build_index_trend_channel_factors
from .index_detail_field_mapper import MarketPageContextLike, build_index_kline_bar_fields, build_page_context
from .index_detail_status_resolver import IndexDetailStatusResolver
from .index_detail_universe import IndexDetailQueryError
from .index_kline_calculations import index_daily_calculations
from .index_kline_result import (
    IndexCalculationFields,
    IndexFieldColumns,
    count_calculated_kline_missing,
    validate_index_common_calculation_fields,
)


@dataclass(frozen=True, slots=True)
class IndexDailyCalculatedPage:
    rows: list[dict[str, Any]]
    common_fields: IndexCalculationFields
    trend_fields: IndexFieldColumns | None
    nine_turn_markers: list[NineTurnMarkerDto]
    missing_count: int


def _split_daily_results(ts_code, result, *, include_price_and_nine_turn):
    expected = {(item["calculation_id"], tuple(sorted(item["parameters"].items())))
                for item in index_daily_calculations(ts_code, include_price_and_nine_turn=include_price_and_nine_turn)}
    actual = {(item.calculation_id, tuple(sorted(item.parameters))): item for item in result.calculations}
    versions = {"ma": "1.0.0", "boll": "1.0.0", "macd": "2.0.0", "kdj": "2.0.0",
                "price": "1.0.0", "nineturn": "1.0.0", "trend_channel": "1.0.0"}
    if (len(actual) != len(result.calculations) or set(actual) != expected
            or any(item.algorithm_version != versions[item.calculation_id] for item in result.calculations)):
        raise IndexDetailQueryError(f"{ts_code} 本页指标实例、参数或版本不完整")
    channel = None
    if ts_code == "000001.SH":
        channel = dict(actual[("trend_channel", ())].fields)
        if len(actual[("trend_channel", ())].fields) != 4 or set(channel) != {"short_upper", "short_lower", "long_upper", "long_lower"} or any(
            len(values) != len(result.times) or any(type(v) not in (int, float) or not isfinite(v) for v in values)
            for values in channel.values()
        ):
            raise IndexDetailQueryError(f"{ts_code} 趋势通道结果字段不完整或数值无效")
    indicators = tuple(item for item in result.calculations if item.calculation_id not in ("price", "nineturn", "trend_channel"))
    direct = {item.calculation_id: item for item in result.calculations if item.calculation_id in ("price", "nineturn")}
    return indicators, direct, channel


def _build_nine_turn_markers(ts_code, dates, calculation) -> list[NineTurnMarkerDto]:
    counts = dict(calculation.fields)
    up = counts.get("up_count", ())
    down = counts.get("down_count", ())
    if len(up) != len(dates) or len(down) != len(dates):
        raise IndexDetailQueryError(f"{ts_code} 九转结果与本页行情根数不一致")

    markers = []
    for day, up_count, down_count in zip(dates, up, down, strict=True):
        if (up_count not in range(14) or down_count not in range(14)
                or (up_count > 0 and down_count > 0)):
            raise IndexDetailQueryError(f"{ts_code} {day} 九转计数无效")
        marker = build_nine_turn_marker(
            trade_date=day, trade_time=None, up_count=int(up_count), down_count=int(down_count),
        )
        if marker is not None:
            markers.append(marker)
    return markers


class IndexDailyKlineService:
    @staticmethod
    def prepare_local_result(ts_code: str, calculated: CalculationWithSource) -> IndexDailyCalculatedPage:
        result = cast(CalculationResult, calculated.result)
        facts = calculated.source_facts
        dates = tuple(bar.trade_date for bar in facts.target_bars)
        if dates != result.times or len(dates) != result.range.count:
            raise IndexDetailQueryError(f"{ts_code} 指标结果日期或根数与本页行情不一致")
        indicators, direct_outputs, trend_fields = _split_daily_results(
            ts_code, result, include_price_and_nine_turn=True,
        )
        values = dict(direct_outputs["price"].fields)
        markers = _build_nine_turn_markers(ts_code, dates, direct_outputs["nineturn"])
        rows = []
        for index, bar in enumerate(facts.target_bars):
            vol, amount = values["volume"][index], values["amount"][index]
            rows.append({
                "trade_date": bar.trade_date,
                **{name: values[name][index] for name in ("open", "high", "low", "close")},
                "pre_close": bar.pre_close, "change": bar.change_amount, "pct_change": bar.pct_chg,
                "vol": None if vol is None else vol / 100,
                "amount": None if amount is None else amount / 1000,
            })
        common_fields = validate_index_common_calculation_fields(ts_code, indicators, len(rows))
        missing_count = count_calculated_kline_missing(rows, common_fields, calculated.selection.preceding_rows)
        return IndexDailyCalculatedPage(rows, common_fields, trend_fields, markers, missing_count)

    @staticmethod
    def prepare_prod_result(
        ts_code: str, rows: list[dict[str, Any]], result: CalculationResult, preceding_rows: int,
    ) -> IndexDailyCalculatedPage:
        if result.range.count != len(rows):
            raise IndexDetailQueryError(f"{ts_code} 指标结果日期或根数与本页行情不一致")
        indicators, _, trend_fields = _split_daily_results(ts_code, result, include_price_and_nine_turn=False)
        common_fields = validate_index_common_calculation_fields(ts_code, indicators, len(rows))
        missing_count = count_calculated_kline_missing(rows, common_fields, preceding_rows)
        return IndexDailyCalculatedPage(rows, common_fields, trend_fields, [], missing_count)

    @staticmethod
    def assemble(
        *, context: MarketPageContextLike, identity: IndexDetailIdentityDto,
        page: IndexDailyCalculatedPage | None, start_date: date | None, limit: int,
        next_end: date | None, include_nine_turn: bool,
    ) -> tuple[IndexDetailKlineResponseDto, int | None]:
        rows = page.rows if page is not None else []
        missing_count = page.missing_count if page is not None else None
        query_end = context.trade_date
        expected_end = query_end if context.is_trading_day else context.prev_trade_date
        data_status = IndexDetailStatusResolver.resolve(
            expected_trade_date=expected_end or query_end,
            observed_trade_date=rows[-1]["trade_date"] if rows else None,
            empty=not rows, partial=bool(missing_count),
        )
        is_sse = identity.tsCode == "000001.SH"
        bars: list[IndexKlineBarDto] = []
        if page is not None:
            for index, row in enumerate(rows):
                trend_channel = (
                    build_index_trend_channel_factors(cast(IndexFieldColumns, page.trend_fields), index)
                    if is_sse else None
                )
                bar_fields = build_index_kline_bar_fields(row)
                common_factors = build_index_common_factors(page.common_fields, index)
                if trend_channel is None:
                    bar = IndexKlineBarDto(**bar_fields, factors=IndexKlineFactorsDto(**common_factors))
                else:
                    bar = IndexSseDailyKlineBarDto(
                        **bar_fields,
                        factors=IndexSseDailyKlineFactorsDto(**common_factors, trendChannel=trend_channel),
                    )
                bars.append(bar)
        fields = dict(
            pageContext=build_page_context(context),
            indexRef=IndexDetailIndexRefDto(tsCode=identity.tsCode, name=identity.name),
            period="day",
            bars=bars,
            meta=IndexDetailSseKlineMetaDto(
                count=len(rows), limit=limit, startDate=start_date, endDate=query_end, nextEndDate=next_end,
            ),
            dataStatus=data_status,
        )
        if include_nine_turn:
            model = LocalIndexDetailSseDailyKlineResponseDto if is_sse else LocalIndexDetailDailyKlineResponseDto
            return model(**fields, nineTurnMarkers=page.nine_turn_markers if page is not None else []), missing_count
        model = IndexDetailSseDailyKlineResponseDto if is_sse else IndexDetailKlineResponseDto
        return model(**fields), missing_count
