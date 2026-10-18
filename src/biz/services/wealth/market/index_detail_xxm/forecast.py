"""Single nearest-target solver over complete, causal reference paths."""
from .forecast_spec import FORECAST_SPEC
from .forecast_math import Interval, Affine, as_interval, project_affine_prefix, display_range, number_inside, const
from .forecast_entry import solve_entry_ranges
from .forecast_joint import close_bounds, common_interval, target_lines, feasible_for_lines
from .forecast_paths import partition_prefix_paths, build_path_relation, validate_path_options, solve_next_bar_outcomes, ReferencePath, path_displayable_witness


def inactive_result(status, reason=None):
    return dict(status=status, reasonCode=reason, targetEndpoint=None, barsAhead=None,
                activation=None, assumption=None, targetEntryRanges=[], targetEntryExclusions=[],
                relations=[], commonConditions=[], examples=[], nextBarOutcomes=None)


def forecast(c,projection,endpoints,check=lambda:None):
    base=inactive_result('NO_CANDIDATE')
    if c.state=='STRUCTURE':return dict(base,status='CONFIRMED')
    if not c.wave or not c.wave.sign:return dict(base,reasonCode='ZERO_WAVE')
    base['nextBarOutcomes']=solve_next_bar_outcomes(c,projection,endpoints[0],check)
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
            parts,exclusions,coeffs=partition_prefix_paths(c,projection,domain,ref,endpoints[:n],check)
            unresolved |= any(e['reason']=='PRECISION_UNRESOLVED' for e in exclusions)
            target_exclusions.extend(dict(entryRangeIds=[key] if key else [],priceRange=e['interval'].json(),reason=e['reason']) for e in exclusions)
            if not parts:continue
            ds,hs,d,h=coeffs
            targets.extend(dict(entryRangeIds=[key] if key else [],priceRange=part.domain.json()) for part in parts)
            for part in parts:
                v,path=part.domain,part.path
                final=path.final
                route_ids={}
                for route in ('dif_turn','color_flip'):
                    if feasible_for_lines(v,target_lines(c,final,ds,d,h,v.lo if v.lo==v.hi else (v.lo+(v.hi or v.lo+1))/2,route)) is None:
                        if v.lo!=v.hi or close_bounds(c,final,ds,d,h,v.lo,route) is None:continue
                    rel=build_path_relation(c,projection,v if conditional else None,path,n,route,endpoints[:n])
                    rel.update(relationId=f'relation-{len(relations)+1}',entryRangeIds=[key] if key else [])
                    route_ids[route]=rel['relationId']
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
                    common=common_interval(c,final,ds,d,h,v,route,check)
                    display=display_range(common) if common else None
                    if display:
                        for p in [v.lo+(v.hi-v.lo)*t for t in (.001,.5,.999)] if v.hi!=v.lo else [v.lo]:
                            assert validate_path_options(c,projection,endpoints[:j],p,display['displayLower'],route,path,check)
                            if display['displayUpper'] is not None:
                                assert validate_path_options(c,projection,endpoints[:j],p,display['displayUpper'],route,path,check)
                        commons.append(dict(relationId=rel['relationId'],entryRangeIds=[key] if key else [],entryDomain=v.json() if conditional else None,reference=final,route=route,closeRanges=[dict(display,route=route)]))
                if conditional:
                    prices=[number_inside(v.lo,True,2),(v.lo+v.hi)/2,number_inside(v.hi,False,2)] if v.hi is not None else [v.lo+1,v.lo+10,v.lo+100]
                    for p in prices:
                        p=round(p,2)
                        if not v.contains(p):continue
                        ranges=[]
                        for route,rid in route_ids.items():
                            iv=close_bounds(c,final,ds,d,h,p,route);shown=display_range(iv) if iv else None
                            if shown:
                                assert validate_path_options(c,projection,endpoints[:j],p,shown['displayLower'],route,path,check)
                                if shown['displayUpper'] is not None:assert validate_path_options(c,projection,endpoints[:j],p,shown['displayUpper'],route,path,check)
                                ranges.append(dict(shown,route=route,relationId=rid))
                        if ranges:examples.append(dict(preClose=p,entryRangeId=key,closeRanges=ranges))
        if relations and not commons and not examples:
            for target in targets:
                key=target['entryRangeIds'][0] if target['entryRangeIds'] else None
                seed=next((v for v in seeds if v[2]==key),None)
                if seed and conditional:
                    relation=next(r for r in relations if r['entryRangeIds']==[key] and r['entryDomain']==target['priceRange'])
                    path=ReferencePath(relation['initialReference'],tuple(relation['referenceTransitions']))
                    witness=path_displayable_witness(c,projection,as_interval(target['priceRange']),path,j-1,endpoints[:j],check)
                    if witness:
                        for v in witness['closeRanges']:
                            v['relationId']=next(r['relationId'] for r in relations if r['entryRangeIds']==[key] and r['route']==v['route'] and as_interval(r['entryDomain']).contains(witness['preClose']))
                        examples.append(dict(witness,entryRangeId=key));break
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
