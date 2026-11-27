"""Compose index weekly and monthly K-lines from the selected page and calculation."""

from collections.abc import Mapping
from datetime import date
from typing import Any, cast

from goldenshare_technical_indicators.contracts import CalculationResult

from src.biz.schemas.wealth.market.index_detail import (
    IndexDetailIndexRefDto, IndexDetailKlineResponseDto, IndexDetailSseKlineMetaDto,
    IndexKlineBarDto, IndexKlineFactorsDto,
)

from .compose.common import build_index_common_factors
from .index_detail_field_mapper import MarketPageContextLike, build_index_kline_bar_fields, build_page_context
from .index_detail_status_resolver import IndexDetailStatusResolver
from .index_detail_universe import IndexDetailQueryError
from .index_kline_result import count_calculated_kline_missing, validate_index_common_calculation_fields


class IndexPeriodKlineService:
    @staticmethod
    def assemble(
        *, ts_code: str, context: MarketPageContextLike, index_ref: IndexDetailIndexRefDto,
        auxiliary_rows: tuple[Mapping[str, Any], ...], periods: tuple[date, ...], cutoffs: tuple[date, ...],
        end: date, expected: date, next_end: date | None, result: CalculationResult | None, pct_scale: int,
        period: str, start_date: date | None, limit: int,
    ) -> tuple[IndexDetailKlineResponseDto, int | None]:
        rows, common_fields, missing_count = [], {}, None
        if auxiliary_rows:
            result = cast(CalculationResult, result)
            if (result.times != periods or result.source_as_of != cutoffs
                    or result.range.count != len(auxiliary_rows)):
                raise IndexDetailQueryError(f"{ts_code} {period} 指标结果日期或根数与本页行情不一致")
            price = next(item for item in result.calculations if item.calculation_id == "price")
            prices = dict(price.fields)
            fields = ("open", "high", "low", "close", "volume", "amount")
            if any(name not in prices or len(prices[name]) != len(auxiliary_rows) for name in fields):
                raise IndexDetailQueryError(f"{ts_code} {period} 行情结果字段不完整")
            for index, (day, auxiliary) in enumerate(zip(cutoffs, auxiliary_rows, strict=True)):
                volume, amount = prices["volume"][index], prices["amount"][index]
                pct = auxiliary["pct_chg"]
                rows.append({
                    "trade_date": day,
                    **{name: prices[name][index] for name in fields[:4]},
                    "vol": None if volume is None else volume / 100,
                    "amount": None if amount is None else amount / 1000,
                    "pre_close": auxiliary["pre_close"],
                    "change": auxiliary["change_amount"],
                    "pct_change": None if pct is None else pct * pct_scale,
                })
            indicators = tuple(item for item in result.calculations if item is not price)
            common_fields = validate_index_common_calculation_fields(ts_code, indicators, len(rows))
            missing_count = count_calculated_kline_missing(
                rows, common_fields, result.statistics.source_rows - result.range.count,
            )
        data_status = IndexDetailStatusResolver.resolve(
            expected_trade_date=expected, observed_trade_date=cutoffs[-1] if rows else None,
            empty=not rows, partial=bool(missing_count),
        )
        return IndexDetailKlineResponseDto(
            pageContext=build_page_context(context), indexRef=index_ref, period=period,
            bars=[
                IndexKlineBarDto(
                    **build_index_kline_bar_fields(row),
                    factors=IndexKlineFactorsDto(**build_index_common_factors(common_fields, index)),
                )
                for index, row in enumerate(rows)
            ],
            meta=IndexDetailSseKlineMetaDto(
                count=len(rows), limit=limit, startDate=start_date, endDate=end, nextEndDate=next_end,
            ),
            dataStatus=data_status,
        ), missing_count
