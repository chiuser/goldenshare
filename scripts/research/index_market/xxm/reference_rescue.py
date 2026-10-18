"""R1 offline bottom-DULL rescue before old-reference cancellation.

Never imported or registered by product code. Every other transition uses the
unchanged product class. This is an explanatory candidate, not software truth.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

from .acceptance import load_source, sha
from .cancellation_restart_audit import ROOT, SOURCE, BASELINE, PERIODS
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


@dataclass(frozen=True)
class RescuePolicy:
    research_version: str = 'r1-bottom-dull-prebreak'
    trigger: str = 'same_negative_segment_dull_old_dif_strict_break'
    selection: str = 'original_pool_strongest_eligible_segment_extremes'
    other_transitions: str = 'unchanged_product_step'
    product_registration: bool = False

    @property
    def policy_hash(self):
        return hashlib.sha256(json.dumps(asdict(self),sort_keys=True).encode()).hexdigest()


R1_POLICY = RescuePolicy()


def rescue_reference(calc, bar):
    """Select only when the old reference would break; never mutate the input.

    Eligibility/sorting are the product's existing first-entry conditions from
    calculator.step:90-98, evaluated on the incoming completed bar's extrema.
    """
    wave, ref = calc.wave, calc.reference
    if (calc.state != 'DULL' or wave is None or wave.sign != -1 or bar.hist >= 0
            or ref is None or calc.pending_rearm is not None):
        return None
    dif = min(wave.dif,bar.dif)
    if dif >= ref.dif:
        return None
    pool = list(reversed(calc.history[-1]))
    price = min(wave.price,bar.close)
    if wave.count+1 < calc.spec.min_bars or not pool or price >= pool[0].price:
        return None
    pool.sort(key=lambda candidate:-candidate.dif,reverse=True)
    for candidate in pool:
        if price < candidate.price and dif > candidate.dif:
            return deepcopy(candidate)
    return None


class BottomDullRescueCalculator(XxmCalculator):
    """Research-only narrow pre-step; no copied product state machine."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rescues = []  # diagnostic log only; never read by detection

    def step(self, bar):
        # Reject before selecting/mutating; preserve original input semantics.
        bar.validate(self.period)
        if self.previous is not None and bar.time <= self.previous.time:
            raise ValueError('Duplicate or unordered XXM input')
        selected = rescue_reference(self,bar)
        old = self.reference.reference() if selected is not None else None
        if selected is not None:
            self.reference = selected
        step = super().step(bar)
        if selected is not None:
            self.rescues.append(dict(time=bar.time,bar=asdict(bar),oldReference=old,
                newReference=selected.reference(),wave=asdict(self.wave),
                pool=[w.reference() for w in self.history[-1]],events=list(step.events),state=self.state))
        return step


def new(period, candidate=False):
    cls = BottomDullRescueCalculator if candidate else XxmCalculator
    return cls(period=period,source_identity='reference-rescue:'+period,spec=MAIN_SPEC)


def child_of(calc):
    child = new(calc.period,isinstance(calc,BottomDullRescueCalculator))
    child.restore(calc.snapshot())
    return child


def collect(period,bars):
    base, candidate = new(period),new(period,True)
    base_events, candidate_events, base_steps, candidate_steps = [],[],[],[]
    base_top, candidate_top, base_bottom, candidate_bottom = {},{},{},{}
    fixed={0,1,25,1000,len(bars)//2,len(bars)-1,len(bars)}
    snapshots={0:candidate.snapshot()}
    checkpoints={}
    for n,bar in enumerate(bars,1):
        selected=rescue_reference(candidate,bar)
        if selected is not None:
            snapshots[n-1]=candidate.snapshot()
        bs,cs=base.step(bar),candidate.step(bar)
        base_steps.append(bs);candidate_steps.append(cs)
        base_events.extend(bs.events);candidate_events.extend(cs.events)
        base_top.update({h['id']:h for h in bs.histories});candidate_top.update({h['id']:h for h in cs.histories})
        base_bottom.update({h['id']:h for h in bs.bottom_histories});candidate_bottom.update({h['id']:h for h in cs.bottom_histories})
        if base.history != candidate.history or base.wave != candidate.wave:
            raise ValueError('R1 changed original segmentation/reference pool')
        if n in fixed or selected is not None:
            snapshots[n]=candidate.snapshot()
        if (period=='m90' and bar.time in ('2025-12-15T15:00:00+08:00','2025-12-16T15:00:00+08:00')
                or period=='m120' and bar.time in ('2026-07-10T15:00:00+08:00','2026-07-13T15:00:00+08:00')
                or period=='m90' and bar.time=='2026-07-13T15:00:00+08:00'):
            checkpoints[bar.time]=dict(base=base.snapshot(),candidate=candidate.snapshot())
    if base_events != json.loads((BASELINE/f'events_{period}.json').read_text())['events']:
        raise ValueError('Original product differs from A1 ledger: '+period)
    if [e for e in base_events if e['direction']=='TOP'] != [e for e in candidate_events if e['direction']=='TOP'] or base_top!=candidate_top:
        raise ValueError('R1 changed TOP events/history')
    changes=[]
    rescue_times=[r['time'] for r in candidate.rescues]
    for bar,bs,cs in zip(bars,base_steps,candidate_steps,strict=True):
        if bs==cs:continue
        at=bisect_right(rescue_times,bar.time)-1
        if at<0:raise ValueError('Difference before first rescue')
        changes.append(dict(time=bar.time,causeRescueAt=rescue_times[at],bar=asdict(bar),
            baseEvents=list(bs.events),candidateEvents=list(cs.events),
            pointChanged=bs.point!=cs.point,basePoint=bs.point,candidatePoint=cs.point,
            baseBottomHistories=list(bs.bottom_histories),candidateBottomHistories=list(cs.bottom_histories),
            baseRearms=list(bs.rearm_records),candidateRearms=list(cs.rearm_records)))
    restored=[]
    for cut,snapshot in sorted(snapshots.items()):
        prefix=new(period,True)
        if [prefix.step(b) for b in bars[:cut]]!=candidate_steps[:cut] or prefix.snapshot()!=snapshot:
            raise ValueError('Candidate prefix is not causal')
        resumed=new(period,True);resumed.restore(snapshot)
        if [resumed.step(b) for b in bars[cut:cut+250]]!=candidate_steps[cut:cut+250]:
            raise ValueError('Candidate restore differs')
        restored.append(dict(rows=cut,through=bars[cut-1].time if cut else None,suffixBars=min(250,len(bars)-cut)))
    before={e['id']:e for e in base_events};after={e['id']:e for e in candidate_events}
    removed=[e for key,e in before.items() if key not in after]
    added=[e for key,e in after.items() if key not in before]
    modified=[dict(base=e,candidate=after[key]) for key,e in before.items() if key in after and after[key]!=e]
    summary=dict(rows=len(bars),baselineEventsEqual=True,poolAndWaveUnchanged=True,topUnchanged=True,
        rescues=len(candidate.rescues),changedEndpoints=len(changes),eventChangedEndpoints=sum(c['baseEvents']!=c['candidateEvents'] for c in changes),
        removed=dict(Counter(e['type'] for e in removed)),added=dict(Counter(e['type'] for e in added)),modifiedSameId=len(modified),
        prefixRestoreCuts=len(restored),baseBottomHistories=len(base_bottom),candidateBottomHistories=len(candidate_bottom))
    return dict(summary=summary,rescues=candidate.rescues,changes=changes,events=candidate_events,
        removed=removed,added=added,modified=modified,restored=restored,checkpoints=checkpoints,
        bottomHistories=list(candidate_bottom.values()),topHistories=list(candidate_top.values()))


def evidence_checks(results,sources):
    checks=[]
    def require(period,date,kind,route=None):
        found=[e for e in results[period]['events'] if e['time'][:10]==date and e['direction']=='BOTTOM'
            and e['type']==kind and (route is None or e['route']==route)]
        if len(found)!=1:raise ValueError(f'Software protection conflict: {period} {date} {kind}')
        checks.append(dict(period=period,date=date,type=kind,route=route,modelTime=found[0]['time'],
            exactSoftwareTimeClaimed=False))
    for date in ('2024-07-23','2024-08-05','2024-08-22'):require('day',date,'RESEARCH_HISTORICAL_WITHDRAWAL')
    for date in ('2024-08-05','2024-08-14'):require('m120',date,'RESEARCH_HISTORICAL_WITHDRAWAL')
    for date,kind,route in [('2024-08-14','DULL','dif_return'),('2024-08-15','STRUCTURE',None),
            ('2026-07-15','CANCEL',None),('2026-07-17','DULL','activation'),('2026-07-20','CANCEL',None)]:
        require('day',date,kind,route)
    case=[e for e in results['m90']['events'] if '2025-12-11'<=e['time'][:10]<='2025-12-16' and e['direction']=='BOTTOM']
    if [e['type'] for e in case]!=['DULL','STRUCTURE','STRUCTURE_DISAPPEARED','DULL']:
        raise ValueError('R1 fails the observed four-label chain')
    if case[-2]['time'][:10]!='2025-12-15' or case[-1]['time'][:10]!='2025-12-15':
        raise ValueError('R1 changed the confirmed 12/15 disappearance/rearm date')
    simulations=[]
    for period,through,stamp,price,expected,route,software in [
        ('m120','2026-07-10T15:00:00+08:00','2026-07-13T11:30:00+08:00',3959.16,'DULL','reactivation',True),
        ('m120','2026-07-10T15:00:00+08:00','2026-07-13T11:30:00+08:00',3960.,'NONE',None,False),
        ('m120','2026-07-13T15:00:00+08:00','2026-07-14T11:30:00+08:00',3892.79,'NONE','dif_break',True),
        ('m90','2026-07-13T15:00:00+08:00','2026-07-14T11:00:00+08:00',3944.79,'DULL',None,True)]:
        calc=new(period,True);calc.restore(results[period]['checkpoints'][through]['candidate'])
        before=calc.snapshot();child=child_of(calc)
        prefix=tuple(b for b in sources[period] if b.time<=through)
        bar,_=recover_projection(prefix,period,lambda:None).project(price,stamp,period)
        step=child.step(bar)
        if child.state!=expected or (not any(e['route']==route for e in step.events) if route else bool(step.events)):
            raise ValueError('Prior simulation protection conflict')
        if calc.snapshot()!=before:raise ValueError('Hypothetical polluted parent')
        simulations.append(dict(period=period,through=through,bar=asdict(bar),state=child.state,events=list(step.events),softwareObservation=software))
    return dict(dateProtections=checks,newSoftwareChain=case,simulations=simulations)


def price_probe(results,bars):
    through='2025-12-15T15:00:00+08:00';stamp='2025-12-16T11:00:00+08:00'
    prefix=tuple(b for b in bars if b.time<=through)
    projection=recover_projection(prefix,'m90',lambda:None)
    saved=results['m90']['checkpoints'][through]
    old=saved['base']['reference'];other=min(saved['base']['history']['-1'],key=lambda r:r['dif'])
    slope=2/13-2/27;bias=projection.e12*11/13-projection.e26*25/27
    roots=dict(oldDif=(old['dif']-bias)/slope,otherDif=(other['dif']-bias)/slope,otherPrice=other['price'])
    ordered=sorted(roots.values());prices=[ordered[0]-1,*[(a+b)/2 for a,b in zip(ordered,ordered[1:])],ordered[-1]+1,3821.73,3826.3425]
    probes=[]
    for price in prices:
        bar,_=projection.project(price,stamp,'m90');row=dict(price=price,bar=asdict(bar))
        for label,candidate in [('base',False),('candidate',True)]:
            calc=new('m90',candidate);calc.restore(saved[label]);parent=calc.snapshot();child=child_of(calc);step=child.step(bar)
            if calc.snapshot()!=parent:raise ValueError('Price probe polluted parent')
            row[label]=dict(state=child.state,events=list(step.events),reference=child.reference.reference() if child.reference else None,
                rescues=child.rescues if candidate else [])
        probes.append(row)
    return dict(through=through,target=stamp,projection=asdict(projection),roots=roots,probes=probes,
        fullForecastSolverRun=False,softwareExactBoundariesKnown=False)


def run(output: Path):
    output=output.resolve()
    if not output.is_relative_to((ROOT/'reports').resolve()) or not output.name.startswith('run_'):
        raise ValueError('Output must be a new reports/.../run_* directory')
    output.mkdir(exist_ok=False)
    protected=dict(json.loads((ROOT/'reports/xxm_software_case_20251215_m90_20261016/case.json').read_text())['protectedSha256'])
    for path in [Path(__file__),ROOT/'reports/xxm_software_case_20251215_m90_20261016/case.json',
        ROOT/'reports/xxm_software_case_20251215_m90_20261016/20251215_m90_original.png',
        ROOT/'reports/xxm_software_case_20251215_m90_20261016/user_observation.txt',
        ROOT/'reports/xxm_cancellation_restart_20261016_01/run_03/episodes_day.json',
        ROOT/'reports/xxm_reference_rescue_20261017_01/protocol.md']:
        protected[str(path.relative_to(ROOT))]=sha(path)
    if not all(sha(ROOT/k)==v for k,v in protected.items()):raise ValueError('Protected input changed')
    sources={p:load_source(SOURCE,p) for p in PERIODS};results={}
    for p in PERIODS:
        results[p]=collect(p,sources[p])
        with (output/f'result_{p}.json').open('x') as f:json.dump(results[p],f,ensure_ascii=False,indent=2);f.write('\n')
        print(p,json.dumps(results[p]['summary']),flush=True)
    evidence=evidence_checks(results,sources);probe=price_probe(results,sources['m90'])
    for name,value in [('evidence',evidence),('price_probe',probe)]:
        with (output/f'{name}.json').open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
    if not all(sha(ROOT/k)==v for k,v in protected.items()):raise ValueError('Protected source/product changed')
    summary=dict(policy=asdict(R1_POLICY),policyHash=R1_POLICY.policy_hash,productionSpec=asdict(MAIN_SPEC),
        specHash=MAIN_SPEC.spec_hash,periods={p:r['summary'] for p,r in results.items()},protectedSha256=protected,
        softwareUniqueFormulaProven=False,productModified=False,formalBudgetTested=False,fullForecastSolverTested=False)
    with (output/'summary.json').open('x') as f:json.dump(summary,f,ensure_ascii=False,indent=2);f.write('\n')
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)


if __name__=='__main__':main()
