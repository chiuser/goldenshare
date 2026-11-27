from src.biz.schemas.wealth.market.index_detail import IndexKdjDto

from ..index_detail_value_conversion import to_float
from ..index_kline_result import IndexFieldColumns


def build_index_kdj_factors(fields: IndexFieldColumns, row_index: int) -> IndexKdjDto:
    return IndexKdjDto(
        k=to_float(fields["k"][row_index]),
        d=to_float(fields["d"][row_index]),
        j=to_float(fields["j"][row_index]),
    )
