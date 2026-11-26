"""Map already validated calculation values; business assemblers choose indicators."""

from src.biz.schemas.wealth.market.stock_detail import (
    StockBollDto, StockKdjDto, StockMacdDto, StockMovingAverageDto, StockTrendChannelFactorsDto,
)

from .stock_detail_field_mapper import to_float


def stock_calculation_key(calculation_id, parameters):
    return calculation_id, tuple(sorted(dict(parameters).items()))


def index_stock_calculation_results(calculations):
    return {stock_calculation_key(item.calculation_id, item.parameters): dict(item.fields)
            for item in calculations}


def build_stock_ma_factors(results, index):
    return StockMovingAverageDto(**{
        f"ma{period}": to_float(results[("ma", (("period", period),))]["value"][index])
        for period in (5, 10, 20, 30, 60, 90, 250)
    })


def build_stock_boll_factors(fields, index):
    return StockBollDto(**{name: to_float(fields[name][index]) for name in ("upper", "middle", "lower")})


def build_stock_macd_factors(fields, index):
    return StockMacdDto(dif=to_float(fields["dif"][index]), dea=to_float(fields["dea"][index]),
                        macd=to_float(fields["hist"][index]))


def build_stock_kdj_factors(fields, index):
    return StockKdjDto(**{name: to_float(fields[name][index]) for name in ("k", "d", "j")})


def build_stock_trend_channel_factors(fields, index):
    return StockTrendChannelFactorsDto(
        shortUpper=fields["short_upper"][index], shortLower=fields["short_lower"][index],
        longUpper=fields["long_upper"][index], longLower=fields["long_lower"][index],
    )


def build_stock_common_factors(results, index):
    fixed = {key[0]: values for key, values in results.items() if key[0] != "ma"}
    return dict(
        ma=build_stock_ma_factors(results, index),
        boll=build_stock_boll_factors(fixed["boll"], index),
        macd=build_stock_macd_factors(fixed["macd"], index),
        kdj=build_stock_kdj_factors(fixed["kdj"], index),
    )
