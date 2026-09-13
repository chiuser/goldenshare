from dataclasses import replace
from datetime import date, timedelta

import pytest

from scripts.research.index_market.chan.stock_opportunity import SPEC, aggregate, evaluate, nonoverlap, outcome


def rows(n=50):
    return [dict(time=f'{date(2024,1,1)+timedelta(days=i)} 10:00:00',
                 date=str(date(2024,1,1)+timedelta(days=i)),
                 open=100+i, high=102+i, low=99+i, close=101+i) for i in range(n)]


def event(data, i, group='B1'):
    return dict(group=group, signal_time=data[i]['time'], signal_index=i, sure=True, buy=True)


def test_next_open_window_and_tail():
    data = rows()
    x = outcome(data, 2, 5)
    assert x['entry_price'] == 103 and x['exit_index'] == 7
    assert x['return_value'] == pytest.approx(108/103-1)
    assert outcome(data, 44, 5) is not None
    assert outcome(data, 45, 5) is None
    data[2]['high'] = 9999
    assert outcome(data, 2, 5) == x


@pytest.mark.parametrize('high,low,expected', [(110,90,'ambiguous'), (110,100,'up'), (102,90,'down')])
def test_first_barrier(high, low, expected):
    data = rows()
    data[1].update(high=high, low=low)
    assert outcome(data, 0, 5)['first'] == expected


def test_overlap_boundary():
    a = [dict(entry_index=1,exit_index=5), dict(entry_index=5,exit_index=9), dict(entry_index=6,exit_index=10)]
    assert nonoverlap(a) == [a[0], a[2]]


def test_dedup_warmup_tail_matching_and_recall():
    data = rows()
    events = [event(data,0), event(data,4), event(data,4), event(data,4,'B2'), event(data,48)]
    spec = replace(SPEC, warmup_days=2, bars_per_day=1, horizons=(5,))
    result = evaluate(data, events, spec)
    b1, _, _, all_b = result['summary']
    assert b1['total'] == 2 and b1['censored'] == 1 and b1['signals']['n'] == 1
    assert all_b['signals']['n'] == 1
    expected = aggregate([outcome(data,i,5) for i in range(2,45)])
    assert b1['matched']['mean'] == expected['mean']
    assert b1['ordinary']['n'] == 43
    rallies = result['recall']['rallies']
    assert len(rallies) >= 1
    assert all(b['entry_index'] > a['exit_index'] for a,b in zip(rallies,rallies[1:]))


def test_reject_backdated_index():
    data = rows()
    e = event(data,4)
    e['signal_index'] = 3
    with pytest.raises(ValueError):
        evaluate(data,[e],replace(SPEC,warmup_days=2,bars_per_day=1,horizons=(5,)))
