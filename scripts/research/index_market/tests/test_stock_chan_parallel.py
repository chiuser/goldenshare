"""Synthetic-only checks for exact reuse and bounded performance orchestration."""
from copy import deepcopy
from dataclasses import replace
import json
import threading
import time

import pytest

from scripts.research.index_market.chan import stock_chan_parallel as runner
from scripts.research.index_market.chan import stock_chan_shared_replay as shared
from scripts.research.index_market.chan.stock_chan_batch import fingerprint


def fake_replay(name, rows, keep):
    events = [dict(group='B3', event_id=r['time'], signal_time=r['time'], signal_index=i)
              for i, r in enumerate(rows)]
    changes = [dict(time=r['time'], index=i) for i, r in enumerate(rows)] if keep else []
    return events, changes


def fake_diagnose(rows, events, window, days):
    return dict(observation_buy_count=len(events), times=[e['signal_time'] for e in events],
                exit_price=rows[-1]['open'])


@pytest.fixture
def sample(monkeypatch):
    monkeypatch.setattr(shared, 'diagnose_window', fake_diagnose)
    rows = [dict(code='000010.SZ', frequency=30, time=f'2026-01-0{i} 10:00:00', date=f'2026-01-0{i}',
                 open=10., high=11., low=9., close=10.) for i in range(1, 7)]
    seats = []
    for n in (4, 6):
        data = deepcopy(rows[:n])
        window = dict(signal_time=data[-3]['time'], prior_days=['2026-01-02'])
        history = data[:-1]
        mode_inputs = dict(full=history,
            prefix=[r for r in history if r['time'] <= window['signal_time']],
            future_perturbed=deepcopy(history), scaled=deepcopy(history),
            shorter_history=history[1:])
        for r in mode_inputs['future_perturbed']:
            if r['time'] > window['signal_time']:
                for k in ('open', 'high', 'low', 'close'):
                    r[k] *= 1.5
        for r in mode_inputs['scaled']:
            for k in ('open', 'high', 'low', 'close'):
                r[k] *= 2
        expected = {f'{k}_events': fake_replay(k, v, False)[0] for k, v in mode_inputs.items()}
        expected['changes'] = fake_replay('full', history, True)[1]
        expected['diagnostics'] = fake_diagnose(data, expected['full_events'], window, [])
        seats.append(dict(unit_id=str(n), rows=data, window=window,
                          expected={k: fingerprint(v) for k, v in expected.items()}))
    return seats, replace(shared.SPEC, history_days=1)


def test_multiwindow_reuse_keeps_independent_prefix_and_future(sample):
    seats, spec = sample
    calls = []

    def one(name, data, keep):
        calls.append((name, deepcopy(data)))
        return fake_replay(name, data, keep)

    result = shared.compute(seats, '000010.SZ', [], one, spec)
    assert len(calls) == 7  # 3 shared plus 2 independent checks per window, not 10.
    assert [len(data) for name, data in calls if name == 'prefix'] == [2, 4]
    futures = [data for name, data in calls if name == 'future_perturbed']
    assert [r['open'] for r in futures[0]] == [10, 10, 15]
    assert [r['open'] for r in futures[1]] == [10, 10, 10, 10, 15]
    assert all(all(r['exact_equal'].values()) and all(r['stability_checks'].values()) for r in result)
    assert [r['events'] for r in result] == [3, 5]


@pytest.mark.parametrize('field', ['open', 'code', 'frequency', 'time'])
def test_different_prefix_rejected(sample, field):
    seats, spec = sample
    seats[0]['rows'][0][field] = 'changed'
    with pytest.raises(ValueError, match='identical prefixes'):
        shared.shared_histories(seats, spec)


@pytest.mark.parametrize('name', ['full_events', 'prefix_events', 'future_perturbed_events',
                                 'scaled_events', 'shorter_history_events', 'changes', 'diagnostics'])
def test_any_output_difference_rejected(sample, name):
    seats, spec = sample
    seats[0]['expected'][name] = 'wrong'
    with pytest.raises(ValueError, match='non-equivalent'):
        shared.compute(seats, '000010.SZ', [], fake_replay, spec)


def test_index_difference_not_hidden_by_semantic_signature(sample):
    seats, spec = sample

    def shifted(name, data, keep):
        events, changes = fake_replay(name, data, keep)
        for event in events:
            event['signal_index'] += 1
        return events, changes

    with pytest.raises(ValueError, match='non-equivalent'):
        shared.compute(seats, '000010.SZ', [], shifted, spec)


def test_input_unchanged_and_last_exit_not_replayed(sample):
    seats, spec = sample
    seats[-1]['rows'][-1]['high'] = 1e12
    before = deepcopy(seats)

    def one(name, rows, keep):
        assert all(r['high'] < 1e12 for r in rows)
        return fake_replay(name, rows, keep)

    shared.compute(seats, '000010.SZ', [], one, spec)
    assert before == seats


@pytest.mark.parametrize('spec', [replace(shared.SPEC, max_bars=1), replace(shared.SPEC, history_days=100)])
def test_history_budgets(sample, spec):
    with pytest.raises(ValueError):
        shared.shared_histories(sample[0], spec)


def test_changed_input_rejected(tmp_path):
    path = tmp_path/'input.json'
    path.write_text('[]')
    assert shared.read_verified(path, shared.digest(path.read_bytes())) == []
    with pytest.raises(ValueError, match='frozen input changed'):
        shared.read_verified(path, 'bad')


def test_changed_spec_rejected_before_io(tmp_path):
    spec = replace(shared.SPEC, stocks=11)
    with pytest.raises(ValueError, match='specification'):
        runner.execute(tmp_path/'out', spec)
    with pytest.raises(ValueError, match='specification'):
        runner.prepare(spec)


@pytest.mark.parametrize('kind', ['cancel', 'timeout', 'memory'])
def test_worker_budget_and_cancellation(monkeypatch, kind):
    cancel = threading.Event()
    monkeypatch.setattr(shared, '_cancel', cancel)
    monkeypatch.setattr(shared, '_deadline', time.monotonic()+10)
    monkeypatch.setattr(shared, 'rss_bytes', lambda: 1)
    error = InterruptedError
    if kind == 'cancel':
        cancel.set()
    elif kind == 'timeout':
        monkeypatch.setattr(shared, '_deadline', time.monotonic()-1)
        error = TimeoutError
    else:
        monkeypatch.setattr(shared, 'rss_bytes', lambda: shared.SPEC.worker_rss_bytes+1)
        error = MemoryError
    with pytest.raises(error):
        shared.check_budget(time.monotonic())


@pytest.mark.parametrize('fail', [False, True])
def test_bounded_dispatch_receipts_and_failure_stop(monkeypatch, tmp_path, fail):
    submitted, cancelled, active = [], [], set()
    cancel = threading.Event()

    class Context:
        def Event(self):
            return cancel

    class Future:
        def __init__(self, job):
            self.job = job

        def result(self):
            active.remove(self)
            if fail:
                raise ValueError('synthetic failure')
            return dict(code=self.job['code'], pid=1, rss_peak_bytes=1,
                        engine_calls=[{}]*5, units=[dict(events=1, observation_buys=0, exact_equal={'a': True})])

        def cancel(self):
            cancelled.append(self)

    class Pool:
        def __init__(self, **kwargs):
            assert kwargs['max_workers'] == 2

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, worker, job):
            f = Future(job)
            submitted.append(job)
            active.add(f)
            assert len(active) <= 2
            return f

    monkeypatch.setattr(runner.multiprocessing, 'get_context', lambda name: Context())
    monkeypatch.setattr(runner, 'ProcessPoolExecutor', Pool)
    monkeypatch.setattr(runner, 'wait', lambda pending, **kw: ({next(iter(pending))}, None))
    jobs = [dict(code=str(i)) for i in range(10)]
    if fail:
        with pytest.raises(ValueError, match='synthetic failure'):
            runner.run_phase(jobs, 2, {}, time.monotonic()+10, tmp_path/'out')
        assert len(submitted) == 2 and cancel.is_set() and len(cancelled) == 1
    else:
        result = runner.run_phase(jobs, 2, {}, time.monotonic()+10, tmp_path/'out')
        assert result['stocks'] == 10 and len(submitted) == 10 and not cancel.is_set()
        assert len(list((tmp_path/'out').glob('*.json'))) == 10
        assert json.loads((tmp_path/'out'/'0.json').read_text())['code'] == '0'


def test_unsupported_parallelism_rejected(tmp_path):
    with pytest.raises(ValueError, match='worker/stock budget'):
        runner.run_phase([{}]*10, 8, {}, 0, tmp_path/'out')
