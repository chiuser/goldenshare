"""MACD definition; all coefficients and recursion will be SQL in D3."""

from ..calculation import CalculationDefinition, OutputField, ParameterSpec

DEFINITION = CalculationDefinition(
    calculation_id="macd", algorithm_version="1.0.0", description="两EMA、DIF、DEA及两倍差值柱",
    parameter_specs=(ParameterSpec("fast", "positive_integer", 12), ParameterSpec("slow", "positive_integer", 26), ParameterSpec("signal", "positive_integer", 9)),
    input_fields=frozenset({"close"}),
    output_fields=tuple(OutputField(name, name, "DOUBLE", False, "首条DIF/DEA/柱严格0") for name in ("dif", "dea", "hist")),
    initialization="首个close初始化两EMA，DEA为0", history_rule="从来源约定起点递推；展示/分页不重置",
    units=tuple((name, "source_price_unit") for name in ("dif", "dea", "hist")),
    parameter_relations=(("fast", "slow"),),
)
