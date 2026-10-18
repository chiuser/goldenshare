"""Offline R1 forecast preflight. Explicit candidate, no runtime patching."""
from src.biz.services.wealth.market.index_detail_xxm.forecast_spec import FORECAST_SPEC
from src.biz.services.wealth.market.index_detail_xxm.forecast_math import (Interval, Affine, as_interval, project_affine_prefix, display_range, number_inside, const)
from src.biz.services.wealth.market.index_detail_xxm.forecast_entry import solve_entry_ranges
from src.biz.services.wealth.market.index_detail_xxm.forecast_joint import (close_bounds, common_interval, displayable_witness, target_lines, feasible_for_lines)
from .reference_rescue_paths import (partition_prefix_paths, build_path_relation, validate_path_options, solve_next_bar_outcomes, ReferencePath, path_displayable_witness)


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


def make_display(result,period,through,mode,context,check=lambda:None):
    from src.biz.services.wealth.market.index_detail_xxm.forecast_text import make_display as existing, price_text, time_text
    from src.biz.services.wealth.market.index_detail_xxm.forecast_math import intersect
    shown=existing(result,period,through,mode,context,check)
    outcomes=result.get('nextBarOutcomes')
    scale=context.get('nextBar')
    if not outcomes or not scale or scale.get('reason') is not None:return shown
    lines=[]
    for part in outcomes['branches']:
        check()
        if part['outcome'] not in ('CANCELLED','REFERENCE_SWITCHED'):continue
        interval=as_interval(part['priceRange'])
        if intersect(interval,as_interval(scale['priceRange'])) is None:continue
        text=price_text(interval,(FORECAST_SPEC.structure_text_places,FORECAST_SPEC.price_display_places,FORECAST_SPEC.price_boundary_places))
        if text:
            lines.append(f'钝化失效：{time_text(outcomes["endpoint"],period)}收盘{text}，底钝化消失。' if part['outcome']=='CANCELLED' else
                         f'钝化延续：{time_text(outcomes["endpoint"],period)}收盘{text}，底钝化仍有效，结构条件需重新计算。')
    if lines:shown['conditionsText']+='\n'+'\n'.join(lines)
    return shown


def main():
    """Bounded frozen preflight; no HTTP, live source or installation."""
    import argparse
    from dataclasses import asdict
    import json
    from pathlib import Path
    import time
    from .acceptance import load_source,sha
    from . import bottom_history_acceptance as b
    from .reference_rescue import BottomDullRescueCalculator,R1_POLICY
    from .reference_rescue_paths import clone
    from src.biz.services.wealth.market.index_detail_xxm.spec import XxmSpec
    from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection,ProjectionPrecisionError
    from src.biz.services.wealth.market.index_detail_xxm.forecast_text import build_display_context,reference_band
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[4]
    source=root/'reports/xxm_source_audit_20261013_213852'
    r1=root/'reports/xxm_reference_rescue_20261017_01/run_01'
    frozen=root/'reports/xxm_same_segment_precheck_20261016_04'
    protected=json.loads((r1/'summary.json').read_text())['protectedSha256']
    assert all(sha(root/p)==h for p,h in protected.items())
    calendar=b.calendar_rows(source)
    summary=dict(policyHash=R1_POLICY.policy_hash,codeSha256={str(p.relative_to(root)):sha(p) for p in (Path(__file__),Path(__file__).with_name('reference_rescue_paths.py'))},
                 periods={},softwareUniqueFormulaProven=False,liveSourceRead=False,formalHttpBudgetTested=False)
    def save(name,value):
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    try:
        for period in ('day','m60','m90','m120'):
            bars=load_source(source,period)
            baseline=json.loads((frozen/f'forecasts_{period}.json').read_text())['results']
            wanted={v['rows'] for v in baseline}
            old=json.loads((r1/f'result_{period}.json').read_text())
            index={bar.time:n for n,bar in enumerate(bars,1)}
            for rescue in old['rescues']:
                n=index[rescue['time']]
                wanted.update(v for v in (n-1,n,n+1) if 0<v<=len(bars))
                next_structure=next((e['time'] for e in old['events'] if e['time']>rescue['time'] and e['type']=='STRUCTURE' and e['direction']=='BOTTOM'),None)
                if next_structure:wanted.add(index[next_structure])
            gate_summaries={}
            for gate in (.75,1.,1.2):
                calc=BottomDullRescueCalculator(period=period,source_identity='r1-forecast-precheck:'+period,spec=XxmSpec(dif_turn_pct=gate))
                snapshots={};confirmed={};events=[];last=None
                for n,bar in enumerate(bars,1):
                    step=calc.step(bar);events.extend(step.events)
                    last=next((e for e in step.events if e['type']=='STRUCTURE'),last)
                    if n in wanted:snapshots[n]=calc.snapshot();confirmed[n]=last
                if gate==1.:
                    fields=('time','type','direction','route','eventReference','fromState')
                    assert [{k:e[k] for k in fields} for e in events]==[{k:e[k] for k in fields} for e in old['events']]
                results=[]
                for n in sorted(wanted):
                    child=BottomDullRescueCalculator(period=period,source_identity=calc.source_identity,spec=calc.spec);child.restore(snapshots[n]);before=child.snapshot()
                    started=time.perf_counter()
                    def check():
                        if time.perf_counter()-started>.2:raise TimeoutError('200ms model budget')
                    if child.state=='STRUCTURE' or confirmed[n] and confirmed[n]['time']==bars[n-1].time:
                        result=inactive_result('CONFIRMED')
                    else:
                        try:
                            projection=recover_projection(tuple(bars[:n]),period,check)
                            result=forecast(child,projection,b.future_slots(calendar,period,bars[n-1].time),check)
                        except ProjectionPrecisionError as exc:result=inactive_result('PRECISION_PENDING',exc.reason)
                    check()
                    result['direction']='TOP' if child.wave.sign>0 else 'BOTTOM' if child.wave.sign<0 else None
                    result['rearmContext']=child.pending_rearm
                    result['confirmedAt']=confirmed[n]['time'] if result['status']=='CONFIRMED' else None
                    result['confirmedDirection']=confirmed[n]['direction'] if result['status']=='CONFIRMED' else None
                    clocks=('15:00',) if period=='day' else tuple(t.strftime('%H:%M') for t in b.ENDPOINTS[int(period[1:])])
                    context=build_display_context(bars[:n],period,bars[n-1].time,result,clocks,check)
                    if result.get('nextBarOutcomes'):
                        context['nextBar']=reference_band(bars[:n],period,bars[n-1].time,result['nextBarOutcomes']['endpoint'],1,clocks,check)
                    result['display']=make_display(result,period,bars[n-1].time,'REPLAY',context,check)
                    check();ms=(time.perf_counter()-started)*1000
                    assert before==child.snapshot()
                    size=len(json.dumps(result,ensure_ascii=False,separators=(',',':')).encode())+2048
                    assert size<=32768,('response estimate',period,n,size)
                    original=next((v['result'] for v in baseline if v['rows']==n),None)
                    if gate==1. and original and original['reasonCode']=='CALIBRATION_FAILED':assert result['reasonCode']=='CALIBRATION_FAILED'
                    results.append(dict(rows=n,through=bars[n-1].time,milliseconds=ms,estimatedResponseBytes=size,result=result))
                save(f'forecasts_{period}_{gate}.json',results)
                gate_summaries[str(gate)]=dict(rows=len(bars),rescues=len(calc.rescues),forecasts=len(results),maxMs=max(v['milliseconds'] for v in results),maxEstimatedBytes=max(v['estimatedResponseBytes'] for v in results),calibrationProtected=sum(v['result']['reasonCode']=='CALIBRATION_FAILED' for v in results))
                print(period,gate,json.dumps(gate_summaries[str(gate)]),flush=True)
            summary['periods'][period]=gate_summaries
            save('summary.json',summary)
        summary['passed']=True
    except Exception as exc:
        summary.update(passed=False,error=dict(type=type(exc).__name__,message=str(exc)))
        raise
    finally:
        summary['protectedUnchanged']=all(sha(root/p)==h for p,h in protected.items())
        save('summary.json',summary)
        assert summary['protectedUnchanged']


if __name__=='__main__':main()
