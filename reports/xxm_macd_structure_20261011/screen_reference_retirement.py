"""Screen reference-lifecycle hypotheses against saved evidence only.

No production imports, network, DB/Lake access, or trading. Target selection uses
historical prices; software labels remain unobserved. Freeze target predictions
before retrieving target-day captions. Prior observation points are conditional
calibration checks, not independent or blind accuracy measurements.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from audit_reference_lifecycle import dropped_references
from replay_color_flip import replay as original
from replay import read_rows
from reference_retirement_candidate import replay
from validate_stage2 import CASES, evidence_labels

ROOT = Path(__file__).resolve().parent
GATES = (.75, 1, 1.2)
VARIANTS = {
    'fixed2': {},
    'crossed2': {'retirement_policy': 'raw_dif_cross'},
    'dominated2': {'retirement_policy': 'dominated'},
    'longer2': {'history_min_bars': 2},
    'crossed_all': {'retirement_policy': 'raw_dif_cross', 'max_refs': 10000},
    'dominated_all': {'retirement_policy': 'dominated', 'max_refs': 10000},
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def predictions(rows, gate, variant):
    return replay(rows, gate, reference_policy='strongest_eligible', **VARIANTS[variant])


def all_labels():
    labels = evidence_labels()
    for filename in ('holdout_20250818.json', 'holdout_20250626.json', 'holdout_20251027.json'):
        for label in json.loads((ROOT / filename).read_text())['labels']:
            labels.append(dict(case='aug_120', time=label['time'],
                               expected=label['expected_event'], confidence=label['confidence'],
                               source=filename))
    assert len(labels) == 47
    assert len({(label['case'], label['time']) for label in labels}) == 47
    return labels


def lifecycle_target(rows, time, gate):
    """Causal old-structure monitor; does not claim a software cancellation.

    Tracks an activated reference after confirmation and reset, until raw DIF
    first strictly crosses it. It deliberately has no time/window expiration:
    testing that lifetime assumption is the reason for selecting these targets.
    """
    prefix = [row for row in rows if row['time'] <= time]
    out = predictions(prefix, gate, 'fixed2')
    active = None
    confirmed, crossing, previous = {}, [], None
    for row in out:
        if previous and row['wave_sign'] != previous['wave_sign']:
            active = None
        if row['event'] == 'DULL' and row['event_route'] == 'activation':
            active = dict(reference_start=row['event_ref_start'],
                          reference_dif=row['event_ref_dif'], direction=row['event_direction'],
                          activation_time=row['time'])
        if row['event'] == 'STRUCTURE' and active:
            # Distinct confirmations may use the same reference; group by peak.
            confirmed.setdefault(active['reference_start'], dict(active, confirmation_time=row['time']))
        for key, structure in list(confirmed.items()):
            if structure['direction'] * (row['dif'] - structure['reference_dif']) > 0:
                if row['time'] == time:
                    crossing.append(structure)
                del confirmed[key]
        if row['state'] == 'NONE':
            active = None
        previous = row
    return dict(baseline=out[-1], retained_structure_crosses=crossing,
                software_label='NOT_OBSERVED',
                conditional_prediction='OLD_STRUCTURE_CANCEL' if crossing else 'NONE')


def main():
    # Protect previous research outputs as well as the original candidate/data.
    protected = {}
    for pattern in ('*.py', '*.json', '*.csv', 'inputs/*.csv', 'sources/*'):
        for path in ROOT.glob(pattern):
            if path.name in {Path(__file__).name, 'reference_retirement_candidate.py'}:
                continue
            if path.name.startswith('reference_retirement_'):
                continue
            if path.is_file():
                protected[str(path.relative_to(ROOT))] = sha(path)
    labels = all_labels()
    data = {case: read_rows(filename) for case, filename in CASES.items()}
    assert sha(ROOT / 'replay_color_flip.py') == 'f472817f85fa8b152501ad659a4afcefe8f903f5b19f8db6bb62403c6ce301ba'
    parity_rows, parity_runs = 0, 0
    for filename in sorted(path.name for path in (ROOT / 'inputs').glob('*.csv')):
        rows = read_rows(filename)
        for gate in GATES:
            assert predictions(rows, gate, 'fixed2') == original(rows, gate, reference_policy='strongest_eligible')
            parity_rows += len(rows)
            parity_runs += 1
    summaries, disagreements, checks = [], [], []
    outputs = {}
    for variant in VARIANTS:
        for gate in GATES:
            outputs[variant, gate] = {case: predictions(rows, gate, variant) for case, rows in data.items()}
            maps = {case: {row['time']: row for row in out}
                    for case, out in outputs[variant, gate].items()}
            failures = []
            for label in labels:
                actual = maps[label['case']][label['time']]
                prefix = [row for row in data[label['case']] if row['time'] <= label['time']]
                assert predictions(prefix, gate, variant)[-1] == actual
                record = dict(**label, variant=variant, gate=gate, actual=actual['event'],
                              matched=actual['event'] == label['expected'], prefix_matched=True)
                checks.append(record)
                if not record['matched']:
                    failures.append(record)
            summaries.append(dict(variant=variant, gate=gate, points=47, failures=failures))
            # Skip jul_120, which is a prefix of aug_120, to avoid duplicate targets.
            for case in ('aug_120', 'daily_2025', 'may_120', 'bottom_daily', 'mins60', 'mins90'):
                base = outputs['fixed2', gate][case]
                for a, b in zip(base, outputs[variant, gate][case]):
                    if (a['event'], a['event_ref_start']) != (b['event'], b['event_ref_start']):
                        disagreements.append(dict(case=case, time=a['time'], gate=gate,
                                                  variant=variant, baseline=a, alternative=b))
    surviving = [v for v in VARIANTS if all(not s['failures'] for s in summaries if s['variant'] == v)]
    survivor_differences = [d for d in disagreements if d['variant'] in surviving]
    assert surviving == ['fixed2', 'crossed2', 'dominated2']
    assert not survivor_differences, 'Reconsider target selection if surviving variants diverge'

    # Alternative screening: later raw-DIF crossing of an already confirmed
    # structure after reset, with no same-reference baseline cancel. This is
    # a separate lifecycle ambiguity, not proof about the fixed window length.
    pool = []
    for case in ('aug_120', 'may_120', 'daily_2025', 'bottom_daily', 'mins90', 'mins60'):
        rows = data[case]
        out = outputs['fixed2', 1][case]
        for dropped in dropped_references(rows, out):
            cross = dropped['first_later_raw_dif_cross']
            if not cross or dropped['last_state'] != 'STRUCTURE' or dropped['same_reference_cancel_at_cross']:
                continue
            margin = abs(cross['dif'] - dropped['reference_dif'])
            pred = dropped['candidate_event_at_cross']
            pool.append(dict(case=case, time=cross['time'], margin=margin,
                             baseline_event=pred['event'], **{key: dropped[key] for key in
                             ('activation_time', 'reference_start', 'reference_dif', 'reset_time')}))
    # Prefer 90m (usually available in supplied videos), then 60m. Require a
    # visible numerical margin >0.05; this is a screen heuristic, not a formula.
    unique = {}
    for item in pool:
        if item['baseline_event'] == 'NONE' and item['margin'] > .05:
            unique.setdefault((item['case'], item['time']), item)
    ranked = sorted(unique.values(), key=lambda r: (0 if r['case'] == 'mins90' else 1, r['time']))
    selected = ranked[:3]
    assert len(selected) == 3
    target_checks = []
    for item in selected:
        target = dict(item, hypotheses=dict(
            reset_clears_confirmation='No additional old-structure disappearance event',
            retained_until_dif_break='Old confirmed structure loses validity on first strict DIF crossing'),
            predictions=[])
        for gate in GATES:
            result = lifecycle_target(data[item['case']], item['time'], gate)
            assert result['baseline'] == next(row for row in outputs['fixed2', gate][item['case']]
                                             if row['time'] == item['time'])
            target['predictions'].append(dict(gate=gate, **result))
        target_checks.append(target)
    frozen_payload = dict(
        scope='Freeze before retrieving selected-day captions; historical saved-input screen, no unseen software labels',
        selection_method='Among structure-reset-later-cross cases, prefer 90m then 60m, NONE baseline event, DIF margin >0.05, chronological; deduplicate same timestamp',
        candidate_sha256=sha(ROOT / 'replay_color_flip.py'),
        audit_script_sha256=sha(Path(__file__)), variant_script_sha256=sha(ROOT / 'reference_retirement_candidate.py'),
        inputs={filename: sha(ROOT / 'inputs' / filename) for filename in sorted(set(CASES.values()))},
        eligible_pool=ranked, targets=target_checks,
        limits=['A conditional old-structure invalidation monitor is not a complete replacement algorithm.',
                'A green marker can refer to dullness disappearance or structure invalidity; images and narration must establish its subject.',
                '90m DG/software binning and numerical differences remain unresolved.',
                'The two added retirement filters are observationally equivalent in these saved inputs only, not proved mathematically identical.'])
    target_path = ROOT / 'reference_retirement_targets_frozen.json'
    if target_path.exists():
        prior = json.loads(target_path.read_text())
        prior.pop('frozen_at')
        assert prior == frozen_payload, 'Never overwrite changed frozen predictions'
    else:
        target_path.write_text(json.dumps(dict(frozen_at=datetime.now(timezone.utc).isoformat(),
                                               **frozen_payload), ensure_ascii=False, indent=2) + '\n')
    assert all(sha(ROOT / name) == digest for name, digest in protected.items())
    report = dict(as_of=datetime.now(timezone.utc).isoformat(), observed_points=47,
                  direct=sum(label['confidence'] == 'direct' for label in labels),
                  mapped=sum(label['confidence'] == 'mapped' for label in labels),
                  parity_runs=parity_runs, parity_rows=parity_rows,
                  old_files_unchanged=len(protected), protected=protected,
                  prefix_checks=len(checks), checks=checks, summaries=summaries,
                  surviving_variants=surviving, survivor_differences=survivor_differences,
                  all_disagreements=disagreements, lifecycle_pool=pool,
                  frozen_target_file=target_path.name, target_prefix_checks=len(selected)*len(GATES))
    (ROOT / 'reference_retirement_screen.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(surviving=surviving, surviving_event_or_ref_differences=len(survivor_differences),
                         prefix_checks=len(checks), parity_runs=parity_runs, parity_rows=parity_rows,
                         unchanged=len(protected), selected=[dict(case=r['case'], time=r['time'], margin=r['margin'],
                         monitor_by_gate=[p['conditional_prediction'] for p in r['predictions']]) for r in target_checks]), ensure_ascii=False))


if __name__ == '__main__':
    main()
