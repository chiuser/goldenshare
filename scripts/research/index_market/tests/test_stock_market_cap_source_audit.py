"""Synthetic guards plus read-only replay of one compact frozen-source audit."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.research.index_market.chan.stock_market_cap_source_audit import audit, profile


DAY = '20220921'


def inputs():
    inventory = [dict(code=f'{i:06}.SZ', board='SZSE/主板', seen=False) for i in range(1, 5)]
    rows = [dict(ts_code=r['code'], trade_date=DAY, total_mv=i + 1.0)
            for i, r in enumerate(inventory[:3])]
    return rows, inventory


def test_missing_is_not_removed_or_imputed():
    rows, inv = inputs()
    result = profile(rows, inv, [], DAY)
    assert result['eligible'] == result['not_selected'] == 4
    assert result['covered'] == 3
    assert result['missing'][0]['full_day_suspension'] is False
    assert result['boards'][0]['illustrative_small_mid_large'] == [1, 1, 1]


@pytest.mark.parametrize('kind,timing,expected', [('S', None, True), ('S', '09:30-10:00', False), ('R', None, False)])
def test_suspension_semantics(kind, timing, expected):
    rows, inv = inputs()
    s = [dict(ts_code='000004.SZ', trade_date=DAY, suspend_type=kind, suspend_timing=timing)]
    assert profile(rows, inv, s, DAY)['missing'][0]['full_day_suspension'] is expected


def test_resume_conflict_does_not_explain_full_day_missing():
    rows, inv = inputs()
    s = [dict(ts_code='000004.SZ', trade_date=DAY, suspend_type=k, suspend_timing=None) for k in ('S', 'R')]
    assert not profile(rows, inv, s, DAY)['missing'][0]['full_day_suspension']


@pytest.mark.parametrize('value', [None, 0, -1, float('nan'), float('inf'), True, '100'])
def test_bad_cap_rejected(value):
    rows, inv = inputs()
    rows[0]['total_mv'] = value
    with pytest.raises(ValueError):
        profile(rows, inv, [], DAY)


def test_duplicate_and_wrong_date_rejected():
    rows, inv = inputs()
    with pytest.raises(ValueError):
        profile(rows + rows[:1], inv, [], DAY)
    rows[0]['trade_date'] = '20260914'
    with pytest.raises(ValueError):
        profile(rows, inv, [], DAY)


def test_bj_not_admitted_and_known_stocks_not_in_bins():
    rows, inv = inputs()
    rows.append(dict(ts_code='920001.BJ', trade_date=DAY, total_mv=1))
    inv[0]['seen'] = True
    result = profile(rows, inv, [], DAY)
    assert result['outside_universe'] == 1
    assert result['not_selected_covered'] == 2
    inv.append(dict(code='920001.BJ', board='BJ', seen=False))
    with pytest.raises(ValueError):
        profile(rows, inv, [], DAY)


def test_frozen_evidence_and_tamper_guards():
    root = Path(__file__).resolve().parents[4]
    evidence = json.loads((root / 'reports/stock_market_cap_source_20260914/evidence.json').read_text())
    assert audit(evidence, root)['not_selected_covered'] == 4034
    changed = deepcopy(evidence)
    changed['summary']['covered'] += 1
    with pytest.raises(ValueError, match='summary'):
        audit(changed, root)
    changed = deepcopy(evidence)
    changed['p0_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='fingerprint'):
        audit(changed, root)
