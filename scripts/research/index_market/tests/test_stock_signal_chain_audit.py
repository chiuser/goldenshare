"""Offline synthetic acceptance for the section-28 observer; no live engine/data."""
from dataclasses import replace
from types import SimpleNamespace
import json
import socket
from zipfile import ZipFile

import pytest

from scripts.research.index_market.chan import stock_signal_chain_audit as audit
from scripts.research.index_market.chan.minute_replay import MinuteLedger
from scripts.research.index_market.chan.minute_variant_a import VARIANT_A


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('network forbidden')
    monkeypatch.setattr(socket, 'create_connection', forbidden)


def test_selection_deterministic_and_missing_rejected():
    def item(code, category, day):
        return dict(code=code, category=category, signal_time=f'2025-01-{day:02d}', types=['B3'])
    first, second = audit.SPEC.codes
    expected = [item(first, audit.NO_SELL, 1), item(first, audit.NO_SELL, 2),
                item(first, 'nonmatching_only', 3), item(first, 'matched_sell_exit', 4),
                item(second, audit.NO_SELL, 1), item(second, audit.NO_SELL, 2)]
    opportunities = expected + [item(first, audit.NO_SELL, 5), item(second, audit.NO_SELL, 6)]
    assert audit.select_cases(opportunities) == expected
    assert audit.select_cases(list(reversed(opportunities))) == expected
    with pytest.raises(ValueError, match='category missing'):
        audit.select_cases([])


@pytest.mark.parametrize('field', ['group', 'signal_time', 'anchor_time', 'types', 'event_id'])
def test_event_field_mismatch_stops(field):
    old = [{field: 'old'}]
    with pytest.raises(ValueError, match='inconsistent:'):
        audit.equal([{field: 'changed'}], old, 'events')


def test_order_is_part_of_event_contract():
    with pytest.raises(ValueError):
        audit.equal([1, 2], [2, 1], 'order')


@pytest.mark.parametrize('types, expected', [(['1p'], []), (['2s'], []),
    (['1', '1p'], ['S1']), (['3a', '3b'], ['S3']), (['2', '2s'], ['S2'])])
def test_raw_type_mapping(types, expected):
    assert audit.groups(types, False) == expected


def fake_line():
    units = [SimpleNamespace(idx=i, low=1 if i < 2 else 2, high=3 if i < 2 else 4) for i in range(3)]
    cls = type('CBi', (), {})
    bi = cls()
    bi.begin_klc = SimpleNamespace(lst=units[:2], low=1, high=3)
    bi.end_klc = SimpleNamespace(lst=units[2:], low=2, high=4)
    bi.dir = SimpleNamespace(name='UP')
    bi.idx, bi.seg_idx, bi.is_sure = 4, 1, False
    return bi


def test_readonly_endpoints_use_last_peak_and_no_engine_cache():
    line = fake_line()
    before = dict(vars(line))
    facts = audit.Facts([{'time': f'2026-01-01 0{i}:00:00'} for i in range(3)])
    facts.now = 2
    ref = facts.line(line)
    assert facts.get(ref)['begin']['index'] == 1
    assert facts.get(ref)['end']['index'] == 2
    assert vars(line) == before
    assert '_memoize_cache' not in vars(line)
    line.is_sure = True
    assert facts.line(line) != ref  # state version, same stable structural identity


def test_future_reference_and_unknown_object_rejected():
    facts = audit.Facts([{'time': 'x'} for _ in range(3)])
    facts.now = 1
    with pytest.raises(ValueError, match='future'):
        facts.line(fake_line())
    with pytest.raises(TypeError, match='unsupported'):
        facts.value(object())


def test_prefix_facts_hash_identical_without_retaining_a_second_object_graph():
    rows = [{'time': str(i)} for i in range(3)]
    retained, streaming = audit.Facts(rows), audit.Facts(rows, retain=False)
    retained.now = streaming.now = 2
    assert retained.line(fake_line()) == streaming.line(fake_line())
    assert retained.objects and not streaming.objects


def test_executed_branch_catalog_does_not_evaluate_conditions(tmp_path):
    path = tmp_path/'source.py'
    path.write_text('def f(x):\n    if x.explode():\n        return\n    else:\n        return False\n')
    catalog = audit.branch_catalog(path)
    assert catalog[3]['guards'] == (('x.explode()', True),)
    assert catalog[5]['guards'] == (('x.explode()', False),)


def test_only_rejections_are_classified():
    p = dict(phase='line', function='treat_bsp1',
             location=dict(statement='is_target_bsp = False', guards=[['not is_diver', True]]))
    assert audit.is_rejection(p)
    assert not audit.is_rejection(dict(p, phase='return'))
    assert not audit.is_rejection(dict(p, location=dict(statement='return', guards=[])))


def test_ledger_disappearance_reappearance_and_type_change_do_not_backfill():
    spec = replace(VARIANT_A, codes=('000731.SZ',), frequencies=(60,))
    ledger = MinuteLedger('000731.SZ', 60, spec)
    p = dict(buy=False, sure=False, types=['1p'], bi_index=1,
             start_index=0, anchor_index=1, end_index=1, start_time='2023-01-01 10:30:00',
             anchor_time='2023-01-01 11:30:00', end_time='2023-01-01 11:30:00')
    assert not ledger.step('2023-01-01 14:00:00', 2, [p])[0]
    p = dict(p, sure=True)
    assert not ledger.step('2023-01-01 15:00:00', 3, [p])[0]
    p = dict(p, types=['1p', '1'])
    first, _ = ledger.step('2023-01-02 10:30:00', 4, [p])
    assert len(first) == 1 and first[0]['signal_index'] == 4
    assert ledger.step('2023-01-02 11:30:00', 5, [])[1][0]['after'] is None
    assert not ledger.step('2023-01-02 14:00:00', 6, [p])[0]


def test_other_stock_rejected_by_frozen_scope():
    with pytest.raises(ValueError, match='unapproved'):
        MinuteLedger('899050.BJ', 60, replace(VARIANT_A, codes=audit.SPEC.codes))


def test_checkpoint_preserves_completed_unit_and_rejects_overwrite(tmp_path):
    manifest = dict(completed_units=[])
    audit.checkpoint(tmp_path, '000731.SZ', {'proof': 1}, manifest)
    with ZipFile(tmp_path/'evidence.zip') as z:
        assert json.loads(z.read('000731.SZ.json')) == {'proof': 1}
    with pytest.raises(ValueError, match='overwrite'):
        audit.checkpoint(tmp_path, '000731.SZ', {'proof': 2}, manifest)
    with ZipFile(tmp_path/'evidence.zip') as z:
        assert json.loads(z.read('000731.SZ.json')) == {'proof': 1}
    assert json.loads((tmp_path/'manifest.json').read_text())['completed_units'] == ['000731.SZ']


def test_corrupt_archive_is_rejected(tmp_path):
    (tmp_path/'evidence.zip').write_bytes(b'not a zip')
    with pytest.raises(Exception):
        audit.checkpoint(tmp_path, 'x', {}, dict(completed_units=[]))


def test_pending_evidence_survives_without_claiming_validation(tmp_path):
    manifest = dict(completed_units=[])
    audit.checkpoint(tmp_path, '000731.SZ', {'objects': {'h': b'{"value":1}'}}, manifest, completed=False)
    assert manifest['completed_units'] == []
    assert manifest['observed_units'] == ['000731.SZ']
    with ZipFile(tmp_path/'evidence.zip') as z:
        assert json.loads(z.read('000731.SZ.json'))['objects']['h'] == {'value': 1}


@pytest.mark.parametrize('earlier_sure, expected', [(True, []), (False, ['000731.SZ|bi|sell|t0'])])
def test_outside_confirmation_is_first_sure_not_a_later_revision(earlier_sure, expected):
    rows = [{'time': f't{i}'} for i in range(4)]
    facts = audit.Facts(rows)
    key = '000731.SZ|bi|sell|t0'
    p = dict(sure=True, buy=False, types=['1p'], anchor={'time': 't1'})
    changes = [dict(index=3, level='bi', candidate_id=key, before=None, after=p)]
    if earlier_sure:
        changes.insert(0, dict(index=0, level='bi', candidate_id=key, before=None,
                              after=dict(p, anchor={'time': 't0'})))
    d = dict(code='000731.SZ', signal_time='t0', types=['B3'], entry_bar='t1', deadline='t2', category=audit.NO_SELL)
    observer = SimpleNamespace(facts=facts, rows=rows, changes=changes, diagnostics=[d], timeline=[],
                               coverage=[dict(index=1, calculations={})])
    assert audit.explain(observer, [])[0]['outside_confirmation'] == expected


def test_resource_limits(monkeypatch):
    monkeypatch.setattr(audit.time, 'monotonic', lambda: 300)
    monkeypatch.setattr(audit.resource, 'getrusage', lambda _: SimpleNamespace(ru_maxrss=1024))
    with pytest.raises(TimeoutError):
        audit.budget(0, 0)
    with pytest.raises(MemoryError):
        audit.budget(300, 300, replace(audit.SPEC, memory_bytes=1))


def test_output_must_be_new_child_of_reports(tmp_path, monkeypatch):
    from scripts.research.index_market.chan import m0_data
    monkeypatch.setattr(m0_data, 'REPO', tmp_path)
    existing = tmp_path/'reports'/'existing'
    existing.mkdir(parents=True)
    for path in (tmp_path, tmp_path/'reports', existing):
        with pytest.raises((ValueError, FileExistsError)):
            m0_data.safe_output(path)
