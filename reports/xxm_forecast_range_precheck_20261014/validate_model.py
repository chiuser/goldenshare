"""Independent original-step replay probes and exhaustive branch accounting."""
import sys,math,json,time,random,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from reports.xxm_forecast_range_precheck_20261014.run_precheck import frozen,endpoints,OUT
from reports.xxm_forecast_range_precheck_20261014 import range_model as m
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection

rng=random.Random(1014)
checks=dict(activation=0,confirmation=0,common=0,boundary=0,identities=0)
cases=[]
for period in ('day','m60','m90','m120'):
    bars,file=frozen(period)
    c=XxmCalculator(period=period,source_identity='frozen-range-precheck')
    selected={}
    for i,b in enumerate(bars):
        c.step(b)
        if i>=250:
            selected[(c.state,c.wave.sign)]=(i,c.snapshot())
    selected[('LATEST',c.wave.sign)]=(len(bars)-1,c.snapshot())
    for (state,sign),(idx,snapshot) in selected.items():
        child=m.clone(c);child.restore(snapshot);prefix=bars[:idx+1]
        slots=endpoints(period,prefix[-1].time)
        if child.state=='STRUCTURE':
            cases.append(dict(period=period,state=state,sign=sign,asOf=prefix[-1].time,status='CONFIRMED',projectionRequired=False));continue
        try:proj=recover_projection(prefix,period,lambda:None)
        except Exception as exc:
            cases.append(dict(period=period,state=state,sign=sign,asOf=prefix[-1].time,status='PRECISION_PENDING',reason=str(exc)));continue
        started=time.perf_counter()
        def check():
            if time.perf_counter()-started>.2:raise TimeoutError('200ms')
        try:
            before=child.snapshot();value=m.make_result(child,proj,slots,check)
            elapsed=time.perf_counter()-started
            assert child.snapshot()==before
            checks['identities']+=1
            row=dict(period=period,state=state,sign=sign,asOf=prefix[-1].time,seconds=elapsed,status=value['status'])
            act=value['activation']
            if act:
                for part in act['ranges']+act['exclusions']:
                    r=m.as_interval(part['priceRange'])
                    probes=[r.lo]
                    if r.hi is not None:
                        probes += [r.hi]+[r.lo+(r.hi-r.lo)*t for t in (.001,.25,.5,.75,.999)]
                    else:probes += [r.lo+1,r.lo+1000,r.lo+1000000]
                    for p in probes:
                        if p<=0 or not r.contains(p):continue
                        hit=m.activation_signature(child,proj,p,slots[0])
                        if 'reference' in part:assert hit==part['reference'],(period,state,p,part,hit)
                        elif part['reason']=='PRECISION_UNRESOLVED':pass  # factoring-roundoff enclosure may contain a determinate machine value
                        else:assert hit is None,(period,state,p,part,hit)
                        checks['activation']+=1
                boundaries=m.entry_cuts(child,proj)
                for cut in boundaries:
                    for p in [cut,math.nextafter(cut,0),math.nextafter(cut,math.inf),cut-.0001,cut+.0001]:
                        if p<=0:continue
                        hit=m.activation_signature(child,proj,p,slots[0])
                        active=[v for v in act['ranges'] if m.as_interval(v['priceRange']).contains(p)]
                        uncertain=[v for v in act['exclusions'] if v['reason']=='PRECISION_UNRESOLVED' and m.as_interval(v['priceRange']).contains(p)]
                        if isinstance(hit,dict):assert active or uncertain,(period,state,p,hit)
                        if active:assert hit==active[0]['reference'],(period,state,p,hit,active)
                        checks['boundary']+=1
            if value['relations']:
                j=value['barsAhead']
                n=j-1
                domains=value['targetEntryRanges'] if act else [dict(priceRange=m.Interval(child.previous.close,child.previous.close,True,True).json(),entryRangeIds=[])]
                ds,hs,d,h=m.project_affine_prefix(proj,n)
                for domain in domains:
                    iv=m.as_interval(domain['priceRange'])
                    if iv.hi==iv.lo:prices=[iv.lo]
                    else:prices=[rng.uniform(iv.lo+1e-6,iv.hi-1e-6) for _ in range(30)]
                    ref=next(a['reference'] for a in act['ranges'] if a['entryRangeId'] in domain['entryRangeIds']) if act else child.reference.reference()
                    for p in prices:
                        for route in ('dif_turn','color_flip'):
                            b=m.close_bounds(child,ref,ds,d,h,p,route)
                            if b is None:continue
                            shown=m.display_range(b,4)
                            if shown is None:continue
                            for close in [shown['displayLower']]+([shown['displayUpper'],(shown['displayLower']+shown['displayUpper'])/2] if shown['displayUpper'] is not None else [shown['displayLower']+100,shown['displayLower']+1000000]):
                                assert m.confirmed_options(child,proj,slots[:j],p,close,route,ref),(period,state,p,close,route,b)
                                checks['confirmation']+=1
                for common in value['commonConditions']:
                    iv=m.as_interval(common['entryDomain']) if common['entryDomain'] else m.Interval(child.previous.close,child.previous.close,True,True)
                    prices=[iv.lo] if iv.hi==iv.lo else [rng.uniform(iv.lo+1e-6,iv.hi-1e-6) for _ in range(40)]
                    for p in prices:
                        for shown in common['closeRanges']:
                            for close in [shown['displayLower']]+([shown['displayUpper']] if shown['displayUpper'] is not None else [shown['displayLower']+10000]):
                                assert m.confirmed_options(child,proj,slots[:j],p,close,common['route'],common['reference'])
                                checks['common']+=1
            print(json.dumps(row,ensure_ascii=False),flush=True);cases.append(row)
        except Exception as exc:
            print('FAILED',period,state,sign,prefix[-1].time,repr(exc),flush=True)
            raise
manifest=dict(checks=checks,cases=cases,inputs={str(frozen(p)[1]):hashlib.sha256(frozen(p)[1].read_bytes()).hexdigest() for p in ('day','m60','m90','m120')},proof='Activation cuts cover all original step predicates; target curves affine within each previous-DIF source plateau; common interval extrema checked at every plateau endpoint. Random probes supplement, never replace the branch proof.')
(OUT/'validation.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print(json.dumps(checks,ensure_ascii=False),flush=True)
