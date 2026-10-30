"""One-step MACD expressions; original operations and conservative bounds.

Only C is unknown.  A source choice is shared wherever the same DIF or MACD
column is used.  Bounds prove a range; evaluations only prove their own point.
"""
from dataclasses import dataclass
from fractions import Fraction
from itertools import product
import math

from .forecast_math import GUARD, source_options
from .projection import ProjectionState, ProjectionPrecisionError


_UNIT_ROUNDOFF = Fraction(1, 2**53)
_SUBNORMAL_BOUND = Fraction(1, 2**1074)


def _number(value):
    if type(value) not in (int, float):
        raise ValueError("Expression number must be original and finite")
    try:
        if not math.isfinite(value):
            raise ValueError("Expression number must be original and finite")
    except OverflowError as exc:
        raise ValueError("Expression number must be finite") from exc
    return value


def literal(value):
    return dict(op="affine", pCoefficient=0., cCoefficient=0., constant=_number(value))


def sourced(expr, day):
    return dict(op="round3", arg=expr, guard=GUARD) if day else expr


def macd_expression(projection, *, field):
    if field not in ("dif", "hist"):
        raise ValueError("Invalid one-step MACD field")
    return dict(op="macd", e12=_number(projection.e12), e26=_number(projection.e26),
                dea=_number(projection.dea), field=field)


def validate_expression(node, *, projection=None):
    if type(node) is not dict or "op" not in node:
        raise ValueError("Invalid forecast expression")
    op = node["op"]
    fields = {"affine": {"op", "pCoefficient", "cCoefficient", "constant"},
              "macd": {"op", "e12", "e26", "dea", "field"},
              "round3": {"op", "arg", "guard"}, "sub": {"op", "args"},
              "scale": {"op", "arg", "factor"}, "abs": {"op", "arg"}}
    if op not in fields or set(node) != fields[op]:
        raise ValueError("Unknown or obsolete forecast expression fields")
    if op == "affine":
        a, b, k = (_number(node[key]) for key in ("pCoefficient", "cCoefficient", "constant"))
        if a != 0 or b not in (0, 1) or (b == 1 and k != 0):
            raise ValueError("Only a constant or the next close is allowed")
    elif op == "macd":
        for key in ("e12", "e26", "dea"):
            _number(node[key])
        if node["field"] not in ("dif", "hist"):
            raise ValueError("Invalid MACD field")
        if projection is not None and any(node[key] != getattr(projection, key) for key in ("e12", "e26", "dea")):
            raise ValueError("MACD expression belongs to another projection")
    elif op == "sub":
        if type(node["args"]) not in (tuple, list) or len(node["args"]) != 2:
            raise ValueError("Subtraction requires two operands")
        for arg in node["args"]:
            validate_expression(arg, projection=projection)
    else:
        validate_expression(node["arg"], projection=projection)
        if op == "scale":
            _number(node["factor"])
        if op == "round3":
            if type(node["guard"]) is not float or node["guard"] != GUARD or node["arg"]["op"] != "macd":
                raise ValueError("Only an original one-step source may be rounded")
    return node


def _records(node, close, raw, memo):
    key = id(node)
    if key in memo:
        return memo[key]
    op = node["op"]
    if op == "affine":
        values = ((close if node["cCoefficient"] == 1 else node["constant"], {}),)
    elif op == "macd":
        values = ((raw[0 if node["field"] == "dif" else 2], {}),)
    elif op == "round3":
        arg = node["arg"]
        origin = (arg["e12"], arg["e26"], arg["dea"], arg["field"])
        value = raw[0 if arg["field"] == "dif" else 2]
        if not math.isfinite(value * 1000):
            raise ValueError("Non-finite source rounding")
        values = tuple((v, {origin: v}) for v in source_options(value, True))
    elif op == "sub":
        left, right = (_records(arg, close, raw, memo) for arg in node["args"])
        values = tuple((a - b, {**ab, **bb}) for (a, ab), (b, bb) in product(left, right)
                       if all(k not in ab or ab[k] == v for k, v in bb.items()))
    else:
        values = tuple((v * node["factor"] if op == "scale" else abs(v), binding)
                       for v, binding in _records(node["arg"], close, raw, memo))
    if any(not math.isfinite(value) for value, _ in values):
        raise ValueError("Non-finite expression")
    memo[key] = values
    return values


def _raw_for(expressions, close, check, raw_values):
    for expr in expressions:
        validate_expression(expr)
    nodes = []
    def collect(node):
        if node["op"] == "macd":
            nodes.append(node)
        elif "arg" in node:
            collect(node["arg"])
        elif "args" in node:
            for arg in node["args"]:
                collect(arg)
    for expr in expressions:
        collect(expr)
    identities = {(node["e12"], node["e26"], node["dea"]) for node in nodes}
    if len(identities) > 1:
        raise ValueError("Mixed MACD projection sources")
    if raw_values is not None:
        if len(raw_values) != 3 or any(not math.isfinite(_number(v)) for v in raw_values):
            raise ValueError("Invalid original projection values")
        return tuple(raw_values)
    if not identities:
        return (0., 0., 0.)
    check()
    state, raw = ProjectionState(*next(iter(identities))).advance(close)
    if any(not math.isfinite(value) for value in (state.e12, state.e26, state.dea, *raw)):
        raise ValueError("Non-finite projection")
    check()
    return raw


def expression_options(expr, c, check=lambda: None, *, raw_values=None):
    c = _number(c)
    if c <= 0:
        raise ValueError("Target close must be positive")
    check()
    raw = _raw_for((expr,), c, check, raw_values)
    result = tuple(dict.fromkeys(v for v, _ in _records(expr, c, raw, {})))
    check()
    return result


def condition_options(conditions, c, check=lambda: None, *, raw_values=None):
    c = _number(c)
    if c <= 0:
        raise ValueError("Target close must be positive")
    compare = {"lt": lambda a, b: a < b, "le": lambda a, b: a <= b,
               "eq": lambda a, b: a == b, "ge": lambda a, b: a >= b, "gt": lambda a, b: a > b}
    expressions = []
    for item in conditions:
        if type(item) is not dict or set(item) != {"left", "op", "right"} or item["op"] not in compare:
            raise ValueError("Invalid comparison")
        expressions.extend((item["left"], item["right"]))
    raw = _raw_for(expressions, c, check, raw_values)
    records, memo = [((), {})], {}
    for item in conditions:
        check()
        options = []
        for (a, ab), (b, bb) in product(_records(item["left"], c, raw, memo), _records(item["right"], c, raw, memo)):
            if all(k not in ab or ab[k] == v for k, v in bb.items()):
                options.append((compare[item["op"]](a, b), {**ab, **bb}))
        records = [((*vector, value), {**bindings, **chosen})
                   for (vector, bindings), (value, chosen) in product(records, options)
                   if all(k not in bindings or bindings[k] == v for k, v in chosen.items())]
    check()
    return tuple(dict.fromkeys(vector for vector, _ in records))


def evaluate_expression(expr, c, check=lambda: None):
    values = expression_options(expr, c, check)
    if len(values) != 1:
        raise ProjectionPrecisionError("ROUNDING_BOUNDARY")
    return values[0]


@dataclass(frozen=True)
class _AffineEnvelope:
    # P is retained as a zero proof coefficient, never as an input variable.
    ideal: tuple
    error: tuple = (Fraction(0), Fraction(0), Fraction(0))


def _fraction(value):
    return Fraction(value) if type(value) is int else Fraction.from_float(value)


def _exact_constant(value):
    value = _number(value)
    fraction = _fraction(value)
    conversion = abs(Fraction.from_float(float(value)) - fraction)
    return _AffineEnvelope((Fraction(0), Fraction(0), fraction), (Fraction(0), Fraction(0), conversion))


def _rounded_envelope(ideal, inherited):
    errors = tuple(old + _UNIT_ROUNDOFF * (abs(value) + old) for value, old in zip(ideal, inherited))
    return _AffineEnvelope(ideal, (errors[0], errors[1], errors[2] + _SUBNORMAL_BOUND))


def _envelope_binary(left, right, op):
    ideal = tuple(a + b if op == "add" else a - b for a, b in zip(left.ideal, right.ideal))
    return _rounded_envelope(ideal, tuple(a + b for a, b in zip(left.error, right.error)))


def _envelope_scaled(value, factor, *, division=False):
    factor = _fraction(_number(factor))
    if division:
        if factor == 0:
            raise ValueError("Zero divisor")
        factor = 1 / factor
    return _rounded_envelope(tuple(v * factor for v in value.ideal), tuple(v * abs(factor) for v in value.error))


def one_step_macd_envelope(projection, field):
    macd_expression(projection, field=field)
    if not all(math.isfinite(value) for value in (projection.e12 * 11, projection.e26 * 25, .8 * projection.dea)):
        raise ValueError("Non-finite original EMA intermediate")
    e12, e26, dea = (_exact_constant(getattr(projection, key)) for key in ("e12", "e26", "dea"))
    c = _AffineEnvelope((Fraction(0), Fraction(1), Fraction(0)))
    twice = _envelope_scaled(c, 2)
    e12 = _envelope_binary(_envelope_scaled(_envelope_scaled(e12, 11), 13, division=True),
                           _envelope_scaled(twice, 13, division=True), "add")
    e26 = _envelope_binary(_envelope_scaled(_envelope_scaled(e26, 25), 27, division=True),
                           _envelope_scaled(twice, 27, division=True), "add")
    dif = _envelope_binary(e12, e26, "sub")
    dea = _envelope_binary(_envelope_scaled(dea, .8), _envelope_scaled(dif, .2), "add")
    hist = _envelope_scaled(_envelope_binary(dif, dea, "sub"), 2)
    return dif if field == "dif" else hist


def one_step_source_envelope(projection, field):
    raw = one_step_macd_envelope(projection, field)
    k = 2 * _UNIT_ROUNDOFF + _UNIT_ROUNDOFF**2
    t = (1 + _UNIT_ROUNDOFF) * (1 + _SUBNORMAL_BOUND) / 1000 + _SUBNORMAL_BOUND
    _, a, b = raw.ideal
    _, e, f = raw.error
    return _AffineEnvelope(raw.ideal, (Fraction(0), e + k * (abs(a) + e), f + k * (abs(b) + f) + t))


def _outward_float(value, upper):
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError("Non-finite necessary root") from exc
    if not math.isfinite(result):
        raise ValueError("Non-finite necessary root")
    if upper and _fraction(result) < value:
        result = math.nextafter(result, math.inf)
    elif not upper and _fraction(result) > value:
        result = math.nextafter(result, -math.inf)
    if not math.isfinite(result):
        raise ValueError("Non-finite necessary root")
    return result


def _expression_envelope(node):
    """Generic round3 stays deliberately uncertified; only the wrapper is special."""
    validate_expression(node)
    result = _visit_envelope(node, None, False)
    return result, result is not None


def _visit_envelope(node, projection, source):
    op = node["op"]
    if op == "affine":
        return _AffineEnvelope((Fraction(0), Fraction(1), Fraction(0))) if node["cCoefficient"] else _exact_constant(node["constant"])
    if op == "macd":
        own = ProjectionState(node["e12"], node["e26"], node["dea"])
        return one_step_macd_envelope(own, node["field"])
    if op == "round3":
        if not source:
            return None
        arg = node["arg"]
        validate_expression(arg, projection=projection)
        return one_step_source_envelope(projection, arg["field"])
    if op == "sub":
        left, right = (_visit_envelope(arg, projection, source) for arg in node["args"])
        return None if left is None or right is None else _envelope_binary(left, right, "sub")
    child = _visit_envelope(node["arg"], projection, source)
    if child is None:
        return None
    if op == "scale":
        return _envelope_scaled(child, node["factor"])
    # abs is exact. Constant/sign-fixed half-lines retain their tight affine
    # proof; a crossing expression uses the sound [0, |a|C+|b|+error] bound.
    _, a, b = child.ideal
    _, e, f = child.error
    if a - e >= 0 and b - f >= 0:
        return child
    if a + e <= 0 and b + f <= 0:
        return _AffineEnvelope(tuple(-v for v in child.ideal), child.error)
    upper_a, upper_b = abs(a) + e, abs(b) + f
    return _AffineEnvelope((Fraction(0), upper_a / 2, upper_b / 2), (Fraction(0), upper_a / 2, upper_b / 2))


def comparison_envelope(left, right, *, projection, period):
    if period not in ("day", "m60", "m90", "m120"):
        raise ValueError("Unsupported forecast period")
    validate_expression(left, projection=projection)
    validate_expression(right, projection=projection)
    def check_constants(node):
        if node["op"] == "macd":
            return False
        children = node.get("args", (node["arg"],) if "arg" in node else ())
        child_constants = [check_constants(arg) for arg in children]
        constant = node["op"] == "affine" and node["cCoefficient"] == 0 or bool(children) and all(child_constants)
        if constant:
            _records(node, 1., (0., 0., 0.), {})
        return constant
    check_constants(left)
    check_constants(right)
    a, b = (_visit_envelope(node, projection, period == "day") for node in (left, right))
    if a is None or b is None:
        raise ValueError("Unsupported source expression")
    # The comparison itself does not perform a floating subtraction.
    return _AffineEnvelope(tuple(x - y for x, y in zip(a.ideal, b.ideal)), tuple(x + y for x, y in zip(a.error, b.error)))
