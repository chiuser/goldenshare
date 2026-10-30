"""P3 step 2 independent mathematics, LLD M1-M3 / PF08, PF15-PF18.

No market files, database, API or old forecasts are read. Literal expectations
and Fraction bounds below are independent of the boundary-solving helpers.
"""
from copy import deepcopy
from fractions import Fraction
import json
import math
import sys

import pytest

from src.biz.services.wealth.market.index_detail_xxm.forecast_expression import (
    _expression_envelope, literal,
)
from src.biz.services.wealth.market.index_detail_xxm.forecast_expression import (
    comparison_envelope, condition_options, evaluate_expression, expression_options,
    macd_expression, one_step_macd_envelope, one_step_source_envelope, sourced,
)
from src.biz.services.wealth.market.index_detail_xxm.forecast_math import (
    Interval, as_interval, candidate_prices, condition, const, difference,
    display_range, intersect, merge, scaled, solve_comparison, solve_predicates,
    source_options, subtract,
)
from src.biz.services.wealth.market.index_detail_xxm.projection import ProjectionState


P = ProjectionState(13., 27., 0.)
C = dict(op="affine", pCoefficient=0., cCoefficient=1., constant=0.)
CHECK = lambda: None


def compare(left, op, right, *, projection=P, period="m60", domain=Interval()):
    return solve_comparison(left, op, right, domain, projection=projection, period=period, check=CHECK)


def membership(ranges, value):
    return any(region.contains(value) for region in ranges)


@pytest.mark.parametrize("op,true_at,false_at", [
    ("gt", (10.000000000000002, 11.), (1., 10.)),
    ("ge", (10., 11.), (1., 9.999999999999998)),
    ("lt", (1., 9.999999999999998), (10., 11.)),
    ("le", (1., 10.), (10.000000000000002, 11.)),
    ("eq", (10.,), (1., 9.999999999999998, 10.000000000000002)),
])
def test_pf15_literal_price_comparisons_have_exact_float_boundaries(op, true_at, false_at):
    result = compare(C, op, const(10.))
    assert not result.undecided
    assert all(membership(result.certain_true, p) for p in true_at)
    assert all(membership(result.certain_false, p) for p in false_at)


def test_pf15_fraction_root_between_float_neighbors_and_negative_slope():
    # Exact root 1/3 lies strictly between adjacent binary64 values.
    low = 1 / 3
    high = math.nextafter(low, math.inf)
    expr = scaled(C, -3.)
    # Multiplication rounding is included: near the mathematical root may be
    # unknown, but unrelated interior points have independent literal truth.
    result = compare(expr, "gt", const(-1.))
    assert membership(result.certain_true, .25)
    assert membership(result.certain_false, .5)
    assert not membership(result.certain_true, high)
    # Exercise exact rational root conversion without adding fictitious C.
    from src.biz.services.wealth.market.index_detail_xxm.forecast_math import _half_line
    greater = _half_line(Fraction(3), Fraction(-1), "gt", Interval())
    assert greater == (Interval(high, None, True, False),)
    lesser = _half_line(Fraction(3), Fraction(-1), "le", Interval())
    assert lesser == (Interval(0., low, False, True),)


def test_pf15_adjacent_open_float_interval_is_empty_but_closed_point_survives():
    lo = 100.
    hi = math.nextafter(lo, math.inf)
    assert not Interval(lo, hi).valid
    assert intersect(Interval(lo, hi), Interval()) is None
    assert merge((Interval(lo, hi),)) == []
    point = Interval(lo, lo, True, True)
    assert point.valid and intersect(point, Interval()) == point
    assert subtract(point, (point,)) == []
    assert subtract(Interval(lo, hi, True, True), (point,)) == [Interval(lo, hi, False, True)]


@pytest.mark.parametrize("region,low,high", [
    (Interval(4135.78, 4140.2), 4136, 4140),
    (Interval(4136., 4140.), 4137, 4139),
    (Interval(4136., 4140., True, True), 4136, 4140),
    (Interval(175.5, 175.5, True, True), None, None),
    (Interval(100.1, 100.2, True, True), None, None),
    (Interval(4135.78), 4136, None),
])
def test_pf15_integer_display_preserves_original_interval_and_true_absence(region, low, high):
    value = display_range(region)
    assert value == {**region.json(), "displayLower": low, "displayUpper": high}
    assert as_interval(value) == region


def test_pf15_integer_candidate_is_converted_before_range_and_original_checks():
    with pytest.raises(ValueError, match="changed"):
        display_range(Interval(9007199254740992.))
    exact = display_range(Interval(9007199254740992., 9007199254740992., True, True))
    assert exact["displayLower"] == exact["displayUpper"] == 9007199254740992
    assert display_range(Interval(4135.78))["displayLower"] == 4136


def test_pf01_ideal_zero_and_error_line_roots_are_all_finite_candidates():
    for projection, zero in ((ProjectionState(13., 27., 0.), 175.5), (ProjectionState(187., 173., 0.), 24.5)):
        hist = macd_expression(projection, field="hist")
        candidates = candidate_prices((condition(hist, "eq", const(0.)),), projection=projection, period="m60", check=CHECK)
        assert zero in candidates
        assert len(candidates) <= 9
        assert all(value > 0 and math.isfinite(value) for value in candidates)
        assert evaluate_expression(hist, zero) == 0.


def test_pf01_m1_normal_integer_range_proof_does_not_claim_unproved_zero_neighborhood():
    dif = macd_expression(P, field="dif")
    hist = macd_expression(P, field="hist")
    rules = (condition(dif, "ge", const(-13.86)), condition(hist, "le", const(0.)))
    result = solve_predicates(rules, projection=P, period="m60", check=CHECK)
    assert membership(result.certain_true, 2.)
    assert membership(result.certain_false, 1.75)
    assert membership(result.certain_false, 176.)
    assert membership(result.undecided, 175.5)
    assert not membership(result.certain_true, 175.5)


@pytest.mark.parametrize("sign", (1, -1))
@pytest.mark.parametrize("current,passed", ((98.01, False), (98.009, True)))
def test_pf08_full_original_subtraction_keeps_one_percent_false_and_true(sign, current, passed):
    # Top P99 -> current98.01 is short of .99 after original subtraction;
    # bottom mirror has precisely the same magnitude and opposite direction.
    p, d = sign * 99., sign * current
    delta = scaled(difference(const(d), const(p)), sign)
    gate = abs(p) * 1.0 / 100
    predicates = (condition(delta, "lt", const(0.)), condition(scaled(delta, -1), "ge", const(gate)))
    expected = ((True, True),) if passed else ((True, False),)
    assert condition_options(predicates, 1.) == expected
    result = solve_predicates(predicates, projection=P, period="m60", check=CHECK)
    assert membership(result.certain_true if passed else result.certain_false, 1.)


def test_pf08_gate_underflow_does_not_remove_strict_direction():
    p = float.fromhex("0x0.0000000000001p-1022")
    gate = abs(p) * 1.0 / 100
    assert p != 0 and gate == 0.
    delta = scaled(difference(const(p), const(p)), 1)
    assert condition_options((condition(delta, "lt", const(0.)), condition(scaled(delta, -1), "ge", const(gate))), 1.) == ((False, True),)


def test_pf16_original_large_source_options_are_not_trimmed():
    assert source_options(-8796093022207.98, True) == (-8796093022207.98, -8796093022207.979)
    assert source_options(0., True) == (0.,)
    assert source_options(1.2345, False) == (1.2345,)


@pytest.mark.parametrize("projection,close", [
    (ProjectionState(13., 27., 0.), 175.5),
    (ProjectionState(187., 173., 0.), 24.5),
    (ProjectionState(-8796093022207.98, 0., 0.), 1.),
    (ProjectionState(8796093022207.98, 0., 0.), 1.),
    (ProjectionState(0., 0., 0.), math.nextafter(0., math.inf)),
])
@pytest.mark.parametrize("field,index", (("dif", 0), ("hist", 2)))
def test_pf16_independent_fraction_source_error_encloses_all_original_choices(projection, close, field, index):
    # Independently spell the literal producer recurrence and declared Ef.
    e12 = projection.e12 * 11 / 13 + close * 2 / 13
    e26 = projection.e26 * 25 / 27 + close * 2 / 27
    d = e12 - e26
    a = .8 * projection.dea + .2 * d
    raw = (d, a, 2 * (d - a))[index]
    u, eta = Fraction(1, 2**53), Fraction(1, 2**1074)
    expected_error = (2 * u + u*u) * abs(Fraction(raw)) + (1+u)*(1+eta)/1000 + eta
    for value in source_options(raw, True):
        assert abs(Fraction(value) - Fraction(raw)) <= expected_error
    bound = one_step_source_envelope(projection, field)
    _, slope, intercept = bound.ideal
    _, error_slope, error_intercept = bound.error
    center, error = slope * Fraction(close) + intercept, error_slope * Fraction(close) + error_intercept
    assert all(center-error <= Fraction(value) <= center+error for value in source_options(raw, True))
    generic = sourced(macd_expression(projection, field=field), True)
    assert _expression_envelope(generic) == (None, False)


def test_pf18_same_source_binding_is_shared_after_json_copy():
    projection = ProjectionState(13., 27., 0.)
    expr = sourced(macd_expression(projection, field="dif"), True)
    # Raw choice supplied by the same one-step producer, avoiding another EMA.
    raw = (.0005, 0., 0.)
    copy = json.loads(json.dumps(expr))
    difference_expr = difference(expr, copy)
    assert expression_options(difference_expr, 1., raw_values=raw) == (0.,)
    vectors = condition_options((condition(expr, "gt", const(0.)), condition(copy, "le", const(0.))), 1., raw_values=raw)
    assert set(vectors) == {(False, True), (True, False)}
    assert (True, True) not in vectors


@pytest.mark.parametrize("bad", [
    dict(op="affine", pCoefficient=1., cCoefficient=0., constant=0.),
    dict(op="affine", pCoefficient=0., cCoefficient=2., constant=0.),
    dict(op="macd", e12=13., e26=27., dea=0., field="dif", prefixBars=1),
    dict(op="macd", e12=13., e26=27., dea=0., field="dea"),
    dict(op="round3", arg=const(1.), guard=1e-10),
    dict(op="scale", arg=const(1.), factor=True),
])
def test_pf20_expression_contract_refuses_old_or_unsupported_nodes(bad):
    with pytest.raises(ValueError):
        compare(bad, "gt", const(0.))


def test_pf17_nonfinite_original_operations_fail_instead_of_certifying_false():
    huge = scaled(const(1e308), 2.)
    cancelled = difference(huge, huge)
    with pytest.raises(ValueError, match="Non-finite"):
        compare(cancelled, "gt", const(0.))
    with pytest.raises(ValueError, match="Non-finite original EMA"):
        one_step_macd_envelope(ProjectionState(1e308, 1., 0.), "dif")
    with pytest.raises(ValueError):
        compare(macd_expression(ProjectionState(14., 27., 0.), field="dif"), "gt", const(0.))


def test_pf17_original_check_exception_is_not_swallowed():
    class Cancelled(RuntimeError):
        pass
    def check():
        raise Cancelled("original cancellation")
    with pytest.raises(Cancelled, match="original cancellation"):
        solve_comparison(C, "gt", const(10.), Interval(), projection=P, period="m60", check=check)


def test_pf19_work_count_does_not_depend_on_price_span(monkeypatch):
    import src.biz.services.wealth.market.index_detail_xxm.forecast_math as module
    original = module._half_line
    calls = []
    def counted(*args):
        calls.append(args)
        return original(*args)
    monkeypatch.setattr(module, "_half_line", counted)
    sizes = []
    for threshold in (10., 1e12):
        calls.clear()
        result = compare(C, "gt", const(threshold))
        assert result.certain_true and result.certain_false
        sizes.append(len(calls))
    assert sizes == [2, 2]
    assert sys.float_info.radix == 2 and sys.float_info.mant_dig == 53 and sys.float_info.rounds == 1


@pytest.mark.parametrize("period", ("day", "m60", "m90", "m120"))
@pytest.mark.parametrize("field,index", (("dif", 0), ("hist", 2)))
@pytest.mark.parametrize("op,threshold", (("lt", 0.), ("ge", -13.86)))
def test_pf16_certified_ranges_agree_with_literal_ordered_ema(period, field, index, op, threshold):
    expr = sourced(macd_expression(P, field=field), period == "day")
    result = compare(expr, op, const(threshold), period=period)
    for close in (.01, 1.75, 2., 100., 175.5, 176., 5000.):
        e12 = 13. * 11 / 13 + close * 2 / 13
        e26 = 27. * 25 / 27 + close * 2 / 27
        d = e12 - e26
        a = .8 * 0. + .2 * d
        raw = (d, a, 2 * (d-a))[index]
        value = round(raw, 3) if period == "day" else raw
        expected = value < threshold if op == "lt" else value >= threshold
        assert sum(membership(r, close) for r in (result.certain_true, result.certain_false, result.undecided)) == 1
        if membership(result.certain_true, close):
            assert expected is True
        elif membership(result.certain_false, close):
            assert expected is False


def test_pf15_merge_only_fills_gaps_with_no_representable_close():
    a = 100.
    b = math.nextafter(a, math.inf)
    c = math.nextafter(b, math.inf)
    assert merge((Interval(a, a, True, True), Interval(b, c, True, True))) == [Interval(a, c, True, True)]
    # b is a real excluded float: taking an outside hull would invent it.
    assert merge((Interval(a, a, True, True), Interval(c, c, True, True))) == [Interval(a, a, True, True), Interval(c, c, True, True)]
    assert merge((Interval(99., 100., True, False), Interval(100., 101., False, True))) == [Interval(99., 100., True, False), Interval(100., 101., False, True)]
    assert not Interval(10**400).valid
