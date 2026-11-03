"""Literal expression contracts from recognition LLD 21.2.

Only the closed expression union is exercised. No current/old forecast is
generated, no response fixture or market material is read, and no formula is
evaluated by these schema tests. Numeric expectations are literal contracts.
"""
from copy import deepcopy

import pytest
from pydantic import TypeAdapter, ValidationError

from src.biz.schemas.wealth.market.index_detail_xxm_forecast import ForecastExpression


EXPRESSION = TypeAdapter(ForecastExpression)
LEAF = {"op": "affine", "pCoefficient": 0, "cCoefficient": 1, "constant": 0}
MACD = {"op": "macd", "e12": 13, "e26": 27, "dea": 0,
        "prefixBars": 0, "prefixClose": None, "target": True, "field": "hist"}


@pytest.mark.parametrize("value", [
    LEAF,
    {"op": "scale", "arg": LEAF, "factor": 2},
    {"op": "abs", "arg": LEAF},
    {"op": "sub", "args": [LEAF, LEAF]},
    {"op": "add", "args": [LEAF, LEAF]},
    {"op": "div", "arg": {"op": "scale", "arg": LEAF, "factor": 11}, "divisor": 13},
    {"op": "round3", "arg": {"op": "add", "args": [MACD, LEAF]}, "guard": 1e-10},
    MACD,
    dict(MACD, prefixBars=19, target=True, field="dif"),
    dict(MACD, prefixBars=20, target=False),
    dict(MACD, prefixBars=1, target=False),
    dict(MACD, prefixBars=1, prefixClose=100),
    dict(MACD, prefixBars=19, prefixClose=100.5),
])
def test_literal_legacy_and_ordered_nodes_are_accepted(value):
    parsed = EXPRESSION.validate_python(deepcopy(value))
    assert parsed.model_dump(mode='json') == value


@pytest.mark.parametrize("op", ["add", "sub"])
@pytest.mark.parametrize("args", [[], [LEAF], [LEAF, LEAF, LEAF], None, {"left": LEAF, "right": LEAF}])
def test_binary_nodes_require_exactly_two_children(op, args):
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python({"op": op, "args": args})


@pytest.mark.parametrize("divisor", [0, -0.0, True, "13", None, float("nan"), float("inf"), float("-inf")])
def test_division_rejects_zero_coerced_and_nonfinite_divisors(divisor):
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python({"op": "div", "arg": LEAF, "divisor": divisor})


@pytest.mark.parametrize("field", ["e12", "e26", "dea"])
@pytest.mark.parametrize("value", [True, "13", None, float("nan"), float("inf"), float("-inf")])
def test_macd_state_is_original_finite_number(field, value):
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python(dict(MACD, **{field: value}))


@pytest.mark.parametrize("prefix,target", [
    (0, False), (-1, True), (20, True), (21, False),
    (True, True), (1.0, True), ("1", True), (1, 0), (1, 1), (1, "true"),
])
def test_macd_uses_strict_integer_boolean_and_one_to_twenty_steps(prefix, target):
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python(dict(MACD, prefixBars=prefix, target=target))


@pytest.mark.parametrize("field", ["dea", "close", "DIF", None, 1])
def test_macd_only_returns_raw_dif_or_hist(field):
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python(dict(MACD, field=field))


@pytest.mark.parametrize("prefix_close", [True, "100", 0, -0.0, -1, float("nan"), float("inf"), float("-inf")])
def test_fixed_prefix_close_is_original_finite_positive_price(prefix_close):
    # A real prefix is present, so this tests the price itself rather than
    # accidentally failing the independent no-unused-prefix requirement.
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python(dict(MACD, prefixBars=1, prefixClose=prefix_close))


def test_prefix_close_is_required_and_cannot_be_attached_to_zero_prefix():
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python({key: value for key, value in MACD.items() if key != "prefixClose"})
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python(dict(MACD, prefixClose=100))


@pytest.mark.parametrize("value", [
    dict(MACD, unexpected=1),
    {key: item for key, item in MACD.items() if key != "dea"},
    {"op": "add", "args": [LEAF, LEAF], "extra": 1},
    {"op": "div", "arg": LEAF, "divisor": 13, "extra": 1},
    {"op": "round3", "arg": {"op": "unknown"}, "guard": 1e-10},
    {"op": "round3", "arg": MACD, "guard": 0},
    {"op": "round3", "arg": MACD, "guard": True},
    {"op": "round3", "arg": MACD, "guard": "1e-10"},
    dict(LEAF, constant=True),
    dict(LEAF, pCoefficient="0"),
    {"op": "scale", "arg": LEAF, "factor": float("inf")},
])
def test_closed_nodes_reject_extra_missing_and_invalid_nested_fields(value):
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python(value)


def test_recursive_cycle_is_rejected_but_shared_legal_children_are_accepted():
    cycle = {"op": "abs"}
    cycle["arg"] = cycle
    with pytest.raises(ValidationError):
        EXPRESSION.validate_python(cycle)
    assert EXPRESSION.validate_python({"op": "add", "args": [LEAF, LEAF]}).op == "add"


def test_twenty_step_compact_node_stays_small_and_round_trips():
    # Twenty hypothetical advances use one literal descriptor, not a copied
    # twenty-level EMA tree. The existing response limit remains 32768 bytes.
    value = {"op": "round3", "arg": dict(MACD, prefixBars=19), "guard": 1e-10}
    body = EXPRESSION.dump_json(EXPRESSION.validate_python(value))
    assert len(body) < 256
    assert EXPRESSION.validate_json(body).model_dump() == value
