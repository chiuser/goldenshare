from ..index_kline_calculations import INDEX_BOLL_KEY, INDEX_KDJ_KEY, INDEX_MACD_KEY
from ..index_kline_result import IndexCalculationFields
from .boll import build_index_boll_factors
from .kdj import build_index_kdj_factors
from .ma import build_index_ma_factors
from .macd import build_index_macd_factors


def build_index_common_factors(fields_by_calculation: IndexCalculationFields, row_index: int):
    return dict(
        ma=build_index_ma_factors(fields_by_calculation, row_index),
        boll=build_index_boll_factors(fields_by_calculation[INDEX_BOLL_KEY], row_index),
        macd=build_index_macd_factors(fields_by_calculation[INDEX_MACD_KEY], row_index),
        kdj=build_index_kdj_factors(fields_by_calculation[INDEX_KDJ_KEY], row_index),
    )
