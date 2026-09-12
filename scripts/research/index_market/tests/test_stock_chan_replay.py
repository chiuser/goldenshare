from copy import deepcopy
from dataclasses import asdict, replace
import json

import duckdb
import pytest

from scripts.research.index_market.chan.m0_data import REPO, digest
from scripts.research.index_market.chan.minute_data import slots
from scripts.research.index_market.chan.minute_variant_a import VARIANT_A
from scripts.research.index_market.chan.run_m0 import save
from scripts.research.index_market.chan.stock_chan_replay import (
    adapter, authenticated_manifest, diagnose_window, event_signature, execute, freeze_samples,
)
from scripts.research.index_market.chan.stock_chan_replay_data import (
    SPEC, Reader, load_pilot, validate_basis, validate_lifecycle, validate_rows,
)
from scripts.research.index_market.chan.stock_chan_replay_audit import reconstruct


def prices(days=('2026-02-25', '2026-02-26')):
    return [dict(code='000002.SZ', frequency=30, exchange='SZSE', date=d, time=f'{d} {s}',
                 open=10., high=12., low=9., close=11., vol=10., amount=100.) for d in days for s in slots(30)]


def test_frozen_actual_seats_and_deterministic_pilot():
    folder = REPO/SPEC.rank_report
    manifest = authenticated_manifest(folder, SPEC.rank_manifest)
    windows, seats, codes, unmatched = freeze_samples(folder, manifest)
    assert len(windows) == 3 and len(seats) == 298 and len(codes) == 289
    assert codes[0] == '000002.SZ'
    assert [s for s in seats if s['code'] == codes[0]] == [
        dict(window_id='2026-02-26', code='000002.SZ', group='control')]
    assert {p['winner'] for p in unmatched} == {'603459.SH', '688813.SH'}


def test_artifact_hash_and_manifest_tamper_rejected(tmp_path):
    save(tmp_path/'data.json', [1])
    save(tmp_path/'manifest.json', dict(artifacts_sha256={'data.json': digest((tmp_path/'data.json').read_bytes())}))
    expected = digest((tmp_path/'manifest.json').read_bytes())
    authenticated_manifest(tmp_path, expected)
    (tmp_path/'data.json').write_text('[2]')
    with pytest.raises(ValueError, match='artifact changed'):
        authenticated_manifest(tmp_path, expected)
    with pytest.raises(ValueError, match='manifest changed'):
        authenticated_manifest(tmp_path, '0'*64)


def test_scope_and_algorithm_preserved(tmp_path):
    actual = adapter('000002.SZ', 25)
    assert actual.chan_config() == VARIANT_A.chan_config()
    assert {k for k, v in asdict(actual).items() if v != asdict(VARIANT_A)[k]} == {
        'codes', 'frequencies', 'replay_seconds'}
    for spec in (replace(SPEC, start='2020-01-01'), replace(SPEC, frequency=60),
                 replace(SPEC, history_days=10), replace(SPEC, universe_asof='2026-02-26')):
        with pytest.raises(ValueError, match='unapproved'):
            execute(tmp_path/'out', spec)


def test_selected_identity_survivor_boundaries():
    seats = [dict(code='000002.SZ', window_id='2026-02-26')]
    row = dict(ts_code='000002.SZ', exchange='SZSE', is_cny_stock=True,
               list_date='1991-01-01', delist_date=None)
    assert validate_lifecycle(seats, [row])
    for changes in (dict(delist_date='2026-09-12'), dict(delist_date='2026-06-01'),
                    dict(exchange='BSE'), dict(exchange='SSE'), dict(is_cny_stock=False),
                    dict(list_date='2026-02-27')):
        with pytest.raises(ValueError, match='out-of-scope'):
            validate_lifecycle(seats, [dict(row, **changes)])
    assert validate_lifecycle(seats, [dict(row, delist_date='2026-09-13')])
    with pytest.raises(ValueError, match='identities'):
        validate_lifecycle(seats, [row, row])


def validate_small(rows):
    return validate_rows(rows, ['2026-02-25', '2026-02-26'], '000002.SZ', '1991-01-01',
                         '2026-02-26 15:00:00', '2026-02-26', replace(SPEC, history_days=1))


def test_exact_grid_and_prior_history_gate():
    rows = prices()
    assert validate_small(rows)['history_days_before_observation'] == 1
    with pytest.raises(ValueError, match='insufficient structure history'):
        validate_rows(rows, ['2026-02-25', '2026-02-26'], '000002.SZ', '1991-01-01',
                      '2026-02-26 15:00:00', '2026-02-26')
    with pytest.raises(ValueError, match='minute grid'):
        validate_small(rows[1:])
    with pytest.raises(ValueError, match='duplicate'):
        validate_small(rows+[rows[-1]])
    with pytest.raises(ValueError, match='minute grid'):
        validate_small(rows[8:])  # Entire missing days must not disappear from denominator.


@pytest.mark.parametrize('change', [dict(low=0), dict(high=9), dict(close=float('nan')),
                                    dict(vol=0), dict(amount=-1), dict(code='920001.BJ'),
                                    dict(frequency=60), dict(exchange='SSE')])
def test_invalid_rows_rejected(change):
    rows = prices()
    rows[0].update(change)
    with pytest.raises(ValueError, match='invalid price'):
        validate_small(rows)


def test_basis_is_shared_positive_and_uses_close():
    anchors = {'2021-01-01 10:00:00': 5., '2026-01-01 15:00:00': 8.}
    raw = [dict(time=t, raw_close=v*2, adj_factor=3.) for t, v in anchors.items()]
    assert validate_basis(anchors, raw)['anchors'][0]['implied_base'] == 6
    bad = deepcopy(raw)
    bad[-1]['adj_factor'] = 4
    with pytest.raises(ValueError, match='inconsistent'):
        validate_basis(anchors, bad)
    with pytest.raises(ValueError, match='missing or duplicate'):
        validate_basis(anchors, raw[:-1])
    with pytest.raises(ValueError, match='missing or duplicate'):
        validate_basis(anchors, [raw[0], raw[0]])


def window_fixture():
    rows = prices(('2026-02-26',))[:5]
    rows[-1].update(open=11, high=1000, low=0.01)
    w = dict(signal_time='2026-02-26 10:00:00', start='2026-02-26 10:00:00',
             end='2026-02-26 13:00:00', entry_bar_end='2026-02-26 10:30:00',
             exit_bar_end='2026-02-26 13:30:00', prior_days=['2026-02-25'])
    return rows, w


def test_action_time_compounding_and_exit_bar_leakage():
    rows, w = window_fixture()
    events = [dict(group='B3', signal_time='2026-02-26 10:00:00')]
    result = diagnose_window(rows, events, w, ['2026-02-25', '2026-02-26'])
    item = result['first_by_group']['B3']
    assert item['action_time'] == '2026-02-26 10:00:00'
    assert item['relative_market_bars'] == 0
    assert item['mfe'] == pytest.approx(.2) and item['mae'] == pytest.approx(-.1)
    assert (1+item['elapsed_change'])*(1+item['remaining_change'])-1 == pytest.approx(result['interval_change'])
    rows[-1]['open'] = 15  # Exit gap is included; exit bar's subsequent high/low is not.
    result = diagnose_window(rows, events, w, ['2026-02-25', '2026-02-26'])
    assert result['interval_mfe'] == pytest.approx(.5)


def test_lunch_late_signal_and_sell_not_a_buy():
    rows, w = window_fixture()
    events = [dict(group='B1', signal_time='2026-02-26 11:30:00'),
              dict(group='S1', signal_time='2026-02-26 11:00:00')]
    result = diagnose_window(rows, events, w, ['2026-02-26'])
    assert result['observation_buy_count'] == 1
    item = result['first_by_group']['B1']
    assert not item['actionable'] and item['action_time'] == '2026-02-26 13:00:00'
    assert 'remaining_change' not in item


def test_signatures_ignore_only_shifted_indexes_not_confirmation():
    event = dict(signal_time='2026-02-26 11:30:00', anchor_time='2026-02-26 10:00:00',
                 signal_index=10, group='B3', event_id='fixed', lag_bars=3)
    shifted = dict(event, signal_index=8)
    assert event_signature([event]) == event_signature([shifted])
    assert event_signature([event], end='2026-02-26 11:00:00') == []
    assert event_signature([event]) != event_signature([dict(shifted, signal_time='2026-02-26 14:00:00')])


def test_reader_rejects_non_lake_before_query(tmp_path):
    path = tmp_path/'data.parquet'
    path.write_bytes(b'invalid')
    with pytest.raises(ValueError, match='Lake path'):
        Reader().read([path], 'SELECT 1', [], 1)


def test_frozen_g1_spec_mismatch():
    folder = REPO/SPEC.rank_report
    manifest = json.loads((folder/'manifest.json').read_text())
    manifest['spec']['frequency'] = 60
    with pytest.raises(ValueError, match='different scope'):
        freeze_samples(folder, manifest)


def test_real_sql_pipeline_uses_canonical_sse_calendar_for_sz_stock(tmp_path, monkeypatch):
    # Synthetic Parquet only: exercise the exact loader SQL, not the production Lake.
    from scripts.research.index_market.chan import stock_chan_replay_data as data
    monkeypatch.setattr(data, 'LAKE', tmp_path)
    spec = replace(SPEC, start='2026-02-25', history_days=1)
    with duckdb.connect(':memory:') as c:
        def parquet(relative, sql):
            path = tmp_path/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            c.execute(f'COPY ({sql}) TO ? (FORMAT PARQUET)', [str(path)])

        parquet('silver/basic/stock_lifecycle/full/part-000.parquet', """SELECT
            '000002.SZ' AS ts_code,'fixture' AS name,'SZSE' AS exchange,true AS is_cny_stock,
            DATE '1991-01-01' list_date,NULL::DATE delist_date""")
        parquet('silver/calendar/trade_calendar/full/part-000.parquet', """SELECT 'SSE' exchange,
            d::DATE trade_date,true is_open FROM generate_series(DATE '2026-02-25', DATE '2026-02-26', INTERVAL 1 DAY) t(d)""")
        c.execute('CREATE TABLE prices(ts_code VARCHAR,freq INT,exchange VARCHAR,trade_date DATE,trade_time TIMESTAMP,open DOUBLE,high DOUBLE,low DOUBLE,close DOUBLE,vol DOUBLE,amount DOUBLE)')
        c.executemany('INSERT INTO prices VALUES (?,?,?,?,?,?,?,?,?,?,?)', [
            [r['code'],r['frequency'],r['exchange'],r['date'],r['time'],r['open'],r['high'],r['low'],r['close'],r['vol'],r['amount']]
            for r in prices()])
        parquet('gold/quote/stk_mins_qfq/freq=30/ts_code=000002.SZ/year=2026/part-000.parquet', 'SELECT * FROM prices')
        for d in ('2026-02-25', '2026-02-26'):
            parquet(f'silver/quote/stk_mins/freq=5/trade_date={d}/part-000.parquet',
                    f"SELECT * REPLACE(5 AS freq) FROM prices WHERE trade_date=DATE '{d}'")
            parquet(f'silver/quote/adj_factor/trade_date={d}/part-000.parquet',
                    f"SELECT '000002.SZ' ts_code,DATE '{d}' trade_date,3.0 adj_factor")
    reader = Reader(spec)
    rows, days, _, quality, basis = load_pilot(reader,
        [dict(code='000002.SZ', window_id='2026-02-26')], '000002.SZ',
        dict(exit_bar_end='2026-02-26 15:00:00', prior_days=['2026-02-26']))
    assert len(rows) == 16 and len(days) == 2 and quality['missing_bars'] == 0
    assert basis['anchors'][0]['implied_base'] == 3
    assert reader.verify_unchanged()['source_hashes_unchanged']


def test_reconstruction_uses_first_sure_time_and_never_retriggers():
    point = dict(sure=False, buy=True, types=['1p', '2s', '3a'], anchor_index=0,
                 anchor_time='2026-01-01 10:00:00')
    sure = dict(point, sure=True)
    changes = [dict(candidate_id='candidate', time='2026-01-01 10:00:00', index=0, before=None, after=point),
               dict(candidate_id='candidate', time='2026-01-01 10:30:00', index=1, before=point, after=sure),
               dict(candidate_id='candidate', time='2026-01-01 11:00:00', index=2, before=sure, after=None),
               dict(candidate_id='candidate', time='2026-01-01 11:30:00', index=3, before=None, after=sure)]
    assert reconstruct(changes) == [('candidate|B3', '2026-01-01 10:30:00', 1, 0, '2026-01-01 10:00:00')]
    changes[-1]['before'] = point
    with pytest.raises(ValueError, match='before-state'):
        reconstruct(changes)
