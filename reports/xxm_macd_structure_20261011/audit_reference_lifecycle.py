"""Audit frozen research candidates using saved data only.

No new signal formula: history-window comparisons call the original replay.
The post-reset monitor records when a dropped reference is later crossed;
it does not turn these crossings into software labels or trading signals.
"""
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from replay_color_flip import read_rows, replay
from validate_stage2 import CASES, evidence_labels

ROOT = Path(__file__).resolve().parent
WINDOWS = (1, 2, 3, 4, 5, 10000)
GATES = (.75, 1, 1.2)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wave_inventory(rows):
    """Causal segment inventory, checked against original replay counts."""
    history = {1: [], -1: []}
    wave = None
    result = {}
    for row in rows:
        sign = (row['hist'] > 0) - (row['hist'] < 0)
        if wave is None or wave['sign'] != sign:
            if wave and wave['sign']:
                history[wave['sign']].append(wave.copy())
            wave = dict(start=row['time'], sign=sign, count=0,
                        price=row['close'], dif=row['dif'],
                        price_time=row['time'], dif_time=row['time'])
        wave['count'] += 1
        if sign * (row['close'] - wave['price']) > 0:
            wave['price'], wave['price_time'] = row['close'], row['time']
        if sign * (row['dif'] - wave['dif']) > 0:
            wave['dif'], wave['dif_time'] = row['dif'], row['time']
        result[row['time']] = dict(
            wave=wave.copy(), previous_same_direction=[w.copy() for w in history.get(sign, [])])
    return result


def dropped_references(rows, predictions):
    """Describe reset loss and subsequent raw-DIF crossings, retrospectively."""
    active = None
    previous = None
    dropped = []
    for index, prediction in enumerate(predictions):
        if previous and prediction['wave_sign'] != previous['wave_sign'] and active:
            old = dict(active)
            old.update(reset_time=prediction['time'], last_state=previous['state'],
                       reset_event=prediction['event'], reset_route=prediction['event_route'])
            crossing = next((r for r in rows[index:]
                             if old['direction'] * (r['dif'] - old['reference_dif']) > 0), None)
            old['first_later_raw_dif_cross'] = crossing
            if crossing:
                actual = predictions[next(i for i, r in enumerate(rows) if r['time'] == crossing['time'])]
                old['candidate_event_at_cross'] = actual
                old['same_reference_cancel_at_cross'] = (
                    actual['event'] == 'CANCEL' and actual['event_ref_start'] == old['reference_start'])
            dropped.append(old)
            active = None
        if prediction['event'] == 'DULL' and prediction['event_route'] == 'activation':
            active = dict(activation_time=prediction['time'], direction=prediction['event_direction'],
                          reference_start=prediction['event_ref_start'],
                          reference_dif=prediction['event_ref_dif'],
                          reference_price=prediction['event_ref_price'])
        if prediction['state'] == 'NONE':
            active = None
        previous = prediction
    return dropped


def main():
    protected = json.loads((ROOT / 'reference_lifecycle_frozen.json').read_text())
    for item in protected['files']:
        assert sha(ROOT / item['file']) == item['sha256'], item['file']
    labels = evidence_labels()
    for name in ('holdout_20250818.json', 'holdout_20250626.json'):
        for label in json.loads((ROOT / name).read_text())['labels']:
            labels.append(dict(case='aug_120', time=label['time'],
                               expected=label['expected_event'], confidence=label['confidence'],
                               source=name, conditional_on_marker_semantics=name.endswith('0626.json')))
    assert len(labels) == 43
    data = {case: read_rows(name) for case, name in CASES.items()}
    summaries, comparisons, prefixes = [], [], 0
    for window in WINDOWS:
        for gate in GATES:
            outputs = {case: {r['time']: r for r in replay(rows, gate,
                       reference_policy='strongest_eligible', max_refs=window)}
                       for case, rows in data.items()}
            current = []
            for label in labels:
                predicted = outputs[label['case']][label['time']]
                prefix = [r for r in data[label['case']] if r['time'] <= label['time']]
                assert replay(prefix, gate, reference_policy='strongest_eligible',
                              max_refs=window)[-1] == predicted
                prefixes += 1
                row = dict(**label, window=window, threshold_pct=gate,
                           actual=predicted['event'], ref=predicted['ref_start'],
                           matched=predicted['event'] == label['expected'])
                comparisons.append(row)
                current.append(row)
            summaries.append(dict(window=window, threshold_pct=gate,
                                  observed_points=len(current),
                                  mismatches=[r for r in current if not r['matched']]))
    inventories, dropped = {}, {}
    for case, rows in data.items():
        predictions = replay(rows, 1, reference_policy='strongest_eligible')
        inventory = wave_inventory(rows)
        for row in predictions:
            assert inventory[row['time']]['wave']['count'] == row['wave_count']
            assert inventory[row['time']]['wave']['sign'] == row['wave_sign']
        inventories[case] = inventory
        dropped[case] = dropped_references(rows, predictions)
    differences = []
    for case in ('aug_120', 'daily_2025', 'may_120', 'bottom_daily'):
        rows = data[case]
        two = replay(rows, 1, reference_policy='strongest_eligible', max_refs=2)
        three = replay(rows, 1, reference_policy='strongest_eligible', max_refs=3)
        for a, b in zip(two, three):
            if a['event'] != b['event']:
                differences.append(dict(case=case, time=a['time'], window2=a, window3=b,
                                        software_label='NOT_CONFIRMED'))
    target = [d for d in differences if d['case'] == 'aug_120'
              and d['time'] in ('2025-10-24 15:00:00', '2025-10-27 11:30:00')]
    assert len(target) == 2
    target_predictions = []
    for gate in GATES:
        for window in (2, 3):
            predictions = replay(data['aug_120'], gate,
                                 reference_policy='strongest_eligible', max_refs=window)
            for row in predictions:
                if row['time'] in [d['time'] for d in target]:
                    prefix = [r for r in data['aug_120'] if r['time'] <= row['time']]
                    assert replay(prefix, gate, reference_policy='strongest_eligible',
                                  max_refs=window)[-1] == row
                    target_predictions.append(dict(window=window, threshold_pct=gate, **row,
                                                    software_label='NOT_CONFIRMED'))
    target_path = ROOT / 'reference_next_20251024_27.json'
    target_payload = dict(
        scope='Before target-day caption retrieval or new screenshots; variants use unchanged candidate.',
        candidate_sha256=sha(ROOT / 'replay_color_flip.py'),
        input_sha256=sha(ROOT / 'inputs/120_20250401_20251111.csv'),
        predictions=target_predictions,
        causal_pools={time: inventories['aug_120'][time] for time in [d['time'] for d in target]},
    )
    if target_path.exists():
        # Re-running the audit must preserve the first prediction and its date.
        existing = json.loads(target_path.read_text())
        existing.pop('frozen_at')
        assert existing == target_payload, 'Frozen predictions differ; keep the original file'
    else:
        target_path.write_text(json.dumps(dict(
            frozen_at=datetime.now(timezone.utc).isoformat(), **target_payload),
            ensure_ascii=False, indent=2) + '\n')
    for item in protected['files']:
        assert sha(ROOT / item['file']) == item['sha256'], item['file']
    report = dict(
        as_of=datetime.now(timezone.utc).isoformat(),
        scope='Research sensitivity and lifecycle audit, not a recovered software formula or blind accuracy test.',
        script_sha256=sha(Path(__file__)), candidate_sha256=sha(ROOT / 'replay_color_flip.py'),
        old_frozen_files_unchanged=len(protected['files']), labels=labels,
        prefix_checks=prefixes, summaries=summaries, window2_vs3_differences=differences,
        dropped_active_references=dropped,
        case_windows={case: dict(input=CASES[case], start=rows[0]['time'], end=rows[-1]['time'],
                                rows=len(rows), sha256=sha(ROOT / 'inputs' / CASES[case]))
                      for case, rows in data.items()},
        june_inventory={time: inventories['aug_120'][time]
                        for time in ('2025-06-13 11:30:00', '2025-06-24 11:30:00', '2025-06-24 15:00:00')},
        jan13_all_available=next(r for r in replay(data['mins90'], 1,
                                 reference_policy='strongest_eligible', max_refs=10000)
                                 if r['time'] == '2026-01-13 15:00:00'),
        limitations=[
            'Seven input cases overlap; 43 observation points are not 43 independent market episodes.',
            'Mapped absences and event positions depend on stable marker rendering.',
            '90-minute DG and software values differ; January mismatch tests this numerical candidate only.',
            'Window comparisons retain every other original assumption, including one-bar color splitting.',
            'All available history is left-truncated; this is not full market history.',
            'Later raw-DIF crosses are retrospective diagnostics, not automatic software cancellations.',
            'Green marker near June24 remains unassigned and is not scored.',
        ])
    (ROOT / 'reference_lifecycle_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    with (ROOT / 'reference_window_comparison.csv').open('w', newline='') as handle:
        fields = ['case', 'time', 'expected', 'confidence', 'source', 'window',
                  'threshold_pct', 'actual', 'ref', 'matched', 'conditional_on_marker_semantics']
        writer = csv.DictWriter(handle, fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(comparisons)
    print(json.dumps(dict(prefix_checks=prefixes, points=len(labels),
                          summaries=[dict(window=r['window'], threshold=r['threshold_pct'],
                                          mismatches=len(r['mismatches'])) for r in summaries],
                          reset_counts={k: len(v) for k, v in dropped.items()},
                          window2_vs3_event_differences=len(differences)), ensure_ascii=False))


if __name__ == '__main__':
    main()
