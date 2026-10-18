"""Synthetic input guards; not software labels or integration acceptance.

Field contract independently comes from the real view schema/four samples in
reports/xxm_cross_index_daily_20261018_01/source_precheck.json. Synthetic open
flags below deliberately select two dates to exercise date validation only.
"""
from copy import deepcopy
from datetime import date, timedelta
import json

import pytest

from scripts.research.index_market.xxm.cross_index_daily import (
    SPEC, classify, identity, read_unit, run, seal, validate_calendar, validate_rows,
)
from scripts.research.index_market.xxm.top_daily_ambiguity import ReferenceGateCalculator
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator


def calendar():
    first, last = date.fromisoformat(SPEC.start), date.fromisoformat(SPEC.end)
    return [dict(trade_date=(first + timedelta(days=i)).isoformat(),
                 is_open=i in (1, 2)) for i in range((last - first).days + 1)]


def rows():
    return [dict(ts_code='399006.SZ', trade_date=d, close=c,
                 macd_dif_bfq=-2.5, macd_dea_bfq=-3.0, macd_bfq=1.0)
            for d, c in [('2020-01-02', 1500.25), ('2020-01-03', 1550.75)]]


def test_real_field_contract_and_normal_price_change_are_accepted():
    bars = validate_rows('399006.SZ', rows(), calendar())
    assert [b.close for b in bars] == [1500.25, 1550.75]
    data = rows()
    for r in data:
        r['ts_code'] = '399001.SZ'
    assert len(validate_rows('399001.SZ', data, calendar())) == 2
    assert SPEC.calendar_exchange == 'SSE'  # Explicit shared-A-share decision.


@pytest.mark.parametrize('case', ['code', 'null', 'nan', 'close', 'missing',
    'duplicate', 'reverse', 'range', 'over_limit'])
def test_bad_source_is_rejected_at_real_validation_boundary(case):
    data = rows()
    if case == 'code': data[0]['ts_code'] = '000001.SH'
    elif case == 'null': data[0]['macd_dif_bfq'] = None
    elif case == 'nan': data[0]['macd_dea_bfq'] = float('nan')
    elif case == 'close': data[0]['close'] = 0
    elif case == 'missing': data.pop()
    elif case == 'duplicate': data[1] = dict(data[0])
    elif case == 'reverse': data.reverse()
    elif case == 'range': data[0]['trade_date'] = '2019-12-31'
    else: data *= SPEC.max_rows
    with pytest.raises(ValueError):
        validate_rows('399006.SZ', data, calendar())


@pytest.mark.parametrize('case', ['missing', 'reverse', 'flag', 'bounds'])
def test_calendar_does_not_hide_missing_days(case):
    data = calendar()
    if case == 'missing': data.pop(10)
    elif case == 'reverse': data.reverse()
    elif case == 'flag': data[1]['is_open'] = 1
    else: data.pop()
    with pytest.raises(ValueError): validate_calendar(data)


def literal_row(base=True, current=False, reference=True, dif=-2):
    # Independent literals: historical reference DIF +5, current DIF -2.
    event = dict(time='2024-01-02', direction='TOP', type='DULL',
                 route='activation', fromState='NONE',
                 eventReference=dict(startTime='2023-12-01', endTime='2023-12-10', price=100, dif=5))
    return dict(bar=dict(time='2024-01-02', dif=dif), variants={v: dict(
        point=dict(ordinaryState='DULL' if active else 'NONE'),
        events=[deepcopy(event)] if active else []) for v, active in
        [('BASE', base), ('ZC', current), ('ZR', reference)]})


def test_literal_first_activation_distinguishes_the_two_conditions():
    assert classify(literal_row()) == 'CURRENT_VS_REFERENCE'
    assert classify(literal_row(reference=False)) == 'BASE_VS_BOTH'
    assert classify(literal_row(current=True, dif=1)) is None


def test_structure_return_and_historical_events_are_not_first_activation():
    for event_type, route in [('DULL', 'dif_return'), ('STRUCTURE', 'dif_turn'),
                              ('RESEARCH_HISTORICAL_WITHDRAWAL', 'historical_price_break')]:
        row = literal_row(reference=False)
        row['variants']['BASE']['events'][0].update(type=event_type, route=route)
        assert classify(row) is None


def test_completed_unit_survives_interruption_and_cannot_be_overwritten(tmp_path):
    seal(tmp_path, 'source_399006.SZ', rows())
    (tmp_path / 'source_399001.SZ.json.partial').write_text('interrupted')
    assert read_unit(tmp_path, 'source_399006.SZ') == rows()
    assert read_unit(tmp_path, 'source_399001.SZ') is None
    with pytest.raises(ValueError, match='overwrite'):
        seal(tmp_path, 'source_399006.SZ', rows())


def test_tampered_source_or_result_is_refused(tmp_path):
    for name in ('source_399006.SZ', 'result_399006.SZ'):
        seal(tmp_path, name, dict(ts_code='399006.SZ', values=[1, 2]))
        (tmp_path / (name + '.json')).write_text(json.dumps(dict(ts_code='399001.SZ')))
        with pytest.raises(ValueError, match='Changed'):
            read_unit(tmp_path, name)


def test_unsealed_final_file_is_not_treated_as_complete(tmp_path):
    (tmp_path / 'source.json').write_text('[]')
    with pytest.raises(ValueError, match='Incomplete'): read_unit(tmp_path, 'source')


def test_product_identity_stays_restricted_and_restore_rejects_other_source():
    with pytest.raises(ValueError, match='Unsupported XXM identity'):
        XxmCalculator(period='day', source_identity='literal', ts_code='399006.SZ')
    a = ReferenceGateCalculator(period='day', source_identity='399006.SZ:hash', variant='BASE')
    b = ReferenceGateCalculator(period='day', source_identity='399001.SZ:hash', variant='BASE')
    with pytest.raises(ValueError): b.restore(a.snapshot())
    assert identity()['spec']['codes'] == ['399006.SZ', '399001.SZ']


def test_resume_rejects_changed_settings_before_any_database_access(tmp_path):
    saved = identity()
    saved['spec']['end'] = '2024-09-01'  # Deliberate incompatible experiment.
    seal(tmp_path, 'identity', saved)
    with pytest.raises(ValueError, match='settings/code identity changed'):
        run(tmp_path, resume=True)
