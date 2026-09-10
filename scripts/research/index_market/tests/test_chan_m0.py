from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.research.index_market.chan.event_ledger import EventLedger, canonical, groups
from scripts.research.index_market.chan.m0_data import SPEC, safe_output, validate
from scripts.research.index_market.chan.run_m0 import audit_saved, expanded, verify_source


def point(**changes):
    return dict(dict(buy=True, types=['3a'], sure=False, bi_index=1,
                     start_date='2010-01-04', start_index=0,
                     anchor_date='2010-01-05', anchor_index=1,
                     end_date='2010-01-05', end_index=1), **changes)


def test_first_sure_not_anchor_and_no_repeated_trigger():
    ledger = EventLedger('000300.SH')
    assert ledger.step('2010-01-05', 1, [point()])[1] == []
    event = ledger.step('2010-01-06', 2, [point(sure=True)])[1][0]
    assert (event['signal_date'], event['anchor_date'], event['lag_bars']) == ('2010-01-06', '2010-01-05', 1)
    assert not event['evaluation']
    assert ledger.step('2011-01-04', 250, [point(sure=True)])[1] == []


def test_types_are_exact_b3_union_and_new_group_can_trigger():
    assert groups(['1p', '2s'], True) == []
    assert groups(['1', '2', '3a', '3b'], False) == ['S1', 'S2', 'S3']
    ledger = EventLedger('000300.SH')
    first = ledger.step('2011-01-04', 250, [point(sure=True, types=['3a', '3b'])])[1]
    assert len(first) == 1 and first[0]['group'] == 'B3'
    later = ledger.step('2011-01-05', 251, [point(sure=True, types=['2', '3b'])])[1]
    assert len(later) == 1 and later[0]['group'] == 'B2'


def test_retraction_reappearance_extension_do_not_delete_or_retrigger():
    ledger = EventLedger('000300.SH')
    event = ledger.step('2011-01-04', 250, [point(sure=True)])[1][0]
    frozen = deepcopy(event)
    change = ledger.step('2011-01-05', 251, [])[0][0]
    assert change['change'] == 'disappeared'
    changes, events, _ = ledger.step('2011-01-06', 252, [point(sure=True, types=['3b'])])
    assert changes[0]['change'] == 'reappeared' and not events
    changes, events, _ = ledger.step('2011-01-07', 253, [point(sure=True, types=['3b'],
        anchor_date='2011-01-05', anchor_index=251, end_date='2011-01-05', end_index=251)])
    assert changes[0]['change'] == 'updated' and not events
    assert event == frozen


def test_new_start_is_new_candidate_with_observed_link():
    ledger = EventLedger('000300.SH')
    first = ledger.step('2011-01-04', 250, [point(sure=True)])[1][0]
    changes, events, _ = ledger.step('2011-01-05', 251, [point(sure=True,
        start_date='2010-01-05', start_index=1)])
    assert len(events) == 1 and events[0]['event_id'] != first['event_id']
    assert any(c['same_index_previous_candidate'] == first['candidate_id'] for c in changes)


@pytest.mark.parametrize('bad', [point(types=['31']), point(sure=None), point(buy=1),
                                point(anchor_date='2030-01-01'), point(end_date='2030-01-01')])
def test_invalid_point_rejected(bad):
    with pytest.raises(ValueError):
        EventLedger('000300.SH').step('2011-01-04', 250, [bad])


def test_order_identity_and_budgets_rejected():
    with pytest.raises(ValueError, match='ambiguous'):
        EventLedger('000300.SH').step('2011-01-04', 250, [point(), point()])
    ledger = EventLedger('000300.SH', replace(SPEC, max_points=0))
    with pytest.raises(ValueError, match='budget'):
        ledger.step('2011-01-04', 250, [point()])
    ledger = EventLedger('000300.SH')
    assert ledger.step('2011-01-04', 250, [])[1] == []
    with pytest.raises(ValueError, match='increasing'):
        ledger.step('2011-01-04', 250, [])
    with pytest.raises(ValueError):
        EventLedger('600000.SH')


def test_change_journal_can_rebuild_all_days_and_first_events(tmp_path):
    ledger = EventLedger('000300.SH')
    all_changes, all_events, all_days = [], [], []
    frames = [[], [point()], [point(sure=True)], [], [point(sure=True, types=['3b'])]]
    for i, points in enumerate(frames):
        changes, events, daily = ledger.step(f'2011-01-0{i+4}', 250+i, points)
        all_changes.extend(changes)
        all_events.extend(events)
        all_days.append(daily)
    for name, values in [('changes', all_changes), ('events', all_events), ('daily', all_days)]:
        (tmp_path / f'{name}.jsonl').write_text(''.join(canonical(v)+'\n' for v in values))
    assert audit_saved(tmp_path)['events'] == 1
    (tmp_path / 'events.jsonl').write_text('')
    with pytest.raises(ValueError, match='reconstruction'):
        audit_saved(tmp_path)


def inputs():
    spec = replace(SPEC, codes=('000300.SH',), start='2010-01-04', end='2010-01-06',
                   evaluation_start='2010-01-05')
    calendar = [dict(date=f'2010-01-0{i}', is_open=i != 6) for i in (4, 5, 6)]
    rows = [dict(ts_code='000300.SH', date=d, partition_date=d,
                 open=10., high=12., low=9., close=11.) for d in ('2010-01-04', '2010-01-05')]
    return spec, calendar, rows


def test_input_grain_calendar_and_scope():
    spec, calendar, rows = inputs()
    assert validate(rows, calendar, spec)['open_days'] == 2
    with pytest.raises(ValueError, match='coverage'):
        validate(rows[:1], calendar, spec)
    with pytest.raises(ValueError, match='duplicate'):
        validate(rows+rows[:1], calendar, spec)
    with pytest.raises(ValueError, match='calendar'):
        validate(rows, calendar[:-1], spec)
    with pytest.raises(ValueError, match='calendar'):
        validate(rows, calendar+calendar[:1], spec)


@pytest.mark.parametrize(('field', 'value'), [('open', None), ('close', float('nan')),
    ('low', 0), ('high', 8), ('partition_date', '2010-01-05'),
    ('date', '2010-01-06'), ('ts_code', '000001.SH')])
def test_input_invalid_values_rejected(field, value):
    spec, calendar, rows = inputs()
    rows[0][field] = value
    with pytest.raises(ValueError):
        validate(rows, calendar, spec)


def test_output_source_and_spec_boundaries(monkeypatch, tmp_path):
    import scripts.research.index_market.chan.m0_data as data
    monkeypatch.setattr(data, 'REPO', tmp_path)
    reports = tmp_path / 'reports'
    reports.mkdir()
    assert safe_output(reports / 'new') == reports / 'new'
    for path in (reports, tmp_path, Path('/Volumes/datasource/data_lake')):
        with pytest.raises(ValueError):
            safe_output(path)
    with pytest.raises(ValueError):
        replace(SPEC, evaluation_start=SPEC.start)
    monkeypatch.setattr(subprocess, 'check_output', lambda *a, **k: 'wrong')
    with pytest.raises(ValueError, match='commit'):
        verify_source(tmp_path)


def test_help_does_not_need_third_party_or_lake():
    result = subprocess.run([sys.executable, '-B', '-m',
        'scripts.research.index_market.chan.run_m0', '--help'], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0 and '--output' in result.stdout


def test_expanded_config_is_json_serializable():
    from enum import Enum
    class Direction(Enum):
        UP = 'up'
    assert json.loads(json.dumps(expanded(dict(a=[Direction.UP])))) == {'a': ['up']}


def test_real_duckdb_loader_on_isolated_parquet(tmp_path, monkeypatch):
    import duckdb
    import scripts.research.index_market.chan.m0_data as data

    spec, _, _ = inputs()
    calendar = tmp_path / 'silver/calendar/trade_calendar/full/part-000.parquet'
    calendar.parent.mkdir(parents=True)
    with duckdb.connect(':memory:') as con:
        con.execute('''COPY (SELECT 'SSE' AS exchange, CAST(d AS DATE) AS trade_date,
            d != DATE '2010-01-06' AS is_open FROM generate_series(
            DATE '2010-01-04', DATE '2010-01-06', INTERVAL 1 DAY) t(d)) TO ? (FORMAT PARQUET)''', [str(calendar)])
        for day in ('2010-01-04', '2010-01-05'):
            path = tmp_path / f'silver/index_daily/trade_date={day}/part-000.parquet'
            path.parent.mkdir(parents=True)
            con.execute('''COPY (SELECT code AS ts_code, CAST($1 AS DATE) AS trade_date,
                10.0::DOUBLE AS open, 12.0::DOUBLE AS high, 9.0::DOUBLE AS low, 11.0::DOUBLE AS close
                FROM (VALUES ('000300.SH'), ('600000.SH')) t(code)) TO $2 (FORMAT PARQUET)''', [day, str(path)])
    monkeypatch.setattr(data, 'LAKE', tmp_path)
    rows, calendar_rows, files, quality = data.load_input(spec)
    assert len(rows) == 2 and len(calendar_rows) == 3 and len(files) == 3
    assert {r['ts_code'] for r in rows} == {'000300.SH'}
    assert quality['parquet_scan_queries'] == 2
    with pytest.raises(ValueError, match='byte budget'):
        data.load_input(replace(spec, max_bytes=1))
    with pytest.raises(ValueError, match='file count'):
        data.load_input(replace(spec, max_files=1))
    with pytest.raises(ValueError, match='row budget'):
        data.load_input(replace(spec, max_rows=1))
    with pytest.raises(ValueError, match='row budget'):
        data.load_input(replace(spec, max_calendar_rows=1))


def test_new_modules_have_no_network_production_or_installer_imports():
    import ast
    root = Path(__file__).resolve().parents[1] / 'chan'
    forbidden = ('src', 'qtf', 'orchestrator', 'requests', 'httpx', 'tushare', 'pip')
    for name in ('m0_data.py', 'event_ledger.py', 'run_m0.py', 'verify_m0.py'):
        tree = ast.parse((root / name).read_text())
        for node in ast.walk(tree):
            imports = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ''] if isinstance(node, ast.ImportFrom) else [])
            assert not any(m == p or m.startswith(p+'.') for m in imports for p in forbidden)
