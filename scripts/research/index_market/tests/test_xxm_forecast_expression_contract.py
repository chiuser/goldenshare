"""LLD 5.4/22.15 F02: literal contracts for the six single-bar JSON nodes.

No forecast or formula is executed. Expected fields are independent literals;
negative numeric tests start from a valid five-field MACD descriptor.
"""
from copy import deepcopy

import pytest
from pydantic import TypeAdapter, ValidationError

from src.biz.schemas.wealth.market.index_detail_xxm_forecast import ForecastExpression


EXPRESSION = TypeAdapter(ForecastExpression)
LEAF = {"op": "affine", "pCoefficient": 0, "cCoefficient": 1, "constant": 0}
MACD = {"op": "macd", "e12": 13, "e26": 27, "dea": 0, "field": "hist"}
NODES = [
    LEAF,
    {"op": "affine", "pCoefficient": 0, "cCoefficient": 0, "constant": -20},
    {"op": "scale", "arg": LEAF, "factor": 2},
    {"op": "abs", "arg": LEAF},
    {"op": "sub", "args": [LEAF, MACD]},
    MACD,
    dict(MACD, field="dif"),
    {"op": "round3", "arg": MACD, "guard": 1e-10},
]


@pytest.mark.parametrize("value", NODES)
def test_single_bar_nodes_and_nested_json_round_trip(value):
    parsed = EXPRESSION.validate_python(deepcopy(value))
    assert parsed.model_dump(mode="json") == value
    assert EXPRESSION.validate_json(EXPRESSION.dump_json(parsed)).model_dump() == value


@pytest.mark.parametrize("args", [[], [LEAF], [LEAF, LEAF, LEAF], None, {"left": LEAF, "right": LEAF}])
def test_sub_requires_exactly_two_children(args):
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python({"op": "sub", "args": args})


@pytest.mark.parametrize("field", ["e12", "e26", "dea"])
@pytest.mark.parametrize("value", [True, "13", None, float("nan"), float("inf"), float("-inf")])
def test_macd_state_is_original_finite_number(field, value):
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python(dict(MACD, **{field: value}))


@pytest.mark.parametrize("field", ["dea", "close", "DIF", None, 1])
def test_macd_only_returns_raw_dif_or_hist(field):
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python(dict(MACD, field=field))


@pytest.mark.parametrize("field", ["op", "e12", "e26", "dea", "field"])
def test_macd_requires_each_single_bar_field(field):
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python({key: value for key, value in MACD.items() if key != field})


@pytest.mark.parametrize("value", [NODES[0], *NODES[2:6], NODES[7]])
def test_each_node_rejects_extra_fields(value):
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python(dict(value, unexpected=1))


@pytest.mark.parametrize("guard", [0, -1, True, "1e-10", None, float("nan"), float("inf")])
def test_round3_requires_original_finite_positive_guard(guard):
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python({"op": "round3", "arg": MACD, "guard": guard})


@pytest.mark.parametrize("field", ["pCoefficient", "cCoefficient", "constant"])
@pytest.mark.parametrize("value", [True, "1", None, float("nan"), float("inf")])
def test_affine_numeric_fields_do_not_coerce_or_accept_nonfinite(field, value):
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python(dict(LEAF, **{field: value}))


@pytest.mark.parametrize("value", [dict(LEAF, pCoefficient=1), dict(LEAF, cCoefficient=2),
                                    dict(LEAF, constant=1)])
def test_affine_allows_only_constant_or_current_close(value):
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python(value)


@pytest.mark.parametrize("value", [
    {"op": "add", "args": [LEAF, LEAF]},
    {"op": "div", "arg": LEAF, "divisor": 13},
    dict(MACD, prefixBars=1), dict(MACD, prefixClose=100), dict(MACD, target=True),
])
def test_old_nodes_and_prefix_fields_are_rejected(value):
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python(value)


@pytest.mark.parametrize("value", [
    {"op": "scale", "arg": LEAF, "factor": float("inf")},
    {"op": "abs"},
    {"op": "sub", "args": [LEAF, {"op": "unknown"}]},
    {"op": "round3", "arg": {"op": "unknown"}, "guard": 1e-10},
])
def test_invalid_nested_json_and_missing_child_are_rejected(value):
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python(value)
