"""Offline R1 path proof. Uses existing affine geometry, never patches product.

After preflight this module is to become the sole product forecast_paths module.
Cuts exhaust the predicates; kernel replays verify, rather than define, domains.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from itertools import product

from src.biz.services.wealth.market.index_detail_xxm.forecast_math import (
    Affine, Interval, GUARD, K, intersect, merge, subtract, source_options,
    project_affine_prefix, rounded, const, condition, scaled, display_range, restrict_positive,
)
from src.biz.services.wealth.market.index_detail_xxm.forecast_entry import entry_partition
from src.biz.services.wealth.market.index_detail_xxm.forecast_joint import (
    branch_points, domains_for_target, target_lines, feasible_for_lines,
    close_bounds, build_relation, turn_threshold,
)
from src.biz.services.wealth.market.index_detail_xxm.forecast_detector import possible_bars
from .reference_rescue import BottomDullRescueCalculator


def clone(c):
    child=BottomDullRescueCalculator(period=c.period,source_identity=c.source_identity,ts_code=c.ts_code,spec=c.spec)
    child.restore(c.snapshot())
    return child


@dataclass(frozen=True)
class ReferencePath:
    initial: dict
    transitions: tuple = ()

    @property
    def final(self):
        return self.transitions[-1]['toReference'] if self.transitions else self.initial

    def reference_at(self, stamp):
        ref = self.initial
        for transition in self.transitions:
            if transition['endpoint'] <= stamp:
                ref = transition['toReference']
        return ref


@dataclass(frozen=True)
class PathCell:
    domain: Interval
    path: ReferencePath


def inner(domain):
    return domain.lo if domain.lo == domain.hi else ((domain.lo+domain.hi)/2 if domain.hi is not None else domain.lo+max(1.,domain.lo*.1))


def cells(domain, cuts):
    """Open cells plus exact point cells form a disjoint, exhaustive domain."""
    cuts = sorted({domain.lo, *[p for p in cuts if p >= domain.lo and (domain.hi is None or p <= domain.hi)], *([domain.hi] if domain.hi is not None else [])})
    for i, lo in enumerate(cuts):
        if domain.contains(lo):
            yield Interval(lo,lo,True,True)
        hi = cuts[i+1] if i+1 < len(cuts) else domain.hi
        if hi is None or hi > lo:
            clipped = intersect(domain, Interval(lo,hi))
            if clipped is not None:
                yield clipped


def _prefix_signature(c, ds, hs, p, stamps, initial):
    """All rounded predicate states, with a fixed original pool and flat P.

    Constant signs on a cut cell prove the signature across that entire cell.
    No future history or skipped cancellation can participate in this path.
    """
    day, sign = c.period == 'day', c.wave.sign
    states = [(initial, c.wave.dif, c.previous.dif, ())]
    price = max(c.wave.price,p) if sign > 0 else min(c.wave.price,p)
    pool = list(reversed(c.history[sign]))
    nearest = pool[0].price if pool else None
    pool.sort(key=lambda w: sign*w.dif,reverse=True)
    stopped = set()
    for i, (d, h, stamp) in enumerate(zip(ds,hs,stamps)):
        newer = []
        for (ref, extreme, previous, transitions), dd, hh in product(states,source_options(d.value(p),day),source_options(h.value(p),day)):
            ex = max(extreme,dd) if sign > 0 else min(extreme,dd)
            if c.state == 'NONE' and i == 0:
                # Full activation domain already proved by solve_entry_ranges.
                newer.append((ref,ex,dd,transitions))
                continue
            if hh == 0:
                stopped.add('COLOR_OR_ZERO'); continue
            if sign*hh < 0:
                stopped.add('CANCEL_BEFORE_TARGET' if sign*(dd-ref['dif'])>0 else 'EARLY_STRUCTURE'); continue
            if sign*(ex-ref['dif'])>0:
                replacement = next((w.reference() for w in pool if sign == -1 and price < nearest and price < w.price and ex > w.dif),None)
                if replacement is None:
                    stopped.add('CANCEL_BEFORE_TARGET'); continue
                transitions = (*transitions,dict(endpoint=stamp,fromReference=ref,toReference=replacement))
                ref = replacement
            delta = sign*(dd-previous)
            if previous != 0 and delta < 0 and -delta >= abs(previous)*c.spec.dif_turn_pct/100:
                stopped.add('EARLY_STRUCTURE'); continue
            newer.append((ref,ex,dd,transitions))
        # All distinct rounding states matter, but identical states are shared.
        states = list({json.dumps(v,sort_keys=True):v for v in newer}.values())
        if not states: break
    paths = {json.dumps(v[3],sort_keys=True):v[3] for v in states}
    if stopped:
        if states or len(stopped)>1:return None,'PRECISION_UNRESOLVED'
        return None,next(iter(stopped))
    if len(paths)!=1:return None,'PRECISION_UNRESOLVED'
    return ReferencePath(initial,next(iter(paths.values()))),None


def _flat_cannot_switch(c, domain, reference, n):
    # Ordinary strongest-first activation already chose the strongest eligible
    # ref. Flat P cannot improve segment price, count is already sufficient,
    # and segment DIF only worsens. Thus no later stronger ref can qualify.
    return c.wave.sign > 0 or (c.state == 'NONE' and (c.pending_rearm is None or n == 1))


def path_branch_points(c, coeffs, domain, reference, check):
    ds,hs,d,h = coeffs
    cuts = {domain.lo, c.wave.price}
    for ref in c.history[c.wave.sign]:
        cuts.add(ref.price)
        cuts.update(branch_points(c,ds,hs,d,h,domain,ref.reference(),check))
    cuts.update(branch_points(c,ds,hs,d,h,domain,reference,check))
    if c.state == 'DULL' and ds and ds[0].p:
        previous = c.previous.dif
        level = previous-c.wave.sign*abs(previous)*c.spec.dif_turn_pct/100
        for shift in ((-.0005-GUARD,-.0005+GUARD,.0005-GUARD,.0005+GUARD) if c.period=='day' else (0.,)):
            cuts.add((level+shift-ds[0].b)/ds[0].p)
    return sorted(p for p in cuts if math.isfinite(p) and p>=domain.lo and (domain.hi is None or p<=domain.hi))


def partition_prefix_paths(c, projection, domain, initial, stamps, check=lambda:None):
    n = len(stamps)
    coeffs = project_affine_prefix(projection,n)
    path = ReferencePath(initial)
    if c.state == 'NONE' and _flat_cannot_switch(c,domain,initial,n):
        domains,excluded,_ = domains_for_target(c,projection,domain,initial,n,check)
        return [PathCell(v,path) for v in domains],excluded,coeffs
    ds,hs,d,h = coeffs
    cuts = path_branch_points(c,coeffs,domain,initial,check) if domain.lo!=domain.hi else [domain.lo]
    bands=[]
    if c.period!='day' and domain.lo!=domain.hi:
        # Outward error enclosure for factored prefix roots. Exact prices are
        # harmless extra cuts; no detector epsilon is introduced.
        slopes=[abs(v.p) for v in ds+hs if v.p]
        for root in tuple(cuts):
            if not slopes:break
            error=16*max(1,n)*math.ulp(max(abs(projection.e12),abs(projection.e26),abs(root),1.))/min(slopes)
            band=intersect(domain,Interval(max(0.,root-error),root+error,True,True))
            if band:
                bands.append(band);cuts.extend([band.lo,*([band.hi] if band.hi is not None else [])])
    parts,excluded = [],[]
    for cell in cells(domain,cuts):
        check(); p=inner(cell)
        if any(v.contains(p) for v in bands):
            excluded.append(dict(interval=cell,reason='PRECISION_UNRESOLVED'));continue
        path,reason = _prefix_signature(c,ds,hs,p,stamps,initial)
        if reason:
            excluded.append(dict(interval=cell,reason=reason));continue
        feasible=[];possible=[]
        for route in ('color_flip','dif_turn'):
            region=feasible_for_lines(cell,target_lines(c,path.final,ds,d,h,p,route))
            if region:feasible.append(region)
            relaxed=feasible_for_lines(cell,target_lines(c,path.final,ds,d,h,p,route,possible=True))
            if relaxed:possible.append(relaxed)
        # Exact point cells use source-equality semantics, not strict line
        # intersections that would incorrectly remove a closed boundary point.
        if cell.lo==cell.hi:
            feasible=[cell] if any(close_bounds(c,path.final,ds,d,h,p,r) for r in ('dif_turn','color_flip')) else []
        valid=merge(feasible)
        parts.extend(PathCell(v,path) for v in valid)
        for rest in subtract(cell,valid):
            uncertain=merge([v for v in (intersect(rest,q) for q in possible) if v])
            excluded.extend(dict(interval=v,reason='PRECISION_UNRESOLVED') for v in uncertain)
            excluded.extend(dict(interval=v,reason='NO_TARGET_SOLUTION') for v in subtract(rest,uncertain))
    grouped={}
    for part in parts:
        key=json.dumps([part.path.initial,part.path.transitions],sort_keys=True)
        grouped.setdefault(key,(part.path,[]))[1].append(part.domain)
    parts=[PathCell(v,path) for path,ranges in grouped.values() for v in merge(ranges)]
    return parts,excluded,coeffs


def validate_path_options(c, projection, stamps, p, target, route, path, check=lambda:None):
    states=[(clone(c),projection)]
    for stamp in stamps[:-1]:
        newer=[]
        for state,proj in states:
            check(); nxt,bars=possible_bars(proj,p,stamp,c.period=='day')
            for bar in bars:
                child=clone(state); step=child.step(bar)
                if child.state!='DULL' or child.reference.reference()!=path.reference_at(stamp):return False
                if any(e['type'] in ('CANCEL','STRUCTURE') for e in step.events):return False
                newer.append((child,nxt))
        states=list({json.dumps(state.snapshot(),sort_keys=True):(state,proj) for state,proj in newer}.values())
    for state,proj in states:
        nxt,bars=possible_bars(proj,target,stamps[-1],c.period=='day')
        for bar in bars:
            check(); child=clone(state); step=child.step(bar)
            event=next((e for e in step.events if e['type']=='STRUCTURE'),None)
            if event is None or event['route']!=route or event['eventReference']!=path.final:return False
    return True


def build_path_relation(c,projection,domain,path,n,route,stamps):
    rel,ds,hs,d,h=build_relation(c,projection,domain,path.final,n,route)
    prefix=[]; sign=c.wave.sign
    for i in range(1 if c.state=='NONE' else 0,len(ds)):
        ref=path.reference_at(stamps[i])
        prefix.extend([condition(scaled(rounded(hs[i],c.period=='day'),sign),'gt',const(0)),
                       condition(scaled(rounded(ds[i],c.period=='day'),sign),'le',const(sign*ref['dif']))])
        switch=next((v for v in path.transitions if v['endpoint']==stamps[i]),None)
        if switch:
            prefix.append(condition(rounded(ds[i],c.period=='day'),'lt',const(switch['fromReference']['dif'])))
            prefix.append(condition(rounded(ds[i],c.period=='day'),'gt',const(ref['dif'])))
            if c.wave.price>=min(ref['price'],c.history[-1][-1].price):
                prefix.append(condition(Affine(p=1).json(),'lt',const(min(ref['price'],c.history[-1][-1].price))))
    rel.update(initialReference=path.initial,referenceTransitions=list(path.transitions),prefixConditions=prefix)
    return rel


def path_displayable_witness(c,projection,domain,path,n,stamps,check):
    """Exact line intersections select a reproducible explanatory P/C point."""
    ds,hs,d,h=project_affine_prefix(projection,n)
    cuts=branch_points(c,ds,hs,d,h,domain,path.final,check) if domain.hi!=domain.lo else [domain.lo]
    for cell in cells(domain,cuts):
        check();p=inner(cell)
        for route in ('color_flip','dif_turn'):
            lines=target_lines(c,path.final,ds,d,h,p,route)
            feasible=feasible_for_lines(cell,lines)
            if feasible is None:continue
            lower,upper=lines
            points=[feasible.lo,*([feasible.hi] if feasible.hi is not None else [])]
            for family in (lower,upper):
                for i,a in enumerate(family):
                    for b in family[i+1:]:
                        if a[0]!=b[0]:
                            root=(b[1]-a[1])/(a[0]-b[0])
                            if root>=feasible.lo and (feasible.hi is None or root<=feasible.hi):points.append(root)
            low=min(max(a*x+b for a,b in lower) for x in points)
            high=max(min(a*x+b for a,b in upper) for x in points) if upper else None
            shown=display_range(Interval(low,high),4)
            if shown is None:continue
            close=shown['displayLower'];witness=feasible
            for a,b in lower:
                witness=restrict_positive(witness,-a,close-b) if witness else None
            for a,b in upper:
                witness=restrict_positive(witness,a,b-close) if witness else None
            if witness is None:continue
            p=inner(witness)
            for candidate in (round(p,2),round(p,4)):
                if not witness.contains(candidate):continue
                iv=close_bounds(c,path.final,ds,d,h,candidate,route)
                shown=display_range(iv) if iv else None
                if shown and validate_path_options(c,projection,stamps,candidate,shown['displayLower'],route,path,check) and (shown['displayUpper'] is None or validate_path_options(c,projection,stamps,candidate,shown['displayUpper'],route,path,check)):
                    return dict(preClose=candidate,closeRanges=[dict(shown,route=route)])
    return None


def _outcome(c,projection,p,stamp):
    initial=c.reference.reference(); results=[]
    nxt,bars=possible_bars(projection,p,stamp,c.period=='day')
    for bar in bars:
        child=clone(c); step=child.step(bar)
        event=next((e for e in step.events if e['type'] in ('STRUCTURE','CANCEL')),None)
        if event:
            results.append(dict(outcome='STRUCTURE_CONFIRMED' if event['type']=='STRUCTURE' else 'CANCELLED',reference=event['eventReference'],route=event['route']))
        elif bar.hist==0:results.append(dict(outcome='ZERO_RESET',reference=None,route=None))
        elif child.state=='DULL':results.append(dict(outcome='PRESERVED' if child.reference.reference()==initial else 'REFERENCE_SWITCHED',reference=child.reference.reference(),route=None))
        else:raise AssertionError('Unclassified next-bar state')
    return results[0] if all(r==results[0] for r in results) else dict(outcome='PRECISION_UNRESOLVED',reference=None,route=None)


def solve_next_bar_outcomes(c,projection,stamp,check=lambda:None):
    if c.state!='DULL' or c.wave.sign!=-1:return None
    cuts,bands=entry_partition(c,projection)
    b=projection.e12*11/13-projection.e26*25/27
    threshold=turn_threshold(c.previous.dif,-1,c.spec.dif_turn_pct,c.period=='day')
    for shift in ((-.0005-GUARD,-.0005+GUARD,.0005-GUARD,.0005+GUARD) if c.period=='day' else (0.,)):
        root=(threshold+shift-b)/K
        if root>0:
            error=8*math.ulp(max(abs(projection.e12),abs(projection.e26),abs(root),1.))/K
            band=Interval(max(0.,root-error),root+error,True,True)
            cuts.extend((band.lo,root,band.hi));bands.append(band)
    groups={}
    for cell in cells(Interval(),cuts):
        check(); p=inner(cell)
        ambiguous=any(v.contains(p) for v in bands)
        outcome=dict(outcome='PRECISION_UNRESOLVED',reference=None,route=None) if ambiguous else _outcome(c,projection,p,stamp)
        key=json.dumps(outcome,sort_keys=True)
        groups.setdefault(key,(outcome,[]))[1].append(cell)
    branches=[]
    for outcome,ranges in groups.values():
        for domain in merge(ranges):branches.append(dict(priceRange=domain.json(),**outcome))
    branches.sort(key=lambda v:(v['priceRange']['lower'],not v['priceRange']['lowerInclusive']))
    for i,branch in enumerate(branches,1):branch['branchId']=f'next-{i}'
    return dict(endpoint=stamp,initialReference=c.reference.reference(),branches=branches)
