from src.biz.schemas.wealth.market.index_detail import IndexTrendChannelFactorsDto

from ..index_kline_result import IndexFieldColumns


def build_index_trend_channel_factors(fields: IndexFieldColumns, row_index: int) -> IndexTrendChannelFactorsDto:
    return IndexTrendChannelFactorsDto(
        shortUpper=fields["short_upper"][row_index], shortLower=fields["short_lower"][row_index],
        longUpper=fields["long_upper"][row_index], longLower=fields["long_lower"][row_index],
    )
