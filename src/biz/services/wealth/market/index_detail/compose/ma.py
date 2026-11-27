from src.biz.schemas.wealth.market.index_detail import IndexMovingAverageDto

from ..index_detail_value_conversion import to_float
from ..index_kline_calculations import INDEX_MA_PERIODS
from ..index_kline_result import IndexCalculationFields


def build_index_ma_factors(fields_by_calculation: IndexCalculationFields, row_index: int) -> IndexMovingAverageDto:
    return IndexMovingAverageDto(**{
        f"ma{period}": to_float(fields_by_calculation[("ma", (("period", period),))]["value"][row_index])
        for period in INDEX_MA_PERIODS
    })
