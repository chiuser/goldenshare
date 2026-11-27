from src.biz.schemas.wealth.market.index_detail import IndexBollDto

from ..index_detail_value_conversion import to_float
from ..index_kline_result import IndexFieldColumns


def build_index_boll_factors(fields: IndexFieldColumns, row_index: int) -> IndexBollDto:
    return IndexBollDto(
        upper=to_float(fields["upper"][row_index]),
        middle=to_float(fields["middle"][row_index]),
        lower=to_float(fields["lower"][row_index]),
    )
