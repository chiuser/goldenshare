"""Read back G2a artifacts and independently reconstruct first-known event times."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.research.index_market.chan.m0_data import REPO, digest
from scripts.research.index_market.chan.minute_roundtrip import validate_cell
from scripts.research.index_market.chan.stock_chan_replay import diagnose_window, event_signature
from scripts.research.index_market.chan.stock_chan_replay_data import SPEC


def reconstruct(changes):
    states, seen, rebuilt = {}, set(), []
    last_time = ''
    for item in changes:
        key, timestamp, point = item['candidate_id'], item['time'], item['after']
        if timestamp < last_time or states.get(key) != item['before']:
            raise ValueError('change order or before-state mismatch')
        last_time = timestamp
        if point is None:
            del states[key]
            continue
        states[key] = point
        if not point['sure']:
            continue
        prefix = 'B' if point['buy'] else 'S'
        for suffix in ('1', '2', '3'):
            match = suffix in point['types'] if suffix != '3' else bool({'3a', '3b'} & set(point['types']))
            identity = f'{key}|{prefix}{suffix}'
            if match and identity not in seen:
                seen.add(identity)
                rebuilt.append((identity, timestamp, item['index'], point['anchor_index'], point['anchor_time']))
    return rebuilt


def audit(report):
    report = report.resolve(strict=True)
    if not report.is_relative_to(REPO/'reports'):
        raise ValueError('not a research report')
    raw = (report/'manifest.json').read_bytes()
    manifest = json.loads(raw)
    if manifest['status'] != 'pilot_complete':
        raise ValueError('pilot not complete')
    for name, expected in manifest['artifacts_sha256'].items():
        path = (report/name).resolve(strict=True)
        if not path.is_relative_to(report) or digest(path.read_bytes()) != expected:
            raise ValueError(f'artifact changed: {name}')
    for name, expected in manifest['code_sha256'].items():
        if digest((Path(__file__).parent/name).read_bytes()) != expected:
            raise ValueError(f'execution code changed: {name}')

    def read(name):
        if name not in manifest['artifacts_sha256']:
            raise ValueError('unhashed artifact')
        return json.loads((report/name).read_text())

    rows, events = read('input.json'), read('full_events.json')
    validate_cell(rows, events, manifest['pilot'], SPEC.frequency)
    rebuilt = reconstruct(read('changes.json'))
    saved = [(e['event_id'], e['signal_time'], e['signal_index'], e['anchor_index'], e['anchor_time']) for e in events]
    if saved != rebuilt:
        raise ValueError('first event reconstruction mismatch')
    window = read('window.json')
    if any(e['signal_time'] >= rows[-1]['time'] for e in events):
        raise ValueError('exit bar leaked into replay')
    diagnostics = diagnose_window(rows, events, window, read('calendar.json'))
    if diagnostics != read('diagnostics.json'):
        raise ValueError('saved path diagnostics mismatch')
    cutoff, start = window['signal_time'], window['prior_days'][0]
    tests = {
        'prefix': event_signature(events, end=cutoff) == event_signature(read('prefix_events.json')),
        'future': event_signature(events, end=cutoff) == event_signature(read('future_perturbed_events.json'), end=cutoff),
        'scaling': event_signature(events) == event_signature(read('scaled_events.json')),
        'initialization': event_signature(events, start=start) == event_signature(read('shorter_history_events.json'), start=start),
    }
    if not all(tests.values()):
        raise ValueError('saved stability checks mismatch')
    return dict(manifest_sha256=digest(raw), artifacts=len(manifest['artifacts_sha256']),
                reconstructed_events=len(rebuilt), diagnostics_recomputed=True, stability_checks=tests,
                prefix_compared_events=len(event_signature(events, end=cutoff)),
                initialization_observation_events=len(event_signature(events, start=start)),
                caveat='Empty observation windows do not establish initialization robustness for actual signals.',
                audit_code_sha256=digest(Path(__file__).read_bytes()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.report), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
