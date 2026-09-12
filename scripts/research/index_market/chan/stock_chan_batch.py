"""G2b fixed first ten stocks, immutable per-seat evidence and verified resume."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import time

from scripts.research.index_market.chan.m0_data import REPO, digest, safe_output
from scripts.research.index_market.chan.minute_replay import replay
from scripts.research.index_market.chan.minute_variant_a import verify_variant_source
from scripts.research.index_market.chan.run_m0 import save
from scripts.research.index_market.chan.stock_chan_batch_data import SPEC, load_batch, seat_input
from scripts.research.index_market.chan.stock_chan_rank import PLAN
from scripts.research.index_market.chan.stock_chan_replay import (
    adapter, authenticated_manifest, diagnose_window, freeze_samples, run_checks,
)
from scripts.research.index_market.chan.stock_chan_replay_audit import audit as audit_pilot, reconstruct
from scripts.research.index_market.chan.stock_chan_replay_data import Reader


CODE_FILES = ('stock_chan_batch.py', 'stock_chan_batch_data.py', 'stock_chan_replay.py',
              'stock_chan_replay_data.py', 'stock_chan_replay_audit.py', 'stock_chan_rank.py',
              'minute_replay.py', 'minute_variant_a.py', 'minute_data.py', 'minute_roundtrip.py',
              'm0_data.py', 'event_ledger.py', 'run_m0.py')


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode())


def code_hashes():
    return {name: digest((Path(__file__).parent/name).read_bytes()) for name in CODE_FILES}


def verify_artifacts(folder, manifest):
    for name, expected in manifest['artifacts_sha256'].items():
        path = (folder/name).resolve(strict=True)
        if not path.is_relative_to(folder.resolve()) or digest(path.read_bytes()) != expected:
            raise ValueError(f'artifact changed: {path}')


def seal(folder, metadata):
    paths = sorted(p for p in folder.rglob('*') if p.is_file())
    if any(p.name == 'manifest.json' for p in paths):
        raise ValueError('unit already sealed')
    size = sum(p.stat().st_size for p in paths)
    if size > SPEC.max_output_bytes:
        raise ValueError('unit output budget')
    value = dict(metadata, artifacts_sha256={str(p.relative_to(folder)): digest(p.read_bytes()) for p in paths})
    save(folder/'manifest.json', value)
    return dict(unit_id=metadata['unit_id'], status=metadata['status'],
                manifest_path=str((folder/'manifest.json').relative_to(REPO)),
                manifest_sha256=digest((folder/'manifest.json').read_bytes()))


def verify_unit(ref, seat, rows, source_fingerprint, expected_code):
    path = (REPO/ref['manifest_path']).resolve(strict=True)
    if not path.is_relative_to(REPO/'reports') or digest(path.read_bytes()) != ref['manifest_sha256']:
        raise ValueError('unit manifest identity/path changed')
    manifest = json.loads(path.read_text())
    if (manifest['unit_id'] != f"{seat['code']}/{seat['window_id']}" or manifest['seat'] != seat
            or manifest['spec_fingerprint'] != fingerprint(asdict(SPEC))
            or manifest['code_sha256'] != expected_code
            or manifest['source_fingerprint'] != source_fingerprint
            or manifest['input_fingerprint'] != fingerprint(rows)
            or manifest['status'] != ref['status']):
        raise ValueError('unit scope/code/input identity mismatch')
    if manifest['status'] not in ('complete', 'insufficient_history', 'stability_failed', 'stability_unverified', 'data_blocked'):
        raise ValueError('unit not terminal')
    verify_artifacts(path.parent, manifest)
    return manifest


def resume_state(folder, expected_code, current_sources):
    if folder is None:
        return {}, 0.0
    folder = folder.resolve(strict=True)
    if not folder.is_relative_to(REPO/'reports'):
        raise ValueError('resume outside reports')
    manifest = json.loads((folder/'manifest.json').read_text())
    if manifest['spec'] != json.loads(json.dumps(asdict(SPEC))) or manifest['code_sha256'] != expected_code:
        raise ValueError('resume spec/code changed')
    verify_artifacts(folder, manifest)
    old_sources = json.loads((folder/'source_hashes.json').read_text())
    if old_sources != current_sources:
        raise ValueError('resume source snapshot changed')
    refs = manifest['units']
    if len({r['unit_id'] for r in refs}) != len(refs):
        raise ValueError('duplicate resume units')
    return {r['unit_id']: r for r in refs}, manifest['cumulative_seconds']


def run_unit(folder, batch, seat, window, source_fingerprint, codes, clock):
    folder.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    rows, quality = seat_input(batch, seat, window)
    save(folder/'input.json', rows)
    save(folder/'quality.json', quality)
    save(folder/'window.json', window)
    status = quality['status']
    if status == 'ready':
        if quality['quality']['history_days_before_observation'] < 2*SPEC.history_days:
            # Do not call a shorter initialization with insufficient remaining history "stable".
            changes = []
            events = replay(rows[:-1], seat['code'], SPEC.frequency,
                            adapter(seat['code'], SPEC.pilot_seconds-(time.monotonic()-clock.started)), sink=changes.extend)
            save(folder/'full_events.json', events)
            save(folder/'changes.json', changes)
            checks = dict(all_passed=False, reason='shorter_initialization_below_250_days')
            status = 'stability_unverified'
        else:
            events, checks = run_checks(rows, seat['code'], window, clock, folder)
            status = 'complete' if checks['all_passed'] else 'stability_failed'
        saved = [(e['event_id'], e['signal_time'], e['signal_index'], e['anchor_index'], e['anchor_time']) for e in events]
        changes = json.loads((folder/'changes.json').read_text())
        if saved != reconstruct(changes):
            raise ValueError('first-known event reconstruction mismatch')
        diagnostic = diagnose_window(rows, events, window, batch['days'])
        ranking = json.loads((REPO/SPEC.rank_report/seat['window_id']/'ranking.json').read_text())
        expected = next(r for r in ranking if r['ts_code'] == seat['code'])['gross_change']
        if not math.isclose(diagnostic['interval_change'], expected, rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError('G1 endpoint return mismatch')
        checks.update(reconstructed_events=len(saved), g1_return_equal=True,
                      initialization_observation_events=sum(e['signal_time'] >= window['prior_days'][0] for e in events))
        save(folder/'checks.json', checks)
        save(folder/'diagnostics.json', diagnostic)
    metadata = dict(unit_id=f"{seat['code']}/{seat['window_id']}", seat=seat, status=status,
                    seconds=time.monotonic()-started, spec_fingerprint=fingerprint(asdict(SPEC)),
                    code_sha256=codes, source_fingerprint=source_fingerprint, input_fingerprint=fingerprint(rows))
    return seal(folder, metadata)


def execute(output, resume_from=None, pause_after_first_unit=False, spec=SPEC):
    if asdict(spec) != asdict(SPEC):
        raise ValueError('unapproved batch specification')
    started = time.monotonic()
    output = safe_output(output)
    if shutil.disk_usage(REPO).free < 2*spec.max_output_bytes:
        raise ValueError('report disk reserve')
    pilot = authenticated_manifest(REPO/spec.pilot_report, spec.pilot_manifest)
    audit_pilot(REPO/spec.pilot_report)
    source = verify_variant_source(Path(pilot['source']['path']))
    if source != pilot['source']:
        raise ValueError('frozen third-party source changed')
    g1 = authenticated_manifest(REPO/spec.rank_report, spec.rank_manifest)
    windows, seats, all_codes, unmatched = freeze_samples(REPO/spec.rank_report, g1)
    output.mkdir(parents=True, exist_ok=False)
    reader, codes, cumulative_before = Reader(spec), code_hashes(), 0.0
    result = dict(status='running', spec=asdict(spec), code_sha256=codes, units=[],
                  plan_sha256=digest(PLAN.read_bytes()), source=source,
                  created_at_utc=datetime.now(timezone.utc).isoformat(),
                  resume_from=str(resume_from) if resume_from else None,
                  pause_after_first_unit=pause_after_first_unit, full_population_executed=False)
    try:
        batch = load_batch(reader, windows, seats, all_codes, spec)
        save(output/'preflight.json', {k: batch[k] for k in ('selected', 'seats', 'profile', 'gaps', 'suspension', 'budget', 'life', 'days')})
        save(output/'unmatched_controls.json', unmatched)
        g1_sources = json.loads((REPO/spec.rank_report/'source_hashes.json').read_text())
        if any(g1_sources[p] != h for p,h in reader.hashes.items() if p in g1_sources):
            raise ValueError('G1 snapshot changed before batch')
        refs, cumulative_before = resume_state(resume_from, codes, reader.hashes)
        wanted = {f"{s['code']}/{s['window_id']}" for s in batch['seats']}
        if set(refs)-wanted:
            raise ValueError('resume units outside fixed first batch')
        source_fingerprint = fingerprint(reader.hashes)
        stock_clock, active_code, prior_stock_seconds = None, None, {}
        result.update(status='complete', total_seats=len(batch['seats']), reused_units=0,
                      global_budget=batch['budget'])
        for seat in batch['seats']:
            if cumulative_before+time.monotonic()-started > spec.total_seconds:
                raise TimeoutError('cumulative batch time budget')
            key = f"{seat['code']}/{seat['window_id']}"
            print(f"G2b {len(result['units'])}/{len(batch['seats'])}: {key}", flush=True)
            window = next(w for w in windows if w['window_id'] == seat['window_id'])
            rows = [r for r in batch['prices'] if r['code'] == seat['code'] and r['time'] <= window['exit_bar_end']]
            if key in refs:
                old = verify_unit(refs[key], seat, rows, source_fingerprint, codes)
                prior_stock_seconds[seat['code']] = prior_stock_seconds.get(seat['code'], 0)+old['seconds']
                result['units'].append(dict(refs[key], reused=True))
                result['reused_units'] += 1
                continue
            if active_code != seat['code']:
                stock_clock, active_code = Reader(), seat['code']
                stock_clock.started -= prior_stock_seconds.get(seat['code'], 0)
            stock_clock.check_time()
            ref = run_unit(output/'units'/seat['code']/seat['window_id'], batch, seat,
                           window, source_fingerprint, codes, stock_clock)
            verify_unit(ref, seat, rows, source_fingerprint, codes)
            result['units'].append(dict(ref, reused=False))
            print(f"G2b sealed {len(result['units'])}/{len(batch['seats'])}: {key} {ref['status']}", flush=True)
            if ref['status'] in ('data_blocked', 'stability_failed'):
                result['status'] = ref['status']
                break
            if pause_after_first_unit:
                result['status'] = 'paused_after_unit'
                break
        result['read_audit'] = reader.verify_unchanged()
    except BaseException as exc:
        result.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'blocked',
                      error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        save(output/'source_hashes.json', reader.hashes)
        save(output/'queries.json', reader.queries)
        result['elapsed_seconds'] = time.monotonic()-started
        result['cumulative_seconds'] = cumulative_before+result['elapsed_seconds']
        paths = sorted(p for p in output.rglob('*') if p.is_file())
        if sum(p.stat().st_size for p in paths) > spec.max_output_bytes:
            result['status'] = 'output_budget_exceeded'
        result['artifacts_sha256'] = {str(p.relative_to(output)): digest(p.read_bytes()) for p in paths}
        save(output/'manifest.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume-from', type=Path)
    parser.add_argument('--pause-after-first-unit', action='store_true')
    args = parser.parse_args()
    result = execute(args.output, args.resume_from, args.pause_after_first_unit)
    print(json.dumps({k:result.get(k) for k in ('status', 'total_seats', 'reused_units', 'cumulative_seconds')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
