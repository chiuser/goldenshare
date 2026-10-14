"""Range-model orchestration; only the original detector confirms events."""
from .forecast_spec import FORECAST_SPEC
from .forecast_math import (Interval, Affine, as_interval, project_affine_prefix, display_range, number_inside, const)
from .forecast_detector import clone, possible_bars, confirmed_options
from .forecast_entry import solve_entry_ranges
from .forecast_joint import (build_relation, close_bounds, domains_for_target, common_interval, displayable_witness, target_lines, feasible_for_lines)


def inactive_result(status, reason=None):
    return dict(status=status, reasonCode=reason, targetEndpoint=None, barsAhead=None,
                activation=None, assumption=None, targetEntryRanges=[], targetEntryExclusions=[],
                relations=[], commonConditions=[], examples=[])


def forecast(c,projection,endpoints,check=lambda:None):
    base=inactive_result('NO_CANDIDATE')
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
                survives=True;ambiguous_survival=False
                if n:
                    states=[(clone(c),projection)]
                    for time in endpoints[:n]:
                        fresh=[];outcomes=set()
                        for child,proj in states:
                            check()
                            nxt,bars=possible_bars(proj,domain.lo,time,c.period=='day')
                            for bar in bars:
                                check()
                                copy=clone(child);step=copy.step(bar)
                                outcomes.add((copy.state,tuple((e['type'],e['route']) for e in step.events)))
                                if copy.state!='DULL' or copy.reference.reference()!=ref or any(e['type'] in ('CANCEL','STRUCTURE') for e in step.events):
                                    survives=False
                                fresh.append((copy,nxt))
                        ambiguous_survival |= len(outcomes)>1
                        states=fresh
                        check()
                        if not survives:break
                domains=[domain] if survives and any(close_bounds(c,ref,ds,d,h,domain.lo,r) for r in ('color_flip','dif_turn')) else []
                exclusions=[]
                if ambiguous_survival:unresolved=True
                elif survives and not domains:
                    unresolved |= any(feasible_for_lines(domain,target_lines(c,ref,ds,d,h,domain.lo,r,possible=True)) for r in ('color_flip','dif_turn'))
            unresolved |= any(e['reason']=='PRECISION_UNRESOLVED' for e in exclusions)
            target_exclusions.extend(dict(entryRangeIds=[key] if key else [],priceRange=e['interval'].json(),reason=e['reason']) for e in exclusions)
            if not domains:continue
            if not conditional:
                ds,hs,d,h=coeffs
                if not any(display_range(iv,FORECAST_SPEC.price_boundary_places) for route in ('dif_turn','color_flip') if (iv:=close_bounds(c,ref,ds,d,h,domain.lo,route)) is not None):
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
                            assert confirmed_options(c,projection,endpoints[:j],p,display['displayLower'],route,ref,check)
                            if display['displayUpper'] is not None:
                                assert confirmed_options(c,projection,endpoints[:j],p,display['displayUpper'],route,ref,check)
                        commons.append(dict(entryRangeIds=[key] if key else [],entryDomain=v.json() if conditional else None,reference=ref,route=route,closeRanges=[dict(display,route=route)]))
            if conditional:
                v=domains[0]
                prices=[number_inside(v.lo,True,FORECAST_SPEC.price_display_places),(v.lo+v.hi)/2,number_inside(v.hi,False,FORECAST_SPEC.price_display_places)] if v.hi is not None else [v.lo+1,v.lo+10,v.lo+100]
                for p in prices:
                    if not v.contains(p):continue
                    p=round(p,FORECAST_SPEC.price_display_places)
                    if not v.contains(p):continue
                    ranges=[]
                    for route in ('dif_turn','color_flip'):
                        iv=close_bounds(c,ref,ds,d,h,p,route)
                        shown=display_range(iv) if iv else None
                        if shown:
                            assert confirmed_options(c,projection,endpoints[:j],p,shown['displayLower'],route,ref,check)
                            if shown['displayUpper'] is not None:assert confirmed_options(c,projection,endpoints[:j],p,shown['displayUpper'],route,ref,check)
                            ranges.append(dict(shown,route=route))
                    if ranges:examples.append(dict(preClose=p,entryRangeId=key,closeRanges=ranges))
        if relations and not commons and not examples:
            for target in targets:
                key=target['entryRangeIds'][0] if target['entryRangeIds'] else None
                seed=next((v for v in seeds if v[2]==key),None)
                if seed:
                    witness=displayable_witness(c,projection,as_interval(target['priceRange']),seed[1],j-1,endpoints[:j],check)
                    if witness:examples.append(dict(witness,entryRangeId=key));break
            if not examples:
                return dict(base,status='PRECISION_PENDING',reasonCode='NARROW_INTERVAL',targetEndpoint=stamp,barsAhead=j)
        if relations:
            # At least one example per selected reference; filling is deterministic.
            selected=[]
            for _,_,key in seeds:
                v=next((e for e in examples if e['entryRangeId']==key),None)
                if v and v not in selected:selected.append(v)
            for e in examples:
                if len(selected)>=FORECAST_SPEC.explanation_sample_count:break
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
