from dataclasses import asdict, replace
import json

import duckdb
import pytest

from scripts.research.index_market.chan import stock_chan_batch as runner
from scripts.research.index_market.chan import stock_chan_batch_data as data
from scripts.research.index_market.chan.m0_data import digest
from scripts.research.index_market.chan.run_m0 import save
from scripts.research.index_market.chan.stock_chan_replay_data import Reader


def test_gap_classification_only_excuses_final_full_days():
    gaps = [dict(code='x', trade_date=f'2026-01-{i:02}', missing_bars=8 if i != 5 else 4) for i in range(1,7)]
    facts = [dict(ts_code='x', trade_date='2026-01-01', suspend_type='S', suspend_timing=None),
             dict(ts_code='x', trade_date='2026-01-02', suspend_type='S', suspend_timing='09:30-10:00'),
             dict(ts_code='x', trade_date='2026-01-03', suspend_type='S', suspend_timing=None),
             dict(ts_code='x', trade_date='2026-01-03', suspend_type='R', suspend_timing=None),
             dict(ts_code='x', trade_date='2026-01-05', suspend_type='S', suspend_timing=None),
             dict(ts_code='y', trade_date='2026-01-06', suspend_type='S', suspend_timing=None)]
    actual = data.classify_gaps(gaps, facts, 'x')
    assert [r['reason'] for r in actual] == ['confirmed_full_day_suspension',
        'non_full_day_or_conflicting_suspension', 'non_full_day_or_conflicting_suspension',
        'no_final_suspension_fact', 'partial_missing_bars', 'no_final_suspension_fact']


def test_fixed_selection_keeps_repeated_seats():
    seats = [dict(code=str(i), window_id='first') for i in range(12)]
    seats.append(dict(code='1', window_id='second'))
    codes = [str(i) for i in range(12)]
    selected, actual = data.select_batch(seats, codes)
    assert selected == codes[:10] and len(actual) == 11


def test_changed_spec_refused_before_any_io(tmp_path):
    for spec in (replace(data.SPEC, batch_size=11), replace(data.SPEC, batch_index=1),
                 replace(data.SPEC, history_days=5), replace(data.SPEC, max_files=3000)):
        with pytest.raises(ValueError, match='unapproved'):
            runner.execute(tmp_path/'out', spec=spec)


def test_whole_sql_preflight_and_suspension_vs_history(tmp_path, monkeypatch):
    from scripts.research.index_market.chan import stock_chan_replay_data as pilot_data
    monkeypatch.setattr(data, 'LAKE', tmp_path)
    monkeypatch.setattr(pilot_data, 'LAKE', tmp_path)
    spec = replace(data.SPEC, start='2026-02-25', end='2026-02-27', batch_size=1, history_days=1)
    code = '000002.SZ'
    with duckdb.connect(':memory:') as c:
        def parquet(relative, sql):
            path = tmp_path/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            c.execute(f'COPY ({sql}) TO ? (FORMAT PARQUET)', [str(path)])
        parquet('silver/basic/stock_lifecycle/full/part-000.parquet', """SELECT '000002.SZ' AS ts_code,
            'fixture' AS name,'SZSE' AS exchange,true AS is_cny_stock,DATE '1991-01-01' AS list_date,NULL::DATE AS delist_date""")
        parquet('silver/calendar/trade_calendar/full/part-000.parquet', """SELECT 'SSE' AS exchange,
            d::DATE AS trade_date,true AS is_open FROM generate_series(DATE '2026-02-25',DATE '2026-02-27',INTERVAL 1 DAY) t(d)""")
        c.execute("""CREATE TABLE prices AS SELECT '000002.SZ' AS ts_code,30 AS freq,'SZSE' AS exchange,
            d::DATE AS trade_date,CAST(CAST(d::DATE AS VARCHAR)||' '||s AS TIMESTAMP) AS trade_time,
            10.0::DOUBLE AS open,12.0::DOUBLE AS high,9.0::DOUBLE AS low,11.0::DOUBLE AS close,
            10.0::DOUBLE AS vol,100.0::DOUBLE AS amount
            FROM generate_series(DATE '2026-02-25',DATE '2026-02-27',INTERVAL 1 DAY) t(d)
            CROSS JOIN (SELECT unnest(?) AS s) slots WHERE d<>DATE '2026-02-26'""", [list(data.slots(30))])
        parquet('gold/quote/stk_mins_qfq/freq=30/ts_code=000002.SZ/year=2026/part-000.parquet', 'SELECT * FROM prices')
        parquet('silver/quote/stock_suspend_daily/trade_date=2026-02-26/part-000.parquet', """SELECT '000002.SZ' AS ts_code,
            DATE '2026-02-26' AS trade_date,'S' AS suspend_type,NULL::VARCHAR AS suspend_timing""")
        for d in ('2026-02-25', '2026-02-27'):
            parquet(f'silver/quote/stk_mins/freq=5/trade_date={d}/part-000.parquet', f"SELECT * REPLACE(5 AS freq) FROM prices WHERE trade_date=DATE '{d}'")
            parquet(f'silver/quote/adj_factor/trade_date={d}/part-000.parquet', f"SELECT '000002.SZ' AS ts_code,DATE '{d}' AS trade_date,3.0::DOUBLE AS adj_factor")
    seat = dict(code=code, window_id='2026-02-27', group='control')
    window = dict(window_id='2026-02-27', exit_bar_end='2026-02-27 15:00:00', prior_days=['2026-02-27'])
    batch = data.load_batch(Reader(spec), [window], [seat], [code], spec)
    rows, quality = data.seat_input(batch, seat, window, spec)
    assert len(rows) == 16 and quality['status'] == 'ready'
    assert quality['quality']['history_days_before_observation'] == 1
    assert quality['gaps'][0]['reason'] == 'confirmed_full_day_suspension'
    _, short = data.seat_input(batch, seat, window, replace(spec, history_days=2))
    assert short['status'] == 'insufficient_history'  # Neither suspended nor future days count.
    batch['suspension'] = []
    _, blocked = data.seat_input(batch, seat, window, spec)
    assert blocked['status'] == 'data_blocked'


def checkpoint_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'REPO', tmp_path)
    folder = tmp_path/'reports'/'fixture'/'units'/'x'
    folder.mkdir(parents=True)
    seat = dict(code='000002.SZ', window_id='2026-02-26', group='control')
    rows, sources, codes = [dict(value=1)], {'source':'hash'}, {'code.py':'hash'}
    save(folder/'input.json', rows)
    metadata = dict(unit_id='000002.SZ/2026-02-26', seat=seat, status='complete', seconds=1,
                    spec_fingerprint=runner.fingerprint(asdict(data.SPEC)), code_sha256=codes,
                    source_fingerprint=runner.fingerprint(sources), input_fingerprint=runner.fingerprint(rows))
    ref = runner.seal(folder, metadata)
    return folder, seat, rows, sources, codes, ref


def test_seal_resume_readback_idempotence_and_tamper(tmp_path, monkeypatch):
    folder, seat, rows, sources, codes, ref = checkpoint_fixture(tmp_path, monkeypatch)
    original = (folder/'manifest.json').read_bytes()
    for _ in range(2):
        assert runner.verify_unit(ref, seat, rows, runner.fingerprint(sources), codes)['status'] == 'complete'
    assert (folder/'manifest.json').read_bytes() == original
    with pytest.raises(ValueError, match='already sealed'):
        runner.seal(folder, {})
    with pytest.raises(ValueError, match='identity mismatch'):
        runner.verify_unit(ref, seat, [dict(value=2)], runner.fingerprint(sources), codes)
    (folder/'input.json').write_text('[2]')
    with pytest.raises(ValueError, match='artifact changed'):
        runner.verify_unit(ref, seat, rows, runner.fingerprint(sources), codes)


def test_resume_rejects_changed_source_and_keeps_half_written_unit_unsealed(tmp_path, monkeypatch):
    folder, seat, rows, sources, codes, ref = checkpoint_fixture(tmp_path, monkeypatch)
    root = tmp_path/'reports'/'fixture'
    save(root/'source_hashes.json', sources)
    half = root/'units'/'unfinished'
    half.mkdir()
    save(half/'input.json', [1])
    manifest = dict(spec=asdict(data.SPEC), code_sha256=codes, units=[ref], cumulative_seconds=5,
                    artifacts_sha256={'source_hashes.json': digest((root/'source_hashes.json').read_bytes())})
    save(root/'manifest.json', manifest)
    refs, seconds = runner.resume_state(root, codes, sources)
    assert list(refs) == [ref['unit_id']] and seconds == 5
    assert not (half/'manifest.json').exists()
    with pytest.raises(ValueError, match='source snapshot changed'):
        runner.resume_state(root, codes, {'source':'changed'})
    with pytest.raises(ValueError, match='spec/code changed'):
        runner.resume_state(root, {'code.py':'changed'}, sources)
    assert json.loads((folder/'input.json').read_text()) == rows
