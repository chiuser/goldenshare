"""Read-only G2b artifact audit and descriptive first-batch summary."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from scripts.research.index_market.chan.m0_data import REPO, digest
from scripts.research.index_market.chan.minute_roundtrip import validate_cell
from scripts.research.index_market.chan.stock_chan_batch import (
    code_hashes, fingerprint, resume_state, verify_unit,
)
from scripts.research.index_market.chan.stock_chan_replay import diagnose_window, event_signature
from scripts.research.index_market.chan.stock_chan_replay_audit import reconstruct


def audit(report):
    report = report.resolve(strict=True)
    manifest = json.loads((report/'manifest.json').read_text())
    sources = json.loads((report/'source_hashes.json').read_text())
    refs, _ = resume_state(report, code_hashes(), sources)
    preflight = json.loads((report/'preflight.json').read_text())
    source_fingerprint = fingerprint(sources)
    identities = {r['ts_code']:r for r in preflight['life']}
    rows_out, rebuilt_count, durations = [], 0, []
    for seat in preflight['seats']:
        key = f"{seat['code']}/{seat['window_id']}"
        if key not in refs:
            rows_out.append(dict(**seat, name=identities[seat['code']]['name'], status='not_executed'))
            continue
        ref = refs[key]
        folder = (REPO/ref['manifest_path']).parent
        rows = json.loads((folder/'input.json').read_text())
        unit = verify_unit(ref, seat, rows, source_fingerprint, code_hashes())
        item = dict(**seat, name=identities[seat['code']]['name'], status=unit['status'],
                    manifest_path=ref['manifest_path'], reused=ref.get('reused', False))
        if unit['status'] in ('insufficient_history', 'data_blocked'):
            rows_out.append(item)
            continue
        events = json.loads((folder/'full_events.json').read_text())
        changes = json.loads((folder/'changes.json').read_text())
        validate_cell(rows, events, seat['code'], 30)
        saved = [(e['event_id'], e['signal_time'], e['signal_index'], e['anchor_index'], e['anchor_time']) for e in events]
        if saved != reconstruct(changes):
            raise ValueError(f'first event reconstruction mismatch: {key}')
        rebuilt_count += len(events)
        if any(e['signal_time'] >= rows[-1]['time'] for e in events):
            raise ValueError('exit bar leaked into replay')
        window = json.loads((folder/'window.json').read_text())
        diag = diagnose_window(rows, events, window, preflight['days'])
        if diag != json.loads((folder/'diagnostics.json').read_text()):
            raise ValueError(f'diagnostics mismatch: {key}')
        checks = json.loads((folder/'checks.json').read_text())
        if unit['status'] != 'stability_unverified':
            def read(name):
                return json.loads((folder/f'{name}_events.json').read_text())
            cutoff, start = window['signal_time'], window['prior_days'][0]
            actual = {
                'prefix_equal': event_signature(events, end=cutoff) == event_signature(read('prefix')),
                'future_isolation_equal': event_signature(events, end=cutoff) == event_signature(read('future_perturbed'), end=cutoff),
                'uniform_scaling_equal': event_signature(events) == event_signature(read('scaled')),
                'shorter_initialization_observation_equal': event_signature(events, start=start) == event_signature(read('shorter_history'), start=start),
            }
            if any(checks[k] != v for k,v in actual.items()) or checks['all_passed'] != all(actual.values()):
                raise ValueError('stability check mismatch')
            durations.append(checks['seconds_by_replay'])
        quality = json.loads((folder/'quality.json').read_text())
        item.update(bars=len(rows)-1, full_events=len(events), window_change=diag['interval_change'],
                    observation_buys=diag['observation_buy_count'],
                    buy_groups=dict(Counter(x['event']['group'] for x in diag['all_observation_buys'])),
                    timing=dict(Counter(x['timing'] for x in diag['all_observation_buys'])),
                    first_by_group=diag['first_by_group'], suspension_days=len(quality['gaps']),
                    nonempty_initialization_comparison=checks['initialization_observation_events'] > 0)
        rows_out.append(item)
    return dict(status=manifest['status'], report_manifest_sha256=digest((report/'manifest.json').read_bytes()),
                audit_code_sha256=digest(Path(__file__).read_bytes()),
                selected_stocks=len(preflight['selected']), expected_seats=len(preflight['seats']),
                sealed_units=len(refs), reused_units=manifest.get('reused_units'),
                reconstructed_events=rebuilt_count, source_snapshot_files=len(sources),
                full_population_executed=False, rows=rows_out, durations=durations,
                global_budget=preflight['budget'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.report), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
