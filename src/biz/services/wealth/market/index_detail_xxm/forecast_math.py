"""Finite one-step price boundaries, preserving original float/source rules."""
from dataclasses import dataclass
from fractions import Fraction
import math
import sys

from .forecast_spec import FORECAST_SPEC
from .types import ComparisonRanges

GUARD = FORECAST_SPEC.daily_rounding_guard


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class Interval:
    lo: float = 0.
    hi: float | None = None
    li: bool = False
    ui: bool = False

    def contains(self, p):
        return (_finite(p) and p > 0 and (p > self.lo or self.li and p == self.lo)
                and (self.hi is None or p < self.hi or self.ui and p == self.hi))

    @property
    def valid(self):
        if (not _finite(self.lo) or self.lo < 0 or type(self.li) is not bool or type(self.ui) is not bool
                or self.lo == 0 and self.li or self.hi is None and self.ui
                or self.hi is not None and not _finite(self.hi)):
            return False
        try:
            first = self.lo if self.li else math.nextafter(self.lo, math.inf)
            last = sys.float_info.max if self.hi is None else self.hi if self.ui else math.nextafter(self.hi, -math.inf)
            return math.isfinite(first) and first > 0 and first <= last
        except (OverflowError, TypeError):
            return False

    def json(self):
        return dict(lower=self.lo, upper=self.hi, lowerInclusive=self.li, upperInclusive=self.ui)


def intersect(a, b):
    lo = max(a.lo, b.lo)
    hi = b.hi if a.hi is None else a.hi if b.hi is None else min(a.hi, b.hi)
    value = Interval(lo, hi, a.contains(lo) and b.contains(lo), hi is not None and a.contains(hi) and b.contains(hi))
    return value if value.valid else None


def merge(ranges):
    result = []
    for r in sorted((r for r in ranges if r.valid), key=lambda r: (r.lo, not r.li)):
        first = r.lo if r.li else math.nextafter(r.lo, math.inf)
        old = result[-1] if result else None
        last = (sys.float_info.max if old.hi is None else old.hi if old.ui else math.nextafter(old.hi, -math.inf)) if old else None
        # Adjacency is over actual representable C, never a real-valued hull
        # across an excluded or uncertain float. Keep the outer boundaries.
        if old is not None and first <= math.nextafter(last, math.inf):
            old = result[-1]
            hi = None if old.hi is None or r.hi is None else max(old.hi, r.hi)
            ui = hi is not None and ((old.hi == hi and old.ui) or (r.hi == hi and r.ui))
            result[-1] = Interval(old.lo, hi, old.li, ui)
        else:
            result.append(r)
    return result


def subtract(a, bs):
    remaining = [a] if a.valid else []
    for b in merge(bs):
        newer = []
        for r in remaining:
            cut = intersect(r, b)
            if cut is None:
                newer.append(r)
                continue
            left = Interval(r.lo, cut.lo, r.li, r.contains(cut.lo) and not cut.li)
            if left.valid:
                newer.append(left)
            if cut.hi is not None:
                right = Interval(cut.hi, r.hi, r.contains(cut.hi) and not cut.ui, r.ui)
                if right.valid:
                    newer.append(right)
        remaining = newer
    return remaining


def source_options(value, day):
    if not day:
        return (value,)
    half = (math.floor(value * 1000) + .5) / 1000
    if abs(value - half) <= GUARD:
        return (math.floor(value * 1000) / 1000, (math.floor(value * 1000) + 1) / 1000)
    return (round(value, 3),)


def const(v):
    if not _finite(v):
        raise ValueError("Constant must be finite")
    return dict(op="affine", pCoefficient=0., cCoefficient=0., constant=v)


def condition(left, op, right):
    if op not in ("lt", "le", "eq", "ge", "gt"):
        raise ValueError("Invalid comparison")
    return dict(left=left, op=op, right=right)


def scaled(expr, factor):
    if not _finite(factor):
        raise ValueError("Scale must be finite")
    return dict(op="scale", arg=expr, factor=factor)


def difference(a, b):
    return dict(op="sub", args=[a, b])


def as_interval(value):
    r = Interval(value["lower"], value["upper"], value["lowerInclusive"], value["upperInclusive"])
    if not r.valid:
        raise ValueError("Invalid price interval")
    return r


def _integer_float(n):
    try:
        value = float(n)
    except OverflowError as exc:
        raise ValueError("Display integer cannot be represented") from exc
    if not math.isfinite(value) or int(value) != n:
        raise ValueError("Display integer changed during float conversion")
    return value


def display_range(interval):
    if not interval.valid:
        raise ValueError("Invalid display interval")
    low = math.ceil(interval.lo)
    if not interval.li and low == interval.lo:
        low += 1
    high = None if interval.hi is None else math.floor(interval.hi)
    if high is not None and not interval.ui and high == interval.hi:
        high -= 1
    if high is not None and low > high:
        return dict(interval.json(), displayLower=None, displayUpper=None)
    lo_float = _integer_float(low)
    hi_float = None if high is None else _integer_float(high)
    if not interval.contains(lo_float) or hi_float is not None and not interval.contains(hi_float):
        raise ValueError("Display integer outside the proved interval")
    return dict(interval.json(), displayLower=low, displayUpper=high)


def _half_line(a, b, op, domain):
    """Exact rational linear comparison, converted to equivalent float sets."""
    from .forecast_expression import _outward_float
    if op not in ("gt", "ge", "lt", "le", "eq"):
        raise ValueError("Invalid comparison")
    if a == 0:
        passed = {"gt": b > 0, "ge": b >= 0, "lt": b < 0, "le": b <= 0, "eq": b == 0}[op]
        return (domain,) if passed else ()
    if a < 0:
        a, b = -a, -b
        op = {"gt": "lt", "ge": "le", "lt": "gt", "le": "ge", "eq": "eq"}[op]
    root = -b / a
    if root <= 0:
        return (domain,) if op in ("gt", "ge") else ()
    if op == "eq":
        value = _outward_float(root, True)
        if Fraction.from_float(value) != root:
            return ()
        candidate = Interval(value, value, True, True)
    elif op in ("gt", "ge"):
        value = _outward_float(root, True)
        candidate = Interval(value, None, op == "ge" or Fraction.from_float(value) != root, False)
    else:
        value = _outward_float(root, False)
        candidate = Interval(0., value, False, op == "le" or Fraction.from_float(value) != root)
    value = intersect(domain, candidate)
    return (value,) if value is not None else ()


def _intersection(left, right):
    return tuple(merge(v for a in left for b in right if (v := intersect(a, b)) is not None))


def solve_comparison(left, op, right, domain, *, projection, period, check):
    from .forecast_expression import comparison_envelope
    check()
    if not isinstance(domain, Interval) or not domain.valid:
        raise ValueError("Invalid comparison domain")
    env = comparison_envelope(left, right, projection=projection, period=period)
    _, a, b = env.ideal
    _, e, f = env.error
    lower, upper = (a - e, b - f), (a + e, b + f)
    if op in ("gt", "ge"):
        true = _half_line(*lower, op, domain)
        false = _half_line(*upper, "le" if op == "gt" else "lt", domain)
    elif op in ("lt", "le"):
        true = _half_line(*upper, op, domain)
        false = _half_line(*lower, "ge" if op == "lt" else "gt", domain)
    elif op == "eq":
        true = _intersection(_half_line(*lower, "ge", domain), _half_line(*upper, "le", domain))
        false = tuple(merge((*_half_line(*lower, "gt", domain), *_half_line(*upper, "lt", domain))))
    else:
        raise ValueError("Invalid comparison operation")
    undecided = tuple(subtract(domain, (*true, *false)))
    check()
    return ComparisonRanges(tuple(true), tuple(false), undecided)


def solve_predicates(predicates, *, projection, period, check):
    domain = Interval()
    true, false = (domain,), ()
    for item in predicates:
        check()
        if type(item) is not dict or set(item) != {"left", "op", "right"}:
            raise ValueError("Invalid condition")
        result = solve_comparison(item["left"], item["op"], item["right"], domain,
                                  projection=projection, period=period, check=check)
        true = _intersection(true, result.certain_true)
        false = tuple(merge((*false, *result.certain_false)))
    check()
    return ComparisonRanges(true, false, tuple(subtract(domain, (*true, *false))))


def candidate_prices(predicates, *, projection, period, check):
    from .forecast_expression import comparison_envelope
    prices = set()
    for item in predicates:
        check()
        env = comparison_envelope(item["left"], item["right"], projection=projection, period=period)
        _, a, b = env.ideal
        _, e, f = env.error
        for slope, intercept in ((a, b), (a - e, b - f), (a + e, b + f)):
            if slope == 0:
                continue
            root = -intercept / slope
            if root <= 0:
                continue
            try:
                nearest = float(root)
            except OverflowError as exc:
                raise ValueError("Non-finite necessary candidate") from exc
            if not math.isfinite(nearest):
                raise ValueError("Non-finite necessary candidate")
            for value in (nearest, math.nextafter(nearest, -math.inf), math.nextafter(nearest, math.inf)):
                if math.isfinite(value) and value > 0:
                    prices.add(value)
    check()
    return tuple(sorted(prices))
