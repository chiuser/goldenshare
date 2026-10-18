"""Complete activation partitions and original-reference qualification."""
import math
from .forecast_math import Interval, merge, source_options, GUARD, K
from .forecast_detector import activation_signature
from .types import Wave


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
    if c.state == 'NONE' and w.sign == 1 and c.pending_rearm is None:
        for shift in ((-GUARD, 0., GUARD) if day else (0.,)):
            add_root(((.0005 if day else 0.) + shift - b) / K, K)
    for ref in c.history[w.sign]:
        cuts.add(ref.price)
        for d in ((ref.dif-.0005,ref.dif+.0005) if day else (ref.dif,)):
            for g in ((-GUARD,0.,GUARD) if day else (0.,)):
                add_root((d+g-b)/K,K)
    if c.pending_rearm is not None:
        saved=c.pending_rearm['referenceWave']
        cuts.update((saved['price'],c.pending_rearm['nearestPriceGate']))
        for d in ((saved['dif']-.0005,saved['dif']+.0005) if day else (saved['dif'],)):
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
    if c.state == 'NONE' and c.wave.sign == 1 and c.pending_rearm is None:
        # Check the current input, before the conservative segment-DIF floor.
        # Daily raw .0006 is supplied as .001 and already satisfies the rule.
        if min(source_options(dlow, c.period == 'day')) <= 0:
            return False
    if c.period=='day':
        dlow=math.floor(dlow*1000)/1000;dhigh=math.ceil(dhigh*1000)/1000
        hlow=math.floor(hlow*1000)/1000;hhigh=math.ceil(hhigh*1000)/1000
    if c.pending_rearm is not None:
        saved=c.pending_rearm['referenceWave']
        return (reference==Wave(**saved).reference() and c.wave.count+1>=c.spec.min_bars and hhigh<0
                and min(c.wave.dif,dlow)>saved['dif']
                and region.hi<min(saved['price'],c.pending_rearm['nearestPriceGate']))
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
    if c.pending_rearm is not None:
        ref=c.pending_rearm['referenceWave']
        if any(min(w.dif,dd)<=ref['dif'] for dd in ds):
            return 'DIF_NOT_DIVERGENT'
        return 'PRICE_NOT_EXTREME'
    if c.state == 'NONE' and w.sign == 1 and max(ds) <= 0:
        return 'CURRENT_DIF_NOT_POSITIVE'
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
