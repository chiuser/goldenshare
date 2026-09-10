"""Synthetic B0 boundaries: no Lake, external API or empirical run."""
from copy import deepcopy
from dataclasses import replace

import pytest

from scripts.research.index_market.chan import minute_roundtrip as rt


def event(i, group='B3', identity=None, evaluation=True):
    return dict(event_id=identity or f'{group}-{i}', signal_index=i, group=group,
                evaluation=evaluation)


def rows():
    return [dict(code='000001.SH', frequency=30, date=t[:10], time=t,
                 open=100.0, high=102.0, low=98.0, close=101.0)
            for t in ('2022-01-07 11:00:00', '2022-01-07 11:30:00',
                      '2022-01-07 13:30:00', '2022-01-07 14:00:00',
                      '2022-01-07 14:30:00', '2022-01-07 15:00:00',
                      '2022-01-10 10:00:00', '2022-01-10 10:30:00')]


@pytest.mark.parametrize('sell_group', ['S1', 'S2', 'S3'])
def test_any_new_sell_and_entry_bar_close(sell_group):
    events = [event(0, 'S1'), event(1), event(2, sell_group)]
    trades, decisions = rt.pair_events(events, 8, 'B3')
    assert len(trades) == 1 and trades[0]['entry_index'] == 2
    assert trades[0]['exit_index'] == 3
    assert decisions == [dict(event_id='B3-1', reason='entered')]
    assert rt.verify_pairs(events, 8, 'B3', trades) == 1


def test_conflict_duplicate_holding_and_exit_bar_new_buy():
    events = [event(0), event(0, 'S2'), event(1, identity='b'), event(1, identity='a'),
              event(2), event(3), event(3, 'S3'), event(4), event(6, 'S1')]
    trades, decisions = rt.pair_events(events, 8, 'B3')
    assert [(t['buy_event']['event_id'], t['entry_index'], t['exit_index']) for t in trades] == [('a', 2, 4), ('B3-4', 5, 7)]
    assert [d['reason'] for d in decisions] == ['conflict', 'entered', 'duplicate_bar', 'holding', 'holding', 'entered']
    rt.verify_pairs(events, 8, 'B3', trades)


def test_multi_sell_preserves_all_ids_one_exit():
    events = [event(0), event(2, 'S1'), event(2, 'S2')]
    trades, _ = rt.pair_events(events, 8, 'B3')
    assert len(trades) == 1 and len(trades[0]['sell_events']) == 2
    rt.verify_pairs(events, 8, 'B3', trades)


def test_old_sell_never_exits_and_initialization_other_group_ignored():
    events = [event(0, evaluation=False), event(0, 'S1'), event(1, 'B1'), event(2)]
    trades, decisions = rt.pair_events(events, 8, 'B3')
    assert len(trades) == len(decisions) == 1
    assert trades[0]['status'] == 'terminal_mark' and trades[0]['sell_events'] == []


@pytest.mark.parametrize('events,entered,pending_sell', [
    ([event(7)], 0, False), ([event(0)], 1, False),
    ([event(0), event(7, 'S1')], 1, True),
])
def test_tail_preserved(events, entered, pending_sell):
    trades, decisions = rt.pair_events(events, 8, 'B3')
    assert len(trades) == entered
    if entered:
        assert trades[0]['exit_index'] is None
        assert trades[0].get('pending_exit', False) == pending_sell
    else:
        assert decisions[0]['reason'] == 'pending_entry'
    rt.verify_pairs(events, 8, 'B3', trades)


def test_midday_weekend_open_times_and_price_path():
    rr = rows()
    events = [event(1), event(5, 'S3')]
    trades, _ = rt.pair_events(events, 8, 'B3')
    t = rt.enrich(rr, trades[0])
    assert t['entry_time'] == '2022-01-07 13:00:00'
    assert t['exit_time'] == '2022-01-10 09:30:00'
    assert t['holding_bars'] == 4 and t['holding_trade_dates'] == 2
    rt.verify_prices(rr, [t])
    assert rt.opening_time(dict(time='2022-01-07 14:00:00', frequency=60)) == '2022-01-07 13:00:00'


@pytest.mark.parametrize('exit_price,mae,mfe', [(90., -.1, .02), (110., -.02, .1)])
def test_exit_gap_included_but_exit_bar_future_extremes_excluded(exit_price, mae, mfe):
    rr = rows()
    events = [event(0), event(2, 'S2')]
    trades, _ = rt.pair_events(events, 8, 'B3')
    rr[3].update(open=exit_price, low=1., high=999.)
    t = rt.enrich(rr, trades[0])
    assert t['mae'] == pytest.approx(mae) and t['mfe'] == pytest.approx(mfe)
    assert t['gross_change'] == pytest.approx(exit_price/100-1)
    assert t['price_path'] == rr[1:3]
    rt.verify_prices(rr, [t])


def test_terminal_mark_includes_last_bar_and_summary_keeps_loss():
    rr = rows()
    rr[-1].update(close=90., low=85., high=102.)
    events = [event(0), event(2)]
    trades, decisions = rt.pair_events(events, 8, 'B3')
    enriched = [rt.enrich(rr, t) for t in trades]
    summary = rt.summarize(events, 'B3', enriched, decisions)
    assert summary['raw_buys'] == 2 and summary['entries'] == 1
    assert summary['natural_exits'] == 0 and summary['terminal_marks'] == 1
    assert not summary['sample_gate']
    assert enriched[0]['gross_change'] == pytest.approx(-.1)
    assert enriched[0]['mae'] == pytest.approx(-.15)
    rt.verify_prices(rr, enriched)


def test_selection_never_uses_price_outcome_and_prefix_natural_exits_stable():
    events = [event(0), event(2, 'S1'), event(4), event(6, 'S2')]
    before = deepcopy(events)
    original, _ = rt.pair_events(events, 8, 'B3')
    changed = [{**e, 'future_q': 999., 'supported': False, 'price': -100.} for e in events]
    alternate, _ = rt.pair_events(changed, 8, 'B3')
    assert [(t['entry_index'], t['exit_index']) for t in original] == [(t['entry_index'], t['exit_index']) for t in alternate]
    prefix, _ = rt.pair_events([e for e in events if e['signal_index'] < 6], 6, 'B3')
    assert [t for t in prefix if t['status'] == 'natural_exit'] == original[:1]
    assert events == before


def test_cases_use_order_not_profit_and_empty_group():
    trades = [dict(status='natural_exit', gross_change=-.2),
              dict(status='natural_exit', gross_change=.8), dict(status='terminal_mark', gross_change=-.5)]
    assert rt.select_cases(trades) == [trades[0], trades[2]]
    assert rt.select_cases([]) == []
    assert rt.summarize([], 'B1', [], [])['entries'] == 0


@pytest.mark.parametrize('events', [[event(2), event(1)], [event(1), event(1)], [event(8)]])
def test_invalid_event_order_duplicate_out_of_range(events):
    with pytest.raises(ValueError):
        rt.pair_events(events, 8, 'B3')


def test_frozen_spec_rejected_before_source_access(tmp_path, monkeypatch):
    def forbidden():
        raise AssertionError('source must not be accessed')
    monkeypatch.setattr(rt, 'authenticated_input', forbidden)
    with pytest.raises(ValueError, match='unapproved'):
        rt.execute(tmp_path/'out', replace(rt.SPEC, min_exits=1))


def test_price_source_identity_and_future_anchor_rejected():
    rr = rows()
    e = dict(**event(1), code='000001.SH', frequency=30, signal_time=rr[1]['time'],
             sure=True, buy=True, start_index=0, anchor_index=0, end_index=0, anchor_time=rr[0]['time'])
    rt.validate_cell(rr, [e], '000001.SH', 30)
    for bad in ({**e, 'anchor_index': 2}, {**e, 'frequency': 60}, {**e, 'evaluation': False}):
        with pytest.raises(ValueError):
            rt.validate_cell(rr, [bad], '000001.SH', 30)
