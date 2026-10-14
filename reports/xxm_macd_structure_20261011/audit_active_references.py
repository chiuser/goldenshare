"""Audit active-reference locking without changing any prior research artifact.

Unlabelled differences are frozen research targets, not software observations.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from active_reference_candidate import replay
from audit_turn_filters import labels50
from replay import read_rows
from replay_color_flip import replay as original
from validate_stage2 import CASES

ROOT = Path(__file__).resolve().parent
GATES = (.75, 1, 1.2)
MODES = ('locked', 'both_before', 'dull_before', 'both_after')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(rows, mode, gate, diagnostics=False):
    return replay(rows, gate, reference_policy='strongest_eligible',
                  active_policy=mode, diagnostics=diagnostics)


def compact(row):
    return {k: row[k] for k in ('time', 'event', 'state', 'event_route',
        'ref_start', 'event_ref_start', 'event_ref_dif', 'event_ref_price', 'dif', 'close')}


def logical_checks():
    seed = [(130,18,1),(150,20,1),(80,5,-1),(100,10,1),
            (101,11,1),(90,7,-1),(110,8,1),(111,9,1)]
    scenarios = {
        'cross_and_new_qualification': seed+[(151,12,1),(152,13,1)],
        'new_qualification_before_cross': seed+[(151,10,1),(152,12,1)],
        'refresh_while_structure': seed+[(112,8.5,1),(151,10,1),(152,12,1)],
        'no_replacement_keeps_cancel': seed+[(120,12,1)],
    }
    inputs = {name:[dict(time=f't{i:02}',close=c,dif=d,hist=h)
                    for i,(c,d,h) in enumerate(triples)] for name,triples in scenarios.items()}
    checks = 0
    for name, rows in inputs.items():
        mirror = [dict(time=r['time'],close=300-r['close'],dif=-r['dif'],hist=-r['hist']) for r in rows]
        results = {}
        for mode in MODES:
            top, bottom = run(rows,mode,1,True), run(mirror,mode,1,True)
            assert [(r['event'],r['state']) for r in top]==[(r['event'],r['state']) for r in bottom]
            for source, output in ((rows,top),(mirror,bottom)):
                for i,row in enumerate(output):
                    assert run(source[:i+1],mode,1,True)[-1]==row
                    checks += 1
            results[mode] = top
        if name=='cross_and_new_qualification':
            assert results['locked'][8]['event']=='CANCEL'
            assert results['both_after'][8]['event']=='CANCEL'
            assert results['both_before'][8]['event']=='NONE'
            assert results['both_before'][8]['reference_refresh']['active_reference']['dif']==20
        elif name=='new_qualification_before_cross':
            assert results['both_after'][8]['reference_refresh']['changed']
            assert results['both_after'][9]['event']=='NONE'
            assert results['locked'][9]['event']=='CANCEL'
        elif name=='refresh_while_structure':
            assert results['locked'][8]['state']=='STRUCTURE'
            assert results['both_before'][9]['reference_refresh']['changed']
            assert not results['dull_before'][9]['reference_refresh']['changed']
        else:
            assert all(output[8]['event']=='CANCEL' for output in results.values())
    return dict(scenarios=inputs,prefix_checks=checks,mirror_checks_passed=True,
                note='Logical state-machine illustrations, not EMA-consistent market samples')


def main():
    names = {'active_reference_candidate.py',Path(__file__).name,'active_reference_audit.json'}
    protected = {str(p.relative_to(ROOT)):sha(p) for p in ROOT.rglob('*')
                 if p.is_file() and p.suffix in {'.py','.csv','.json','.png'}
                 and p.name not in names and '__pycache__' not in p.parts}
    assert sha(ROOT/'replay_color_flip.py')=='f472817f85fa8b152501ad659a4afcefe8f903f5b19f8db6bb62403c6ce301ba'
    labels=labels50()
    assert sum(l['confidence']=='direct' for l in labels)==19
    data={case:read_rows(file) for case,file in CASES.items()}
    summaries,checks,scope=[],[],[]
    for mode in MODES:
        for gate in GATES:
            out={case:{r['time']:r for r in run(rows,mode,gate,True)} for case,rows in data.items()}
            failures=[]
            for label in labels:
                row=out[label['case']][label['time']]
                prefix=[r for r in data[label['case']] if r['time']<=label['time']]
                assert run(prefix,mode,gate,True)[-1]==row
                check=dict(**label,mode=mode,gate=gate,actual=row['event'],
                           matched=row['event']==label['expected'],prefix_matched=True)
                checks.append(check)
                if not check['matched']:failures.append(check)
            summaries.append(dict(mode=mode,gate=gate,direct_failures=sum(l['confidence']=='direct' for l in failures),
                                  mapped_failures=sum(l['confidence']=='mapped' for l in failures),failures=failures))
    parity_runs,parity_rows,switch_prefix_checks=0,0,0
    targets=[]
    for path in sorted((ROOT/'inputs').glob('*.csv')):
        rows=read_rows(path.name)
        for gate in GATES:
            base=run(rows,'locked',gate,True)
            assert run(rows,'locked',gate)==original(rows,gate,reference_policy='strongest_eligible')
            parity_runs+=1;parity_rows+=len(rows)
            for mode in MODES[1:]:
                alt=run(rows,mode,gate,True)
                changes=[]; switches=[]
                for i,(a,b) in enumerate(zip(base,alt)):
                    changed=(a['event'],a['state'],a['event_route'],a['event_ref_start'])!=(b['event'],b['state'],b['event_route'],b['event_ref_start'])
                    if changed:
                        changes.append(dict(time=a['time'],baseline=compact(a),alternative=compact(b)))
                    if b['reference_refresh']['changed']:
                        switches.append(b)
                        targets.append(dict(input=path.name,gate=gate,mode=mode,time=b['time'],
                            baseline=a,alternative=b,observation='NOT_OBSERVED',
                            alignment='DG 90-minute bin is not yet reconciled with software' if path.name.startswith('90_') else 'software period availability unconfirmed'))
                    if changed or b['reference_refresh']['changed']:
                        assert run(rows[:i+1],mode,gate,True)[-1]==b
                        switch_prefix_checks+=1
                scope.append(dict(input=path.name,gate=gate,mode=mode,rows=len(rows),
                                  changed_bars=changes,switches=switches))
    logical=logical_checks()
    assert all(sha(ROOT/name)==digest for name,digest in protected.items())
    result=dict(as_of=datetime.now(timezone.utc).isoformat(),
        scope_description='Retrospective single-rule comparison, no new software labels',
        fixed_rules=dict(reference_policy='strongest_eligible',max_refs=2,min_bars=2,
                         historical_extrema='whole',current_extrema='whole',turn='single_bar_pct',
                         color_flip='evaluate prior active reference before reset'),
        labels=dict(total=50,direct=19,mapped=31,newly_added=0),modes=MODES,gates=GATES,
        summaries=summaries,checks=checks,causal_label_checks=len(checks),
        parity=dict(runs=parity_runs,rows=parity_rows,exact=True),
        scope=scope,scope_comparisons=len(scope),switch_prefix_checks=switch_prefix_checks,
        frozen_unobserved_targets=targets,logical=logical,
        protected_files=protected,protected_files_unchanged=True,
        candidate_sha256=sha(ROOT/'active_reference_candidate.py'),audit_sha256=sha(Path(__file__)))
    (ROOT/'active_reference_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(summaries=summaries,parity=result['parity'],checks=len(checks),
        scope_comparisons=len(scope),switch_prefix_checks=switch_prefix_checks,
        targets=[{k:t[k] for k in ('input','gate','mode','time')} for t in targets],
        logical_checks=logical['prefix_checks'],protected_files=len(protected)),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
