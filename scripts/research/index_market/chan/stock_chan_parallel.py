"""Benchmark 1/2/4 spawned workers on authenticated G2b first-ten inputs only."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import asdict
from datetime import datetime, timezone
import json
import multiprocessing
from pathlib import Path
import platform
import time

from scripts.research.index_market.chan.m0_data import REPO, digest, safe_output
from scripts.research.index_market.chan.run_m0 import save
from scripts.research.index_market.chan.stock_chan_batch import code_hashes, fingerprint
from scripts.research.index_market.chan.stock_chan_batch_audit import audit
from scripts.research.index_market.chan.stock_chan_rank import PLAN
from scripts.research.index_market.chan.stock_chan_shared_replay import (
    MODES, SPEC, initialize, read_verified, rss_bytes, run_stock,
)


def benchmark_hashes():
    names = ('stock_chan_parallel.py', 'stock_chan_shared_replay.py', 'stock_chan_batch_audit.py')
    return code_hashes() | {n: digest((Path(__file__).parent/n).read_bytes()) for n in names}


def prepare(spec=SPEC):
    if spec != SPEC:
        raise ValueError('unapproved performance specification')
    folder = REPO/spec.report
    manifest = read_verified(folder/'manifest.json', spec.manifest)
    if manifest['status'] != 'complete' or len(manifest['units']) != spec.seats:
        raise ValueError('incomplete/wrong-size reference')
    # Bound reference reads before invoking the existing independent audit.
    files = {folder/'manifest.json', *(folder/n for n in manifest['artifacts_sha256'])}
    for ref in manifest['units']:
        path = (REPO/ref['manifest_path']).resolve(strict=True)
        if not path.is_relative_to(REPO/'reports'):
            raise ValueError('reference outside reports')
        unit = read_verified(path, ref['manifest_sha256'])
        files.add(path)
        files.update(path.parent/n for n in unit['artifacts_sha256'])
    if (any(not p.resolve(strict=True).is_relative_to(REPO/'reports') for p in files)
            or sum(p.stat().st_size for p in files) > spec.max_bytes):
        raise ValueError('reference byte/path budget')
    frozen = {str(p): digest(p.read_bytes()) for p in sorted(files)}
    verified = audit(folder)
    if verified['sealed_units'] != spec.seats or verified['selected_stocks'] != spec.stocks:
        raise ValueError('reference stock/seat scope')
    preflight = json.loads((folder/'preflight.json').read_text())
    jobs = {}
    for ref in manifest['units']:
        path = REPO/ref['manifest_path']
        unit = json.loads(path.read_text())
        if unit['status'] != 'complete':
            raise ValueError('benchmark requires already verified complete units')
        code = unit['seat']['code']
        job = jobs.setdefault(code, dict(code=code, days=preflight['days'], seats=[]))
        expected = {}
        for name in tuple(f'{m}_events' for m in MODES)+('changes', 'diagnostics'):
            expected[name] = fingerprint(json.loads((path.parent/f'{name}.json').read_text()))
        job['seats'].append(dict(unit_id=ref['unit_id'],
            input_path=str(path.parent/'input.json'), input_sha256=unit['artifacts_sha256']['input.json'],
            window_path=str(path.parent/'window.json'), window_sha256=unit['artifacts_sha256']['window.json'],
            expected=expected))
    if sorted(jobs) != sorted(preflight['selected']) or len(jobs) != spec.stocks:
        raise ValueError('stock scope changed')
    assert_unchanged(frozen)
    return sorted(jobs.values(), key=lambda j: j['code']), manifest['source'], verified, frozen


def assert_unchanged(hashes):
    for name, expected in hashes.items():
        if digest(Path(name).read_bytes()) != expected:
            raise ValueError(f'reference changed during benchmark: {name}')


def run_phase(jobs, workers, source, deadline, output, spec=SPEC):
    if workers not in spec.worker_counts or len(jobs) != spec.stocks:
        raise ValueError('worker/stock budget')
    output.mkdir(exist_ok=False)
    ctx = multiprocessing.get_context('spawn')
    cancel = ctx.Event()
    started, results, peaks = time.monotonic(), [], {}
    remaining = iter(jobs)
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx,
                             initializer=initialize, initargs=(source, cancel, deadline)) as pool:
        pending = {}

        def dispatch():
            if cancel.is_set() or time.monotonic() > deadline:
                raise TimeoutError('stop dispatch at benchmark deadline/cancellation')
            job = next(remaining, None)
            if job is not None:
                pending[pool.submit(run_stock, job)] = job['code']

        try:
            for _ in range(workers):
                dispatch()
            while pending:
                if time.monotonic() > deadline:
                    raise TimeoutError('whole benchmark time budget')
                done, _ = wait(pending, timeout=min(spec.progress_seconds, max(0, deadline-time.monotonic())), return_when=FIRST_COMPLETED)
                for future in done:
                    code = pending.pop(future)
                    result = future.result()
                    save(output/f'{code}.json', result)
                    # Read back each persisted receipt before admitting another job.
                    if json.loads((output/f'{code}.json').read_text()) != result:
                        raise ValueError('receipt readback mismatch')
                    peaks[result['pid']] = max(peaks.get(result['pid'], 0), result['rss_peak_bytes'])
                    results.append(result)
                    if rss_bytes()+sum(peaks.values()) > spec.total_rss_bytes:
                        raise MemoryError('combined peak RSS budget')
                print(f'workers={workers}: {len(results)}/{len(jobs)} stocks complete; active={list(pending.values())}', flush=True)
                for _ in done:
                    dispatch()
        except BaseException:
            cancel.set()
            for future in pending:
                future.cancel()
            raise
    return dict(workers=workers, seconds=time.monotonic()-started,
                stocks=len(results), seats=sum(len(r['units']) for r in results),
                engine_calls=sum(len(r['engine_calls']) for r in results),
                events=sum(u['events'] for r in results for u in r['units']),
                observation_buys=sum(u['observation_buys'] for r in results for u in r['units']),
                conservative_rss_peak_bytes=rss_bytes()+sum(peaks.values()),
                all_equal=all(all(u['exact_equal'].values()) for r in results for u in r['units']))


def execute(output, spec=SPEC):
    if spec != SPEC:
        raise ValueError('unapproved performance specification')
    output = safe_output(output)
    started = time.monotonic()
    jobs, source, baseline, frozen = prepare(spec)
    codes = benchmark_hashes()
    output.mkdir(parents=True, exist_ok=False)
    metadata = dict(spec=asdict(spec), source=source, code_sha256=codes,
                    created_at_utc=datetime.now(timezone.utc).isoformat(),
                    python=platform.python_version(), platform=platform.platform(),
                    plan_sha256=digest(PLAN.read_bytes()), baseline_manifest=spec.manifest)
    save(output/'preflight.json', dict(jobs=jobs, baseline=baseline, reference_sha256=frozen))
    phases = []
    try:
        for workers in spec.worker_counts:
            phase = run_phase(jobs, workers, source, started+spec.total_seconds, output/f'workers_{workers}', spec)
            phases.append(phase)
            save(output/f'phase_{workers}.json', phase)
        assert_unchanged(frozen)
        if benchmark_hashes() != codes:
            raise ValueError('benchmark code changed during run')
        if time.monotonic()-started > spec.total_seconds:
            raise TimeoutError('whole benchmark time budget')
        metadata.update(status='equivalent', phases=phases, seconds=time.monotonic()-started,
                        reference_unchanged=True, code_unchanged=True, lake_reads=0)
    except BaseException as exc:
        metadata.update(status='failed', error=f'{type(exc).__name__}: {exc}', phases=phases,
                        seconds=time.monotonic()-started)
        save(output/'failure.json', metadata)
        raise
    paths = sorted(p for p in output.rglob('*') if p.is_file())
    if sum(p.stat().st_size for p in paths) > spec.max_bytes:
        raise ValueError('benchmark output budget')
    metadata['artifacts_sha256'] = {str(p.relative_to(output)): digest(p.read_bytes()) for p in paths}
    save(output/'manifest.json', metadata)
    print(json.dumps(metadata['phases'], indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    execute(args.output)


if __name__ == '__main__':
    main()
