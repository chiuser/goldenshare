"""Saved-evidence audit of causal boundary and first-dull bar requirements.

Five global candidates and three dated local diagnostics, each at three gates.
Local exceptions isolate a cause and are never proposed as an indicator rule.
Previously viewed screenshots/captions are retrospective evidence, not blind
validation; unlabelled event differences are not verified software signals.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from audit_turn_filters import labels50
from replay import read_rows
from replay_color_flip import replay as baseline
from validate_stage2 import CASES
from wave_boundary_candidate import replay

ROOT = Path(__file__).resolve().parent
GATES = (.75, 1, 1.2)
GLOBAL = {
    'raw_cut1_min2': {},
    'raw_cut2_min2': dict(cut_bars=2),
    'confirmed_cut2_min2': dict(cut_bars=2, flip_timing='confirmed'),
    'raw_cut1_min1': dict(min_bars=1),
    'raw_cut1_min3': dict(min_bars=3),
}
LOCAL = {
    'ignore_daily_20251105': ('daily_2025', '2025-11-05'),
    'ignore_120_20251022_pm': ('aug_120', '2025-10-22 15:00:00'),
    'ignore_120_20251023_am': ('aug_120', '2025-10-23 11:30:00'),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(rows, mode, gate, case='', diagnostics=False):
    args = GLOBAL.get(mode, {})
    if mode in LOCAL and case == LOCAL[mode][0]:
        args = dict(cut_bars=2, defer_at={LOCAL[mode][1]})
    return replay(rows, gate, diagnostics=diagnostics, **args)


def sign_runs(rows):
    result = []
    for i, row in enumerate(rows):
        sign = (row['hist'] > 0) - (row['hist'] < 0)
        if not result or result[-1]['sign'] != sign:
            result.append(dict(sign=sign, first=i, last=i))
        else:
            result[-1]['last'] = i
    return result


def main():
    own = {'wave_boundary_candidate.py', 'audit_wave_boundaries.py', 'wave_boundary_audit.json'}
    protected = {str(p.relative_to(ROOT)): sha(p) for p in ROOT.rglob('*')
                 if p.is_file() and p.suffix.lower() in {'.py', '.json', '.csv', '.png'}
                 and p.name not in own and '__pycache__' not in p.parts}
    assert sha(ROOT/'replay_color_flip.py') == 'f472817f85fa8b152501ad659a4afcefe8f903f5b19f8db6bb62403c6ce301ba'
    labels = labels50()
    data = {case: read_rows(name) for case, name in CASES.items()}
    summaries, checks, outputs = [], [], {}
    for mode in (*GLOBAL, *LOCAL):
        for gate in GATES:
            outputs[mode, gate] = {case: {r['time']: r for r in run(rows, mode, gate, case, True)}
                                   for case, rows in data.items()}
            failures = []
            for label in labels:
                row = outputs[mode, gate][label['case']][label['time']]
                prefix = [r for r in data[label['case']] if r['time'] <= label['time']]
                assert run(prefix, mode, gate, label['case'], True)[-1] == row
                check = dict(**label, mode=mode, gate=gate, actual=row['event'],
                             matched=label['expected'] == row['event'], prefix_matched=True,
                             prediction=row)
                checks.append(check)
                if not check['matched']:
                    failures.append(check)
            summaries.append(dict(mode=mode, gate=gate, points=50, new_points=0,
                direct_failures=sum(r['confidence']=='direct' for r in failures),
                mapped_failures=sum(r['confidence']=='mapped' for r in failures), failures=failures))
    parity_runs, parity_rows = 0, 0
    scope, census, causal_pending_checks = [], [], 0
    for path in sorted((ROOT/'inputs').glob('*.csv')):
        rows = read_rows(path.name)
        runs = sign_runs(rows)
        isolated = [r for r in runs[1:-1] if r['sign'] and r['first']==r['last']]
        census.append(dict(input=path.name, rows=len(rows), isolated_nonzero_runs=[
            dict(row=rows[r['first']], before=rows[r['first']-1], after=rows[r['first']+1])
            for r in isolated], note='Overlapping extracts are not independent episodes.'))
        for gate in GATES:
            original = baseline(rows, gate, reference_policy='strongest_eligible')
            assert run(rows, 'raw_cut1_min2', gate) == original
            parity_runs += 1
            parity_rows += len(rows)
            for mode in GLOBAL:
                alternative = run(rows, mode, gate)
                event_diffs = [dict(time=a['time'], baseline=a, alternative=b)
                    for a,b in zip(original, alternative)
                    if (a['event'], a['event_ref_start']) != (b['event'], b['event_ref_start'])]
                scope.append(dict(input=path.name, mode=mode, gate=gate,
                                  event_differences=len(event_diffs),
                                  differences=event_diffs if gate==1 else [],
                                  note='No unlabelled difference is a software observation.'))
                # Target causality at the uncertain first/return bars, rather
                # than just at later labelled endpoints.
                for run_info in isolated:
                    for i in (run_info['first'], run_info['first']+1):
                        assert run(rows[:i+1], mode, gate)[-1] == alternative[i]
                        causal_pending_checks += 1
    local_records = []
    for mode,(case,time) in LOCAL.items():
        rows = data[case]
        for gate in GATES:
            base = outputs['raw_cut1_min2',gate][case]
            local = outputs[mode,gate][case]
            assert all(base[r['time']]==local[r['time']] for r in rows if r['time']<time)
            window_end = '2025-11-12' if case=='daily_2025' else '2025-10-28'
            local_records.append(dict(mode=mode, case=case, gate=gate,
                sole_deferred_start=time, before_target_exact_match=True,
                window=[dict(baseline=base[r['time']], alternative=local[r['time']])
                        for r in rows if time<=r['time']<=window_end],
                interpretation='Dated local causal diagnostic; not a production rule.'))
    # Logical state-machine paths, not a claim of EMA-consistent market data.
    def synthetic(values):
        return [dict(time=f't{i:02d}', close=c, dif=d, hist=h)
                for i,(c,d,h) in enumerate(values)]
    prefix = [(100,10,1),(101,12,1),(95,10,-1),(94,10.1,-1),(102,9,1),(103,9.5,1)]
    illustrations = []
    for ending in ([(104,9.49,-1),(105,9.6,1)], [(104,9.49,-1),(104,9.48,-1)]):
        rows=synthetic(prefix+ending)
        mirror=[dict(time=r['time'], close=200-r['close'],dif=-r['dif'],hist=-r['hist']) for r in rows]
        for mode in ('raw_cut1_min2','raw_cut2_min2','confirmed_cut2_min2'):
            top,bottom=run(rows,mode,1),run(mirror,mode,1)
            assert [(r['event'],r['state'],r['wave_count']) for r in top]==[
                (r['event'],r['state'],r['wave_count']) for r in bottom]
            for rr,full in ((rows,top),(mirror,bottom)):
                for i,row in enumerate(full):
                    assert run(rr[:i+1],mode,1)[-1]==row
            illustrations.append(dict(mode=mode, inputs=rows, outputs=top,
                                       mirrored_match=True, prefix_checks=2*len(rows)))
        raw=run(rows,'raw_cut2_min2',1)
        confirmed=run(rows,'confirmed_cut2_min2',1)
        assert raw[6]['event']=='STRUCTURE' and confirmed[6]['event']=='NONE'
        if ending[-1][2]<0:
            assert confirmed[-1]['event']=='STRUCTURE' and confirmed[-1]['wave_count']==2
        else:
            assert raw[-1]['wave_count']==3 and raw[-1]['event']=='DULL'
    assert all(sha(ROOT/name)==digest for name,digest in protected.items())
    result=dict(as_of=datetime.now(timezone.utc).isoformat(),
        scope='Retrospective boundary audit; no new software observations and no blind score.',
        fixed_rules=dict(reference_policy='strongest_eligible',max_refs=2, raw_dif_cancel=True,
                         single_bar_turn=True,zero_histogram='always ends wave'),
        global_hypotheses=GLOBAL, local_diagnostics={k:dict(case=v[0],deferred_at=v[1]) for k,v in LOCAL.items()},
        labels=dict(total=50,direct=19,mapped=31,newly_added=0), checks=checks,summaries=summaries,
        baseline_parity=dict(runs=parity_runs,rows=parity_rows,exact_match=True),
        label_prefix_checks=len(checks),pending_prefix_checks=causal_pending_checks,
        scope_screen=scope,single_bar_census=census,local_records=local_records,
        synthetic_illustrations=illustrations,protected_files=protected,protected_files_unchanged=True,
        candidate_sha256=sha(ROOT/'wave_boundary_candidate.py'),script_sha256=sha(Path(__file__)))
    (ROOT/'wave_boundary_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(parity=result['baseline_parity'], label_prefix_checks=len(checks),
        pending_prefix_checks=causal_pending_checks,protected_files=len(protected),
        summaries=[{k:s[k] for k in ('mode','gate','direct_failures','mapped_failures')} for s in summaries]),
        ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
