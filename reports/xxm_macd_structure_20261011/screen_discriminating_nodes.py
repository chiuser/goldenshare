"""Freeze a source-aware discrimination screen; never add software labels.

Only saved CSV closes are used. Extended series are research derivations, not
new DG exports or software histories. Existing candidates and reports stay fixed.
The parameter-cell screen is conditional on the previously allowed interval.
"""
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from active_reference_candidate import replay as active
from audit_threshold_constraints import last_passing_threshold
from audit_turn_filters import labels50
from reference_retirement_candidate import replay as retirement
from replay import read_rows
from turn_filter_candidate import replay as turn
from validate_stage2 import CASES

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'discrimination_screen_20261012'
KEYS = ('event', 'state', 'event_route', 'event_ref_start')
GATES = (.75, 1., 1.2)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signature(rows):
    return [tuple(r[k] for k in KEYS) for r in rows]


def extend(seed_name, close_name, endpoints):
    seed, source = read_rows(seed_name), read_rows(close_name)
    selected = [r for r in source if r['time'][11:16] in endpoints]
    source_map = {r['time']: r for r in selected}
    overlaps = [(r, source_map[r['time']]) for r in seed if r['time'] in source_map]
    assert overlaps and all(a['close'] == b['close'] for a, b in overlaps)
    # Solve F0-S0=D0 and the next 12/26 EMA step; H0 fixes DEA0.
    a, b = seed[:2]
    af, ass = 2 / 13, 2 / 27
    slow = (b['dif'] - (1-af)*a['dif'] - (af-ass)*b['close']) / (ass-af)
    fast, dea = slow+a['dif'], a['dif']-a['hist']/2
    initial = dict(fast=fast, slow=slow, dea=dea)
    rows = [dict(a)]
    tail = [r for r in selected if r['time'] > seed[-1]['time']]
    for r in seed[1:] + tail:
        fast = af*r['close'] + (1-af)*fast
        slow = ass*r['close'] + (1-ass)*slow
        dif = fast-slow
        dea = .2*dif + .8*dea
        rows.append(dict(time=r['time'], close=r['close'], dif=dif, hist=2*(dif-dea)))
    assert [r['time'] for r in rows] == sorted({r['time'] for r in rows})
    # Every included date has all chosen endpoints; no assumed trading calendar.
    dates = {}
    for r in rows:
        dates.setdefault(r['time'][:10], set()).add(r['time'][11:16])
    assert all(times == set(endpoints) for times in dates.values())
    return rows, dict(seed=seed_name, close_source=close_name, endpoints=endpoints,
                     seed_sha256=sha(ROOT/'inputs'/seed_name),
                     close_source_sha256=sha(ROOT/'inputs'/close_name),
                     recovered_initial_state=initial, close_overlap_bars=len(overlaps),
                     new_derived_bars=len(tail), rows=len(rows),
                     start=rows[0]['time'], end=rows[-1]['time'],
                     source_status='DERIVED_FROM_SAVED_CLOSES_NOT_NEW_SOFTWARE_OBSERVATIONS')


def write_csv(path, rows):
    with path.open('w', newline='') as h:
        w = csv.DictWriter(h, fieldnames=('time', 'close', 'dif', 'hist'))
        w.writeheader(); w.writerows(rows)


def compare(a, b):
    return [dict(time=x['time'], baseline={k:x[k] for k in KEYS},
                 alternative={k:y[k] for k in KEYS}, software_observation='NOT_OBSERVED')
            for x, y in zip(a, b) if tuple(x[k] for k in KEYS) != tuple(y[k] for k in KEYS)]


def main():
    OUT.mkdir(exist_ok=True)
    protected = {str(p.relative_to(ROOT)):sha(p) for p in ROOT.rglob('*')
                 if p.is_file() and OUT not in p.parents and p.name != Path(__file__).name
                 and '__pycache__' not in p.parts}
    allowed = json.loads((ROOT/'threshold_constraint_audit.json').read_text())['ranges']['locked']['exact_all']
    assert len(allowed) == 1
    lo, hi = allowed[0]['lower_exclusive'], allowed[0]['upper_inclusive']
    series, provenance = {}, {}
    for freq, seed, source, ends in (
        (120, '120_20250401_20251111.csv', '60_20250603_20261009.csv', ['11:30','15:00']),
        (90, '90_20250603_20260113.csv', '30_20250603_20261009.csv', ['11:00','14:00','15:00'])):
        series[freq], provenance[freq] = extend(seed, source, ends)
        path = OUT/f'derived_{freq}.csv'; write_csv(path, series[freq])
        provenance[freq]['derived_file_sha256'] = sha(path)
    # Overlap equality is DG-level numerical reproducibility, not software alignment.
    overlap_checks = []
    for freq, rows in series.items():
        idx = {r['time']:r for r in rows}
        for path in sorted((ROOT/'inputs').glob(f'{freq}_*.csv')):
            pairs = [(r,idx[r['time']]) for r in read_rows(path.name) if r['time'] in idx]
            errors = {k:max(abs(a[k]-b[k]) for a,b in pairs) for k in ('close','dif','hist')}
            assert errors['close'] == 0 and max(errors.values()) < 1e-8
            overlap_checks.append(dict(input=path.name, sha256=sha(path), bars=len(pairs), max_errors=errors))
    # All possible raw-DIF bases are past row values: previous bar or state anchor.
    # Every float decision critical point in the interval is thus in this superset.
    # Endpoints are inclusive on the lower cell (>= predicate); no uniform grid.
    rows = series[120]
    cuts = {hi}
    for i, basis in enumerate(rows):
        if not basis['dif']: continue
        for current in rows[i+1:]:
            mag = abs(current['dif']-basis['dif'])
            q = 100*mag/abs(basis['dif'])
            if lo < q < hi:
                cuts.add(last_passing_threshold(basis['dif'],mag))
    points = sorted(q for q in cuts if lo < q <= hi)
    labels = labels50() + [dict(case='mins90', **r) for r in
                          json.loads((ROOT/'holdout_20260105_pair.json').read_text())['labels']]
    assert len(labels) == 52
    calibration = {case:read_rows(name) for case,name in CASES.items()}
    physical120 = {l['time']:l for l in labels if '120' in l['case']}
    frozen = []; cells = []; checks = 0; prior = lo
    for n, right in enumerate(points):
        midpoint = prior + (right-prior)/2
        outputs = {}
        for gate in (midpoint,right):
            outputs[gate] = {mode:turn(rows,gate,turn_measure=mode,reference_policy='strongest_eligible')
                             for mode in ('single_bar','state_extreme')}
            for policy in ('locked','both_before','dull_before','both_after'):
                result = active(rows,gate,active_policy=policy,reference_policy='strongest_eligible')
                assert signature(result) == signature(outputs[gate]['single_bar'])
                checks += 1
            for policy in ('none','raw_dif_cross','dominated'):
                result = retirement(rows,gate,retirement_policy=policy,reference_policy='strongest_eligible')
                assert signature(result) == signature(outputs[gate]['single_bar'])
                checks += 1
        for mode in ('single_bar','state_extreme'):
            assert signature(outputs[midpoint][mode]) == signature(outputs[right][mode])
            checks += 1
        differences = compare(outputs[right]['single_bar'],outputs[right]['state_extreme'])
        survives = {}
        for mode in ('single_bar','state_extreme'):
            outs = {case:{r['time']:r for r in turn(data,right,turn_measure=mode,
                    reference_policy='strongest_eligible')} for case,data in calibration.items()}
            failures = [dict(**l,actual=outs[l['case']][l['time']]['event'])
                        for l in labels if outs[l['case']][l['time']]['event'] != l['expected']]
            survives[mode] = dict(failures=failures, matched=len(labels)-len(failures))
        eligible = all(not r['failures'] for r in survives.values())
        for d in differences:
            d.update(cell_lower_exclusive=prior,cell_upper_inclusive=right,
                     candidate_pair_survives_old_labels=eligible,
                     already_labelled=d['time'] in physical120)
            frozen.append(d)
        cells.append(dict(lower_exclusive=prior,upper_inclusive=right,
                          calibration=survives,differences=differences))
        prior = right
    auxiliary = []
    prefix_checks = 0
    for gate in GATES:
        for freq in (90,120):
            data = series[freq]
            a = turn(data,gate,reference_policy='strongest_eligible')
            b = turn(data,gate,reference_policy='strongest_eligible',turn_measure='state_extreme')
            auxiliary.append(dict(freq=freq,gate=gate,comparison='single_vs_cumulative',differences=compare(a,b)))
            for policy in ('both_before','dull_before','both_after'):
                base = active(data,gate,reference_policy='strongest_eligible')
                alt = active(data,gate,reference_policy='strongest_eligible',active_policy=policy)
                diffs = compare(base,alt)
                for d in diffs:
                    i = next(i for i,r in enumerate(data) if r['time']==d['time'])
                    assert active(data[:i+1],gate,reference_policy='strongest_eligible',active_policy=policy)[-1] == alt[i]
                    prefix_checks += 1
                auxiliary.append(dict(freq=freq,gate=gate,comparison=f'locked_vs_{policy}',differences=diffs))
    # Store existing unavailable requests rather than reissue them after screening.
    constraints = [dict(date='2025-07-11',freq=60,status='UNAVAILABLE_DO_NOT_REPEAT'),
                   dict(date='2025-07-23',freq=60,status='PAUSED'),
                   dict(date='2025-12-16',freq=90,status='PAUSED_SOURCE_AND_NUMERIC_ALIGNMENT'),
                   dict(date='2026-06-05',freq=30,status='WITHDRAWN_TRANSCRIPT_HAS_NO_SUCH_PERIOD')]
    assert all(sha(ROOT/name)==digest for name,digest in protected.items())
    result = dict(as_of=datetime.now(timezone.utc).isoformat(),
                  purpose='Frozen unobserved predictions and source availability; no new software labels',
                  candidate_sha256={name:sha(ROOT/name) for name in
                      ('turn_filter_candidate.py','active_reference_candidate.py','reference_retirement_candidate.py')},
                  script_sha256=sha(Path(__file__)),provenance=provenance,overlap_checks=overlap_checks,
                  parameter_domain=allowed[0],parameter_cells=len(cells),cells=cells,
                  frozen_120_disagreements=frozen,auxiliary_screen=auxiliary,
                  validation=dict(cell_and_policy_checks=checks,causal_prefix_checks=prefix_checks,
                                  calibration_labels_unchanged=52,new_software_labels=0),
                  source_constraints=constraints,new_screenshot_requests=[],
                  protected_files=protected,protected_files_unchanged=True,
                  limitations=['120 parameter-cell coverage applies only to raw single-bar/state-extreme candidates within the saved conditional interval.',
                               'The 90-minute auxiliary comparison tests three thresholds only; its software numerical mismatch is unresolved.',
                               'Extended CSVs are offline EMA derivations with recovered DG seeds, not software truth or new independent evidence.',
                               'Absence of disagreement in a bounded history is not global equivalence or unique software identification.',
                               'No new transcript/frame retrieval was attempted; vidIQ exhausted quota and prior missing-period feedback were respected.'])
    (OUT/'screen.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(provenance=provenance,overlap_checks=overlap_checks,
                         cells=len(cells),frozen_120_differences=len(frozen),
                         auxiliary_differences=[dict(freq=d['freq'],gate=d['gate'],comparison=d['comparison'],
                                                    times=[x['time'] for x in d['differences']])
                                                for d in auxiliary if d['differences']],
                         validation=result['validation'],protected_files=len(protected)),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
