from src.biz.schemas.wealth.market.index_detail import IndexMacdDto

from ..index_detail_value_conversion import to_float
from ..index_kline_result import IndexFieldColumns


def build_index_macd_factors(fields: IndexFieldColumns, row_index: int) -> IndexMacdDto:
    return IndexMacdDto(
        dif=to_float(fields["dif"][row_index]),
        dea=to_float(fields["dea"][row_index]),
        macd=to_float(fields["hist"][row_index]),
    )
