"""Read-only candidate. Affine branch geometry; detector events verify every output.

Not imported by production. It uses no future actual prices, IO, or new detector.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from itertools import product
import math

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar
from src.biz.services.wealth.market.index_detail_xxm.projection import ProjectionState

GUARD = 1e-10
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


def clone(c):
    child = XxmCalculator(period=c.period, source_identity=c.source_identity, spec=c.spec)
    child.restore(c.snapshot())
    return child


def source_options(value, day):
    if not day:
        return (value,)
    half = (math.floor(value * 1000) + .5) / 1000
    if abs(value - half) <= GUARD:
        return (math.floor(value * 1000) / 1000, (math.floor(value * 1000) + 1) / 1000)
    return (round(value, 3),)


def possible_bars(projection, close, stamp, day):
    projected, (d, a, h) = projection.advance(close)
    return projected, tuple(XxmBar(stamp, close, dd, round(a, 3) if day else a, hh)
                            for dd, hh in product(source_options(d, day), source_options(h, day)))


def event_options(c, projection, close, stamp, kind):
    state, bars = possible_bars(projection, close, stamp, c.period == 'day')
    results = []
    for bar in bars:
        child = clone(c)
        step = child.step(bar)
        event = next((e for e in step.events if e['type'] == kind and e['direction'] == ('TOP' if c.wave.sign > 0 else 'BOTTOM')), None)
        results.append((child, state, event))
    return results


def activation_signature(c, projection, p, stamp):
    options = event_options(c, projection, p, stamp, 'DULL')
    events = [o[2] for o in options]
    if events and all(e is not None and e['route'] == 'activation' for e in events):
        refs = {e['eventReference']['startTime'] for e in events}
        if len(refs) == 1:
            return events[0]['eventReference']
    if any(events):
        return 'PRECISION_UNRESOLVED'
    return None


def entry_partition(c, projection):
    """Complete predicate cuts with a computed affine-roundoff enclosure.

    This enclosure is NOT an epsilon in the detector. A cell inside it is
    undecidable by the factored affine proof and is labelled precision only.
    """
    w=c.wave;b=projection.e12*11/13-projection.e26*25/27
    cuts={0.,w.price,(w.dif-b)/K};bands=[]
    day=c.period=='day'
    def add_root(root,slope):
        if root<0 or not math.isfinite(root):return
        error=8*math.ulp(max(abs(projection.e12),abs(projection.e26),abs(root),1.))/abs(slope)
        band=Interval(max(0.,root-error),root+error,True,True)
        cuts.update((root,band.lo,band.hi));bands.append(band)
    for ref in c.history[w.sign]:
        cuts.add(ref.price)
        for d in ((ref.dif-.0005,ref.dif+.0005) if day else (ref.dif,)):
            for g in ((-GUARD,0.,GUARD) if day else (0.,)):
                add_root((d+g-b)/K,K)
    for h in ((-.0005,.0005) if day else (0.,)):
        for g in ((-GUARD,0.,GUARD) if day else (0.,)):
            add_root((projection.dea+(h+g)/1.6-b)/K,1.6*K)
    return sorted(v for v in cuts if v>=0 and math.isfinite(v)),merge(bands)


def entry_cuts(c,projection):return entry_partition(c,projection)[0]


def stable_reference_on_band(c,projection,region,reference):
    if region.hi is None:return False
    values=[projection.advance(p)[1] for p in (region.lo,region.hi)]
    error=8*math.ulp(max(abs(projection.e12),abs(projection.e26),abs(region.hi),1.))
    dlow=min(v[0] for v in values)-error;dhigh=max(v[0] for v in values)+error
    hlow=min(v[2] for v in values)-2*error;hhigh=max(v[2] for v in values)+2*error
    if c.period=='day':
        dlow=math.floor(dlow*1000)/1000;dhigh=math.ceil(dhigh*1000)/1000
        hlow=math.floor(hlow*1000)/1000;hhigh=math.ceil(hhigh*1000)/1000
    s=c.wave.sign;w=c.wave
    if w.count+1<c.spec.min_bars or (hlow<=0 if s>0 else hhigh>=0):return False
    pool=list(reversed(c.history[s]));recent_price=pool[0].price;pool.sort(key=lambda r:s*r.dif,reverse=True)
    def qualifies(ref,guaranteed):
        p=(region.lo if s>0 else region.hi) if guaranteed else (region.hi if s>0 else region.lo)
        extreme=max(w.price,p) if s>0 else min(w.price,p)
        dif=max(w.dif,dhigh if guaranteed else dlow) if s>0 else min(w.dif,dlow if guaranteed else dhigh)
        return s*(extreme-recent_price)>0 and s*(extreme-ref.price)>0 and s*(dif-ref.dif)<0
    for ref in pool:
        if ref.start==reference['startTime']:return qualifies(ref,True)
        if qualifies(ref,False):return False
    return False


def reason_for(c, projection, p):
    w = c.wave
    _, (d, a, h) = projection.advance(p)
    ds, hs = source_options(d, c.period == 'day'), source_options(h, c.period == 'day')
    if any((hh > 0)-(hh < 0) != w.sign for hh in hs):
        return 'WRONG_COLOR_OR_ZERO'
    if w.count+1 < c.spec.min_bars:
        return 'INSUFFICIENT_BARS'
    refs = list(reversed(c.history[w.sign]))
    extreme_price = max(w.price, p) if w.sign > 0 else min(w.price, p)
    if w.sign*(extreme_price-refs[0].price) <= 0:
        return 'PRICE_NOT_EXTREME'
    eligible_dif = [ref for ref in refs if all(w.sign*((max(w.dif,dd) if w.sign>0 else min(w.dif,dd))-ref.dif)<0 for dd in ds)]
    if eligible_dif and not any(w.sign*(extreme_price-ref.price)>0 for ref in eligible_dif):
        return 'PRICE_NOT_EXTREME'
    return 'DIF_NOT_DIVERGENT'


def solve_entry_ranges(c, projection, stamp, check=lambda: None):
    if c.state != 'NONE' or not c.wave or not c.wave.sign or not c.history[c.wave.sign]:
        return dict(endpoint=stamp, ranges=[], exclusions=[])
    cuts, numeric_bands = entry_partition(c, projection)
    parts = []
    for i, lo in enumerate(cuts):
        check()
        hi = cuts[i+1] if i+1 < len(cuts) else None
        mid = (lo+hi)/2 if hi is not None else lo+max(1.,lo*.1)
        signature = activation_signature(c, projection, mid, stamp)
        if any(b.contains(mid) for b in numeric_bands) and not (isinstance(signature,dict) and stable_reference_on_band(c,projection,Interval(lo,hi),signature)):
            probes=[math.nextafter(lo,0),math.nextafter(hi,math.inf)] if hi is not None else []
            if signature is not None or any(activation_signature(c,projection,p,stamp) is not None for p in probes if p>0):
                signature='PRECISION_UNRESOLVED'
        if hi is not None and hi-lo < 1e-7:
            probes=[math.nextafter(lo,hi),math.nextafter(hi,lo)]
            variants=[activation_signature(c,projection,p,stamp) for p in probes]
            if any(v!=signature for v in variants):signature='PRECISION_UNRESOLVED'
        parts.append((Interval(lo,hi), signature, reason_for(c,projection,mid)))
        if lo > 0:
            hit = activation_signature(c,projection,lo,stamp)
            if any(b.contains(lo) for b in numeric_bands) and not (isinstance(hit,dict) and stable_reference_on_band(c,projection,Interval(lo,lo,True,True),hit)):
                neighbours=[math.nextafter(lo,0),math.nextafter(lo,math.inf)]
                if hit is not None or any(activation_signature(c,projection,p,stamp) is not None for p in neighbours if p>0):hit='PRECISION_UNRESOLVED'
            parts.append((Interval(lo,lo,True,True),hit,reason_for(c,projection,lo)))
    refs = {v[1]['startTime']:v[1] for v in parts if isinstance(v[1],dict)}
    ranges=[]
    for key, ref in sorted(refs.items()):
        for r in merge([v[0] for v in parts if isinstance(v[1],dict) and v[1]['startTime']==key]):
            # Three inner probes validate the classifier for each algebraic branch.
            probes=[r.lo+(r.hi-r.lo)*t for t in (.1,.5,.9)] if r.hi is not None and r.lo<r.hi else [r.lo] if r.li else [r.lo+1]
            for p in probes:
                assert activation_signature(c,projection,p,stamp)==ref
            ranges.append(dict(entryRangeId=f'entry-{len(ranges)+1}',priceRange=r.json(),reference=ref))
    exclusions=[]
    reasons={('PRECISION_UNRESOLVED' if v[1]=='PRECISION_UNRESOLVED' else v[2]) for v in parts if not isinstance(v[1],dict)}
    for reason in sorted(reasons):
        for r in merge([v[0] for v in parts if not isinstance(v[1],dict) and ('PRECISION_UNRESOLVED' if v[1]=='PRECISION_UNRESOLVED' else v[2])==reason]):
            exclusions.append(dict(priceRange=r.json(),reason=reason))
    return dict(endpoint=stamp,ranges=sorted(ranges,key=lambda v:v['priceRange']['lower']),exclusions=sorted(exclusions,key=lambda v:v['priceRange']['lower']))


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


def build_relation(c,projection,domain,reference,n,route):
    day=c.period=='day';s=c.wave.sign
    ds,hs,d,h=project_affine_prefix(projection,n)
    prefix=[]
    # entryDomain is the fully proved survival/target-feasibility domain.
    # Its construction includes the no-early-event inequalities.
    # The first bar activation is carried by the original entryRangeId.
    for i in range(1,len(ds)):
        dd,prev=rounded(ds[i],day),rounded(ds[i-1],day)
        prefix.append(condition(scaled(rounded(hs[i],day),s),'gt',const(0)))
        prefix.append(condition(scaled(dd,s),'le',const(s*reference['dif'])))
        # DULL remains only when it does not already meet the 1% turn.
        # NOT(turn) is split by prev=0; branches are evaluated in geometry below.
    prev=rounded(ds[-1],day) if ds else const(c.previous.dif)
    td,th=rounded(d,day),rounded(h,day)
    target=[condition(scaled(td,s),'le',const(s*reference['dif'])),condition(scaled(th,s),'gt' if route=='dif_turn' else 'lt',const(0))]
    if route=='dif_turn':
        target.extend([condition(dict(op='abs',arg=prev),'gt',const(0)),condition(scaled(difference(td,prev),-s),'ge',scaled(dict(op='abs',arg=prev),c.spec.dif_turn_pct/100))])
    return dict(entryDomain=domain.json() if domain else None,reference=reference,route=route,
                prefixConditions=prefix,targetConditions=target),ds,hs,d,h


def turn_threshold(previous, sign, pct, day):
    raw=previous-sign*abs(previous)*pct/100
    if not day:return raw
    tick=math.floor(raw*1000)
    def succeeds(q):
        delta=sign*(q/1000-previous)
        return delta<0 and -delta>=abs(previous)*pct/100
    # Directly identical arithmetic to original step, including float equality.
    candidates=[q for q in range(tick-2,tick+4) if succeeds(q)]
    return (max(candidates) if sign>0 else min(candidates))/1000


def close_bounds(c,reference,ds,d,h,p,route):
    s=c.wave.sign;day=c.period=='day';pct=c.spec.dif_turn_pct
    prev_options=source_options(ds[-1].value(p),day) if ds else (c.previous.dif,)
    b=d.value(p);hb=h.value(p);hd=h.c
    result=Interval()
    r=reference['dif']
    # Cancellation threshold permits equality of the rounded/source DIF.
    cut=(r+(.0005-GUARD if s>0 else -.0005+GUARD) -b)/K if day else (r-b)/K
    bound=Interval(0.,cut,False,not day) if s>0 else Interval(max(0.,cut),None,cut>0 and not day,False)
    result=intersect(result,bound)
    if result is None:return None
    hue=(.0005+GUARD if (s>0)==(route=='dif_turn') else -.0005-GUARD) if day else 0.
    color_cut=(hue-hb)/hd
    is_above=(s>0)==(route=='dif_turn')
    color=Interval(max(0.,color_cut),None) if is_above else Interval(0.,color_cut)
    result=intersect(result,color)
    if result is None:return None
    if route=='dif_turn':
        if 0. in prev_options:return None
        ts=[turn_threshold(v,s,pct,day) for v in prev_options]
        t=min(ts) if s>0 else max(ts)
        cut=(t+(.0005-GUARD if s>0 else -.0005+GUARD)-b)/K if day else (t-b)/K
        turn=Interval(0.,cut,False,not day) if s>0 else Interval(max(0.,cut),None,cut>0 and not day,False)
        result=intersect(result,turn)
    return result


def number_inside(value,lower,places):
    step=Decimal(1).scaleb(-places)
    allowance=Decimal(str(max(1e-7,math.ulp(value)*32)))
    return float((Decimal(str(value))+(allowance if lower else -allowance)).quantize(step,rounding=ROUND_CEILING if lower else ROUND_FLOOR))


def display_range(interval,places=2):
    lo=number_inside(interval.lo,True,places)
    hi=None if interval.hi is None else number_inside(interval.hi,False,places)
    if hi is not None and lo>hi:
        if places==4:return None
        return display_range(interval,4)
    return dict(interval.json(),displayLower=lo,displayUpper=hi,displayPlaces=places)


def branch_points(c,ds,hs,d,h,domain,reference,check):
    """Exhaustive affine/quantization cuts for prefix P and target C ordering.

    Scalar critical levels only. The P price domain is NOT sampled on a grid.
    """
    cuts={domain.lo}
    if domain.hi is not None:cuts.add(domain.hi)
    day=c.period=='day';s=c.wave.sign
    for expr in ds:
        if not expr.p:continue
        roots=[(0-expr.b)/expr.p,(reference['dif']-expr.b)/expr.p]
        if day:
            low=expr.value(domain.lo);high=expr.value(domain.hi) if domain.hi is not None else None
            if high is None:raise ValueError('Daily activation domain must be bounded by DIF qualification')
            start=math.floor(min(low,high)*1000)-1;end=math.ceil(max(low,high)*1000)+1
            for i in range(start,end+1):
                if i%1000==0:check()
                half=(i+.5)/1000
                roots.extend((half+g-expr.b)/expr.p for g in (-GUARD,0.,GUARD))
        cuts.update(r for r in roots if r>domain.lo and (domain.hi is None or r<domain.hi))
    if not day:
        for i in range(1,len(ds)):
            for previous_sign in (-1,1):
                turn=ds[i]-ds[i-1]*(1-c.wave.sign*previous_sign*c.spec.dif_turn_pct/100)
                if turn.p:
                    root=-turn.b/turn.p
                    if root>domain.lo and (domain.hi is None or root<domain.hi):cuts.add(root)
    for expr in hs:
        if expr.p:
            for level in ((-.0005, .0005) if day else (0.,)):
                for g in ((-GUARD,0.,GUARD) if day else (0.,)):
                    root=(level+g-expr.b)/expr.p
                    if root>domain.lo and (domain.hi is None or root<domain.hi):cuts.add(root)
    # Minute branch intersections are inserted by the region solve below.
    return sorted(cuts)


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


def line_for(expr,value):
    return (-expr.p/expr.c,(value-expr.b)/expr.c)


def target_lines(c,reference,ds,d,h,p,route):
    """Each bound is affine in P on this algebraic/quantized branch."""
    s=c.wave.sign;day=c.period=='day';pct=c.spec.dif_turn_pct
    lower=[(0.,0.)];upper=[]
    r=reference['dif']+((.0005-GUARD) if s>0 else (-.0005+GUARD)) if day else reference['dif']
    (upper if s>0 else lower).append(line_for(d,r))
    hue=(.0005+GUARD if (s>0)==(route=='dif_turn') else -.0005-GUARD) if day else 0.
    (lower if (s>0)==(route=='dif_turn') else upper).append(line_for(h,hue))
    if route=='dif_turn':
        previous=ds[-1] if ds else Affine(b=c.previous.dif)
        if day:
            values=source_options(previous.value(p),True)
            if 0. in values:return None
            thresholds=[turn_threshold(q,s,pct,True) for q in values]
            t=(min(thresholds) if s>0 else max(thresholds)) + (.0005-GUARD if s>0 else -.0005+GUARD)
            bound=line_for(d,t)
        else:
            v=previous.value(p)
            if v==0:return None
            multiplier=1-s*(1 if v>0 else -1)*pct/100
            t=previous*multiplier
            bound=((t.p-d.p)/K,(t.b-d.b)/K)
        (upper if s>0 else lower).append(bound)
    return lower,upper


def feasible_for_lines(domain,lines):
    if lines is None:return None
    lower,upper=lines
    for l in lower:
        for u in upper:
            domain=restrict_positive(domain,u[0]-l[0],u[1]-l[1])
            if domain is None:return None
    return domain


def survival_reason(c,reference,ds,hs,p):
    day=c.period=='day';s=c.wave.sign
    for i in range(1,len(ds)):
        reasons=[]
        for prev,d,hue in product(source_options(ds[i-1].value(p),day),source_options(ds[i].value(p),day),source_options(hs[i].value(p),day)):
            if s*hue<=0:reasons.append('COLOR_OR_ZERO')
            elif s*(d-reference['dif'])>0:reasons.append('CANCEL_BEFORE_TARGET')
            else:
                delta=s*(d-prev)
                reasons.append('EARLY_STRUCTURE' if prev!=0 and delta<0 and -delta>=abs(prev)*c.spec.dif_turn_pct/100 else None)
        if any(reasons):
            if any(r is None for r in reasons):return 'PRECISION_UNRESOLVED'
            return reasons[0]
    return None


def robust_survival(c,reference,ds,hs,p):return survival_reason(c,reference,ds,hs,p) is None


def domains_for_target(c,projection,domain,reference,n,check):
    ds,hs,d,h=project_affine_prefix(projection,n)
    if n==1:
        # No intermediate event. A complete color-flip region can prove E_j=E
        # without expanding unrelated DIF quantization plateaus.
        color=feasible_for_lines(domain,target_lines(c,reference,ds,d,h,(domain.lo+(domain.hi or domain.lo+1))/2,'color_flip'))
        if color==domain:
            return [domain],[],(ds,hs,d,h)
    cuts=branch_points(c,ds,hs,d,h,domain,reference,check)
    cells=[]
    for i,lo in enumerate(cuts):
        hi=cuts[i+1] if i+1<len(cuts) else domain.hi
        if hi is None:hi=None
        if hi is not None and hi<=lo:continue
        mid=(lo+hi)/2 if hi is not None else lo+max(1.,lo*.1)
        cell=Interval(lo,hi)
        clipped=intersect(cell,domain)
        if clipped is None:continue
        cells.append((clipped,mid))
    result=[];excluded=[]
    for cell,mid in cells:
        check()
        if not robust_survival(c,reference,ds,hs,mid):
            excluded.append(dict(interval=cell,reason=survival_reason(c,reference,ds,hs,mid)));continue
        for route in ('color_flip','dif_turn'):
            feasible=feasible_for_lines(cell,target_lines(c,reference,ds,d,h,mid,route))
            if feasible:result.append(feasible)
    # Boundary P values may activate the same reference; all adjacent source
    # choices are checked rather than assigning one banker's-rounding result.
    for p in cuts:
        check()
        if p<=0 or not domain.contains(p) or not robust_survival(c,reference,ds,hs,p):continue
        if any(close_bounds(c,reference,ds,d,h,p,r) for r in ('color_flip','dif_turn')):
            result.append(Interval(p,p,True,True))
    return merge(result),excluded,(ds,hs,d,h)


def common_interval(c,reference,ds,d,h,domain,route,check):
    """Full-domain intersection, including every relevant rounded-DIF plateau.

    On a plateau the target bounds are affine, so extrema occur at its two
    ends; enumerating those critical plateaus proves the intersection.
    """
    s=c.wave.sign;day=c.period=='day'
    if domain.hi is None:
        # Minute candidate domains are bounded by DIF qualification. Existing
        # DULL uses a degenerate real P. Unbounded curves are handled by slopes.
        endpoints=[domain.lo]
    else:endpoints=[domain.lo,domain.hi]
    midpoint=sum(endpoints)/len(endpoints)
    lines=target_lines(c,reference,ds,d,h,midpoint,route)
    if lines is None:return None
    lower,upper=lines
    # For a minute abs(P) expression split at zero; extrema remain at endpoints.
    if not day and route=='dif_turn' and ds and ds[-1].p:
        zero=-ds[-1].b/ds[-1].p
        if domain.contains(zero):return None  # no universal turn for previous DIF=0
    values=[]
    for p in endpoints:
        b=close_bounds(c,reference,ds,d,h,p,route)
        if b is None:return None
        values.append(b)
    lo=max(b.lo for b in values)
    hi=None if all(b.hi is None for b in values) else min(b.hi for b in values if b.hi is not None)
    if day and route=='dif_turn' and ds and ds[-1].p:
        prev=ds[-1]
        if domain.hi is None:raise ValueError('Unbounded daily P')
        q0=math.floor(prev.value(domain.lo)*1000)-1
        q1=math.ceil(prev.value(domain.hi)*1000)+1
        for q in range(q0,q1+1):
            if q%1000==0:check()
            # Highest possible previous DIF for bottom; lowest for top.
            shift=GUARD if s>0 else -GUARD
            left=((q-.5)/1000+shift-prev.b)/prev.p
            right=((q+.5)/1000+shift-prev.b)/prev.p
            pl=max(domain.lo,left);ph=min(domain.hi,right)
            if pl>ph:continue
            if q==0:return None
            t=turn_threshold(q/1000,s,c.spec.dif_turn_pct,True)+(.0005-GUARD if s>0 else -.0005+GUARD)
            cl=(t-d.p*pl-d.b)/K
            ch=(t-d.p*ph-d.b)/K
            if s>0:hi=min(hi,min(cl,ch)) if hi is not None else min(cl,ch)
            else:lo=max(lo,max(cl,ch))
    if domain.hi is None:
        for slope,intercept in lower:
            if slope>0:return None
        for slope,intercept in upper:
            if slope<0:return None
    interval=Interval(lo,hi)
    return interval if interval.valid else None


def confirmed_options(c,projection,stamps,p,target,route,reference):
    states=[(clone(c),projection)]
    for stamp in stamps[:-1]:
        newer=[]
        for state,proj in states:
            next_proj,bars=possible_bars(proj,p,stamp,c.period=='day')
            for bar in bars:
                child=clone(state);step=child.step(bar)
                if child.state!='DULL' or child.reference.reference()!=reference:return False
                if any(e['type'] in ('CANCEL','STRUCTURE') for e in step.events):return False
                newer.append((child,next_proj))
        states=newer
    for state,proj in states:
        options=event_options(state,proj,target,stamps[-1],'STRUCTURE')
        if not all(o[2] and o[2]['route']==route and o[2]['eventReference']==reference for o in options):return False
    return True


def displayable_witness(c,projection,domain,reference,n,stamps,check):
    ds,hs,d,h=project_affine_prefix(projection,n)
    # On every complete source plateau, the joint P/C constraints are linear.
    # Their C-projection extrema occur at domain endpoints or line crossings.
    cuts=branch_points(c,ds,hs,d,h,domain,reference,check) if domain.hi!=domain.lo else [domain.lo]
    cells=[domain] if domain.hi==domain.lo else [Interval(a,b) for a,b in zip(cuts,cuts[1:]) if a<b]
    for cell in cells:
        check()
        p=cell.lo if cell.hi==cell.lo else (cell.lo+cell.hi)/2
        for route in ('color_flip','dif_turn'):
            lines=target_lines(c,reference,ds,d,h,p,route)
            feasible=feasible_for_lines(cell,lines)
            if feasible is None:continue
            lower,upper=lines
            points=[feasible.lo,feasible.hi]
            for family in (lower,upper):
                for i,a in enumerate(family):
                    for b in family[i+1:]:
                        if a[0]!=b[0]:
                            root=(b[1]-a[1])/(a[0]-b[0])
                            if feasible.lo<=root<=feasible.hi:points.append(root)
            lowest=min(max(a*x+b for a,b in lower) for x in points)
            highest=max(min(a*x+b for a,b in upper) for x in points) if upper else None
            shown=display_range(Interval(lowest,highest),4)
            if shown is None:continue
            close=shown['displayLower']
            witness=feasible
            for a,b in lower:
                witness=restrict_positive(witness,-a,close-b) if witness else None
            for a,b in upper:
                witness=restrict_positive(witness,a,b-close) if witness else None
            if witness is None:continue
            p=witness.lo if witness.hi==witness.lo else (witness.lo+witness.hi)/2
            if confirmed_options(c,projection,stamps,p,close,route,reference):return True
    return False


def make_result(c,projection,endpoints,check=lambda:None):
    base=dict(status='NO_CANDIDATE',reasonCode=None,targetEndpoint=None,barsAhead=None,
              activation=None,assumption=None,targetEntryRanges=[],targetEntryExclusions=[],relations=[],commonConditions=[],examples=[])
    if c.state=='STRUCTURE':return dict(base,status='CONFIRMED')
    if not c.wave or not c.wave.sign:return dict(base,reasonCode='ZERO_WAVE')
    conditional=c.state=='NONE'
    if conditional:
        if not c.history[c.wave.sign]:return dict(base,reasonCode='NO_REFERENCE')
        activation=solve_entry_ranges(c,projection,endpoints[0],check)
        base['activation']=activation
        if not activation['ranges']:
            if any(v['reason']=='PRECISION_UNRESOLVED' for v in activation['exclusions']):
                return dict(base,status='PRECISION_PENDING',reasonCode='ROUNDING_BOUNDARY')
            return dict(base,reasonCode='NO_ENTRY_RANGE')
        seeds=[(as_interval(r['priceRange']),r['reference'],r['entryRangeId']) for r in activation['ranges']]
    else:
        seeds=[(Interval(c.previous.close,c.previous.close,True,True),c.reference.reference(),None)]
    for j,stamp in enumerate(endpoints,1):
        check()
        if conditional and j==1:continue
        n=j-1
        relations=[];targets=[];commons=[];examples=[];target_exclusions=[];unresolved=False;narrow=False
        for domain,ref,key in seeds:
            if conditional:
                domains,exclusions,coeffs=domains_for_target(c,projection,domain,ref,n,check)
            else:
                coeffs=project_affine_prefix(projection,n)
                ds,hs,d,h=coeffs
                survives=True
                if n:
                    states=[(clone(c),projection)]
                    for time in endpoints[:n]:
                        fresh=[]
                        for child,proj in states:
                            nxt,bars=possible_bars(proj,domain.lo,time,c.period=='day')
                            for bar in bars:
                                copy=clone(child);step=copy.step(bar)
                                if copy.state!='DULL' or copy.reference.reference()!=ref or any(e['type'] in ('CANCEL','STRUCTURE') for e in step.events):
                                    survives=False
                                fresh.append((copy,nxt))
                        states=fresh
                        check()
                        if not survives:break
                domains=[domain] if survives and any(close_bounds(c,ref,ds,d,h,domain.lo,r) for r in ('color_flip','dif_turn')) else []
                exclusions=[]
            unresolved |= any(e['reason']=='PRECISION_UNRESOLVED' for e in exclusions)
            target_exclusions.extend(dict(entryRangeIds=[key] if key else [],priceRange=e['interval'].json(),reason=e['reason']) for e in exclusions)
            if not domains:continue
            if not conditional:
                ds,hs,d,h=coeffs
                if not any(display_range(iv,4) for route in ('dif_turn','color_flip') if (iv:=close_bounds(c,ref,ds,d,h,domain.lo,route)) is not None):
                    narrow=True;continue
            ds,hs,d,h=coeffs
            targets.extend(dict(entryRangeIds=[key] if key else [],priceRange=v.json()) for v in domains)
            for route in ('dif_turn','color_flip'):
                for v in domains:
                    rel,*_=build_relation(c,projection,v if conditional else None,ref,n,route)
                    rel.update(relationId=f'relation-{len(relations)+1}',entryRangeIds=[key] if key else [])
                    if not conditional:
                        def substitute(expr):
                            if isinstance(expr,dict):
                                if expr.get('op')=='affine':
                                    return dict(expr,constant=expr['constant']+expr['pCoefficient']*domain.lo,pCoefficient=0.)
                                return {k:substitute(x) for k,x in expr.items()}
                            if isinstance(expr,list):return [substitute(x) for x in expr]
                            return expr
                        rel=substitute(rel)
                    relations.append(rel)
                    common=common_interval(c,ref,ds,d,h,v,route,check)
                    display=display_range(common) if common else None
                    if display:
                        for p in [v.lo+(v.hi-v.lo)*t for t in (.001,.5,.999)] if v.hi!=v.lo else [v.lo]:
                            assert confirmed_options(c,projection,endpoints[:j],p,display['displayLower'],route,ref)
                            if display['displayUpper'] is not None:
                                assert confirmed_options(c,projection,endpoints[:j],p,display['displayUpper'],route,ref)
                        commons.append(dict(entryRangeIds=[key] if key else [],entryDomain=v.json() if conditional else None,reference=ref,route=route,closeRanges=[dict(display,route=route)]))
            if conditional:
                v=domains[0]
                prices=[number_inside(v.lo,True,2),(v.lo+v.hi)/2,number_inside(v.hi,False,2)] if v.hi is not None else [v.lo+1,v.lo+10,v.lo+100]
                for p in prices:
                    if not v.contains(p):continue
                    p=round(p,2)
                    if not v.contains(p):continue
                    ranges=[]
                    for route in ('dif_turn','color_flip'):
                        iv=close_bounds(c,ref,ds,d,h,p,route)
                        shown=display_range(iv) if iv else None
                        if shown:
                            assert confirmed_options(c,projection,endpoints[:j],p,shown['displayLower'],route,ref)
                            if shown['displayUpper'] is not None:assert confirmed_options(c,projection,endpoints[:j],p,shown['displayUpper'],route,ref)
                            ranges.append(dict(shown,route=route))
                    if ranges:examples.append(dict(preClose=p,entryRangeId=key,closeRanges=ranges))
        if relations and not commons and not examples:
            if not any(displayable_witness(c,projection,domain,ref,j-1,endpoints[:j],check) for domain,ref,key in seeds):
                return dict(base,status='PRECISION_PENDING',reasonCode='NARROW_INTERVAL',targetEndpoint=stamp,barsAhead=j)
        if relations:
            # At least one example per selected reference; filling is deterministic.
            selected=[]
            for _,_,key in seeds:
                v=next((e for e in examples if e['entryRangeId']==key),None)
                if v and v not in selected:selected.append(v)
            for e in examples:
                if len(selected)>=3:break
                if e not in selected:selected.append(e)
            return dict(base,status='CONDITIONAL_ENTRY' if conditional else 'READY',targetEndpoint=stamp,barsAhead=j,
                        assumption=dict(policy='entry_range_then_flat',activationEndpoint=endpoints[0] if conditional else None,
                                        intermediateEndpoints=list(endpoints[:j-1]),intermediateCloseExpression=Affine(p=1).json() if conditional else const(c.previous.close)),
                        targetEntryRanges=targets if conditional else [],targetEntryExclusions=target_exclusions,relations=relations,commonConditions=commons,examples=selected)
        if narrow:
            return dict(base,status='PRECISION_PENDING',reasonCode='NARROW_INTERVAL',targetEndpoint=stamp,barsAhead=j)
        if unresolved:
            return dict(base,status='PRECISION_PENDING',reasonCode='ROUNDING_BOUNDARY',targetEndpoint=stamp,barsAhead=j)
    return dict(base,status='ENTRY_ONLY' if conditional else 'NO_CANDIDATE',reasonCode='NO_CONFIRMATION_IN_HORIZON')
