"""Joint P/C geometry, survival and whole-domain intersections."""
import math
from itertools import product
from .forecast_math import (Interval, Affine, GUARD, K, intersect, merge, restrict_positive, source_options, project_affine_prefix, rounded, const, condition, scaled, difference, subtract)
from .forecast_spec import FORECAST_SPEC
from .forecast_math import display_range
from .forecast_detector import confirmed_options


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


def line_for(expr,value):
    return (-expr.p/expr.c,(value-expr.b)/expr.c)


def target_lines(c,reference,ds,d,h,p,route,possible=False):
    """Each bound is affine in P on this algebraic/quantized branch."""
    s=c.wave.sign;day=c.period=='day';pct=c.spec.dif_turn_pct
    lower=[(0.,0.)];upper=[]
    guard=-GUARD if possible else GUARD
    r=reference['dif']+((.0005-guard) if s>0 else (-.0005+guard)) if day else reference['dif']
    (upper if s>0 else lower).append(line_for(d,r))
    hue=(.0005+guard if (s>0)==(route=='dif_turn') else -.0005-guard) if day else 0.
    (lower if (s>0)==(route=='dif_turn') else upper).append(line_for(h,hue))
    if route=='dif_turn':
        previous=ds[-1] if ds else Affine(b=c.previous.dif)
        if day:
            values=source_options(previous.value(p),True)
            if possible:values=tuple(q for q in values if q!=0)
            if not values or 0. in values:return None
            thresholds=[turn_threshold(q,s,pct,True) for q in values]
            t=((max(thresholds) if s>0 else min(thresholds)) if possible else (min(thresholds) if s>0 else max(thresholds))) + (.0005-guard if s>0 else -.0005+guard)
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
            if hue==0:reasons.append('COLOR_OR_ZERO')
            elif s*(d-reference['dif'])>0:reasons.append('CANCEL_BEFORE_TARGET')
            elif s*hue<0:reasons.append('EARLY_STRUCTURE')
            else:
                delta=s*(d-prev)
                reasons.append('EARLY_STRUCTURE' if prev!=0 and delta<0 and -delta>=abs(prev)*c.spec.dif_turn_pct/100 else None)
        if any(reasons):
            if len(set(reasons))!=1:return 'PRECISION_UNRESOLVED'
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
    result=[];excluded=[];possible=[]
    for cell,mid in cells:
        check()
        if not robust_survival(c,reference,ds,hs,mid):
            excluded.append(dict(interval=cell,reason=survival_reason(c,reference,ds,hs,mid)));continue
        for route in ('color_flip','dif_turn'):
            feasible=feasible_for_lines(cell,target_lines(c,reference,ds,d,h,mid,route))
            if feasible:result.append(feasible)
            relaxed=feasible_for_lines(cell,target_lines(c,reference,ds,d,h,mid,route,possible=True))
            if relaxed:possible.append(relaxed)
    # Boundary P values may activate the same reference; all adjacent source
    # choices are checked rather than assigning one banker's-rounding result.
    for p in cuts:
        check()
        if p<=0 or not domain.contains(p):continue
        reason=survival_reason(c,reference,ds,hs,p)
        if reason:
            excluded.append(dict(interval=Interval(p,p,True,True),reason=reason));continue
        if any(close_bounds(c,reference,ds,d,h,p,r) for r in ('color_flip','dif_turn')):
            result.append(Interval(p,p,True,True))
    valid=merge(result)
    # Every excluded price receives a reason; sparse explanatory samples do
    # not establish feasibility or its complement.
    labelled=[]
    for reason in sorted({e['reason'] for e in excluded}):
        for iv in merge([e['interval'] for e in excluded if e['reason']==reason]):
            for part in subtract(iv,valid):labelled.append(dict(interval=part,reason=reason))
    remaining=subtract(domain,valid+[e['interval'] for e in labelled])
    uncertain=[]
    for part in remaining:
        for relaxed in possible:
            iv=intersect(part,relaxed)
            if iv:uncertain.append(iv)
    uncertain=merge(uncertain)
    labelled.extend(dict(interval=iv,reason='PRECISION_UNRESOLVED') for iv in uncertain)
    for part in remaining:
        labelled.extend(dict(interval=iv,reason='NO_TARGET_SOLUTION') for iv in subtract(part,uncertain))
    return valid,labelled,(ds,hs,d,h)


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
            shown=display_range(Interval(lowest,highest),FORECAST_SPEC.price_boundary_places)
            if shown is None:continue
            close=shown['displayLower']
            witness=feasible
            for a,b in lower:
                witness=restrict_positive(witness,-a,close-b) if witness else None
            for a,b in upper:
                witness=restrict_positive(witness,a,b-close) if witness else None
            if witness is None:continue
            p=witness.lo if witness.hi==witness.lo else (witness.lo+witness.hi)/2
            # A displayed witness must itself be reproducible; it is an example,
            # never a required exact preceding close.
            for candidate in (round(p,2),round(p,4)):
                if not witness.contains(candidate):continue
                iv=close_bounds(c,reference,ds,d,h,candidate,route)
                shown=display_range(iv) if iv else None
                if shown and confirmed_options(c,projection,stamps,candidate,shown['displayLower'],route,reference,check) and (shown['displayUpper'] is None or confirmed_options(c,projection,stamps,candidate,shown['displayUpper'],route,reference,check)):
                    return dict(preClose=candidate,closeRanges=[dict(shown,route=route)])
    return None
