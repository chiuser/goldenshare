"""Price intervals, source precision and affine MACD expressions."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import math
from .forecast_spec import FORECAST_SPEC
GUARD = FORECAST_SPEC.daily_rounding_guard
K = 2 / 13 - 2 / 27


@dataclass(frozen=True)
class Interval:
    lo: float = 0.
    hi: float | None = None
    li: bool = False
    ui: bool = False

    def contains(self, p):
        return (p > self.lo or self.li and p == self.lo) and (self.hi is None or p < self.hi or self.ui and p == self.hi)

    @property
    def valid(self):
        return self.hi is None or self.lo < self.hi or self.lo == self.hi and self.li and self.ui

    def json(self):
        return dict(lower=self.lo, upper=self.hi, lowerInclusive=self.li, upperInclusive=self.ui)


def intersect(a, b):
    lo = max(a.lo, b.lo)
    hi = b.hi if a.hi is None else a.hi if b.hi is None else min(a.hi, b.hi)
    value = Interval(lo, hi, a.contains(lo) and b.contains(lo), hi is not None and a.contains(hi) and b.contains(hi))
    return value if value.valid else None


def merge(ranges):
    result = []
    for r in sorted(ranges, key=lambda r: (r.lo, not r.li)):
        if result and (result[-1].hi is None or r.lo < result[-1].hi or r.lo == result[-1].hi and (r.li or result[-1].ui)):
            old = result[-1]
            hi = None if old.hi is None or r.hi is None else max(old.hi, r.hi)
            ui = hi is not None and ((old.hi == hi and old.ui) or (r.hi == hi and r.ui))
            result[-1] = Interval(old.lo, hi, old.li, ui)
        else:
            result.append(r)
    return result


def subtract(a, bs):
    remaining = [a]
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


@dataclass(frozen=True)
class Affine:
    p: float = 0.
    c: float = 0.
    b: float = 0.

    def __add__(self, other):
        if not isinstance(other, Affine): other=Affine(b=other)
        return Affine(self.p+other.p,self.c+other.c,self.b+other.b)
    def __sub__(self, other):
        if not isinstance(other, Affine): other=Affine(b=other)
        return Affine(self.p-other.p,self.c-other.c,self.b-other.b)
    def __mul__(self, factor):
        return Affine(self.p*factor,self.c*factor,self.b*factor)
    def value(self,p,c=0.):return self.p*p+self.c*c+self.b
    def json(self):return dict(op='affine',pCoefficient=self.p,cCoefficient=self.c,constant=self.b)


def project_affine_prefix(projection, n):
    e12,e26,a=Affine(b=projection.e12),Affine(b=projection.e26),Affine(b=projection.dea)
    ds,hs=[],[]
    for i in range(n):
        e12,e26=e12*(11/13)+Affine(p=2/13),e26*(25/27)+Affine(p=2/27)
        d=e12-e26;a=a*.8+d*.2
        ds.append(d);hs.append((d-a)*2)
    b=e12*(11/13)-e26*(25/27)
    target=b+Affine(c=K)
    hist=(target-a)*1.6
    return ds,hs,target,hist


def rounded(expr,day):return dict(op='round3',arg=expr.json(),guard=GUARD) if day else expr.json()


def const(v):return Affine(b=v).json()


def condition(left,op,right):return dict(left=left,op=op,right=right)


def scaled(expr,f):return dict(op='scale',arg=expr,factor=f)


def difference(a,b):return dict(op='sub',args=[a,b])


def number_inside(value,lower,places):
    step=Decimal(1).scaleb(-places)
    allowance=Decimal(str(max(1e-7,math.ulp(value)*32)))
    return float((Decimal(str(value))+(allowance if lower else -allowance)).quantize(step,rounding=ROUND_CEILING if lower else ROUND_FLOOR))


def display_range(interval,places=FORECAST_SPEC.price_display_places):
    lo=number_inside(interval.lo,True,places)
    hi=None if interval.hi is None else number_inside(interval.hi,False,places)
    if hi is not None and lo>hi:
        if places==FORECAST_SPEC.price_boundary_places:return None
        return display_range(interval,FORECAST_SPEC.price_boundary_places)
    return dict(interval.json(),displayLower=lo,displayUpper=hi,displayPlaces=places)


def as_interval(value):
    return Interval(value['lower'] or 0.,value['upper'],value['lowerInclusive'],value['upperInclusive'])


def restrict_positive(domain, slope, intercept):
    if slope==0:
        return domain if intercept>0 else None
    root=-intercept/slope
    if slope>0:
        if root<0:return domain
        return intersect(domain,Interval(root,None))
    return intersect(domain,Interval(0.,root))
