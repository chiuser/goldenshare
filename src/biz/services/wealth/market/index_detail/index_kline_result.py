"""Validate shared index indicators and count missing values in the current page."""

from collections.abc import Mapping, Sequence
from typing import Any

from goldenshare_technical_indicators.contracts import CalculationValues, Parameters

from .index_detail_universe import IndexDetailQueryError
from .index_kline_calculations import (
    INDEX_BOLL_KEY, INDEX_BOLL_PERIOD, INDEX_COMMON_CALCULATIONS, INDEX_KDJ_KEY, INDEX_MACD_KEY, INDEX_MA_PERIODS,
)


IndexFieldColumns = dict[str, tuple[float | None, ...]]
IndexCalculationFields = dict[tuple[str, Parameters], IndexFieldColumns]

_PRICE_FIELDS = ("open", "high", "low", "close", "pre_close", "change", "pct_change", "vol", "amount")
_COMMON_FIELDS = (
    *(("value",) for _ in INDEX_MA_PERIODS),
    ("upper", "middle", "lower"),
    ("dif", "dea", "hist"),
    ("k", "d", "j"),
)


def validate_index_common_calculation_fields(
    ts_code: str, calculations: tuple[CalculationValues, ...], row_count: int,
) -> IndexCalculationFields:
    instances = {
        (item.calculation_id, tuple(sorted(dict(item.parameters).items()))): dict(item.fields)
        for item in calculations
    }
    if len(calculations) != len(_COMMON_FIELDS) or len(instances) != len(_COMMON_FIELDS):
        raise IndexDetailQueryError(f"{ts_code} 本页指标实例不完整")
    for request, fields in zip(INDEX_COMMON_CALCULATIONS, _COMMON_FIELDS, strict=True):
        key = request["calculation_id"], tuple(sorted(request["parameters"].items()))
        values_by_field = instances.get(key, {})
        for field in fields:
            values = values_by_field.get(field)
            if values is None or len(values) != row_count:
                raise IndexDetailQueryError(f"{ts_code} 指标结果字段不完整：{key[0]}.{field}")
    return instances


def count_calculated_kline_missing(
    rows: Sequence[Mapping[str, Any]], fields_by_calculation: IndexCalculationFields, preceding_rows: int,
) -> int:
    boll = fields_by_calculation[INDEX_BOLL_KEY]
    macd = fields_by_calculation[INDEX_MACD_KEY]
    kdj = fields_by_calculation[INDEX_KDJ_KEY]
    required = (*(macd[name] for name in ("dif", "dea", "hist")), *(kdj[name] for name in ("k", "d", "j")))
    windowed = (
        *((fields_by_calculation[("ma", (("period", period),))]["value"], period) for period in INDEX_MA_PERIODS),
        *((boll[name], INDEX_BOLL_PERIOD) for name in ("upper", "middle", "lower")),
    )
    return sum(
        sum(row[name] is None for name in _PRICE_FIELDS)
        + sum(values[index] is None for values in required)
        + sum(values[index] is None and preceding_rows + index + 1 >= period for values, period in windowed)
        for index, row in enumerate(rows)
    )
