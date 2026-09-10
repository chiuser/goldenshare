"""Synthetic-only diagnostics tests: no Lake, replay or external resources."""
from copy import deepcopy
from datetime import date, timedelta
from dataclasses import replace
import json

import pytest

from scripts.research.index_market.chan.minute_diagnostics import features, sensitivity
from scripts.research.index_market.chan.m0_data import REPO, safe_output
from scripts.research.index_market.chan import minute_diagnostics as diagnostic


def sample():
    rows = []
    for day in range(23):
        d = str(date(2024, 1, 1)+timedelta(days=day))
        for slot in ('10:30:00','11:30:00','14:00:00','15:00:00'):
            rows.append(dict(date=d, time=d+' '+slot, open=100., high=110., low=90., close=100., amount=10.))
    return rows, dict(signal_index=81, anchor_index=80, signal_time=rows[81]['time'])


def test_feature_golden_and_intraday_amount():
    rows, e = sample()
    rows[81]['close'] = 105.
    rows[81]['amount'] = 30.
    result = features(rows, e)
    assert result == pytest.approx(dict(return20=.05, drawdown20=105/110-1, amount_ratio=2., anchor_rebound=105/90-1))


def test_future_prices_amount_and_daily_close_cannot_leak():
    rows, e = sample()
    expected = features(rows, e)
    changed = deepcopy(rows)
    for row in changed[82:]:
        row.update(close=100000., high=100000., amount=100000.)
    assert features(changed, e) == expected == features(rows[:82], e)


def test_zero_amount_is_missing_not_zero():
    rows, e = sample()
    for row in rows[:80]:
        row['amount'] = 0.
    assert features(rows, e)['amount_ratio'] is None


@pytest.mark.parametrize('patch', [dict(anchor_index=82), dict(anchor_index=-1), dict(signal_index=1000), dict(signal_time='bad')])
def test_invalid_event_rejected(patch):
    rows, e = sample()
    with pytest.raises(ValueError):
        features(rows, dict(e, **patch))


def test_insufficient_history_rejected():
    rows, _ = sample()
    with pytest.raises(ValueError, match='history'):
        features(rows, dict(signal_index=5, anchor_index=4, signal_time=rows[5]['time']))


def test_calendar_deletion_and_no_input_mutation():
    records = [dict(event_id=str(i), date=d, year=d[:4], q=q, return20=0., drawdown20=0., amount_ratio=None, anchor_rebound=0.)
               for i,(d,q) in enumerate([('2024-01-01',.1),('2024-01-01',.2),('2025-01-01',-.1)])]
    before = deepcopy(records)
    result = sensitivity(records)
    assert result['n']==3 and result['signal_dates']==2
    assert result['without_best_q']==pytest.approx(0.)
    removed = result['deletion']['date'][0]
    assert removed['removed_n']==2 and removed['remaining_n']==1 and removed['q']==-.1
    assert result['outcome_features']['positive']['amount_ratio']['missing']==2
    assert records==before


def test_singleton_deletion_is_missing():
    row = dict(event_id='x', date='2024-01-01', year='2024', q=0., return20=0., drawdown20=0., amount_ratio=1., anchor_rebound=0.)
    result = sensitivity([row])
    assert result['without_best_q'] is None
    assert result['deletion']['date'][0]['q'] is None
    assert result['outcome_features']['positive']['return20']['n']==0


def test_output_existing_or_outside_reports_rejected(tmp_path):
    with pytest.raises(ValueError):
        safe_output(tmp_path/'result')
    with pytest.raises(ValueError):
        safe_output(REPO/'reports')


def test_manifest_tamper_rejected_before_artifact_read(tmp_path, monkeypatch):
    (tmp_path/'manifest.json').write_text('{}')
    monkeypatch.setattr(diagnostic, 'SPEC', replace(diagnostic.SPEC, report=str(tmp_path)))
    with pytest.raises(ValueError, match='manifest changed'):
        diagnostic.authenticated_input()


def test_artifact_escape_rejected_before_audit(tmp_path, monkeypatch):
    folder = tmp_path/'report'
    folder.mkdir()
    (tmp_path/'outside.json').write_text('{}')
    payload = json.dumps({'artifacts_sha256':{'../outside.json':'irrelevant'}}).encode()
    (folder/'manifest.json').write_bytes(payload)
    monkeypatch.setattr(diagnostic, 'SPEC', replace(diagnostic.SPEC, report=str(folder), manifest_sha256=diagnostic.digest(payload)))
    with pytest.raises(ValueError, match='paths/count'):
        diagnostic.authenticated_input()


def test_byte_budget_rejected_before_audit(tmp_path, monkeypatch):
    (tmp_path/'input.json').write_text('{}')
    payload = json.dumps({'artifacts_sha256':{'input.json':'irrelevant'}}).encode()
    (tmp_path/'manifest.json').write_bytes(payload)
    monkeypatch.setattr(diagnostic, 'SPEC', replace(diagnostic.SPEC, report=str(tmp_path), manifest_sha256=diagnostic.digest(payload), max_bytes=1))
    with pytest.raises(ValueError, match='byte budget'):
        diagnostic.authenticated_input()
