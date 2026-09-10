"""Fixed B0 window selection and source authentication; no Lake reads."""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from scripts.research.index_market.chan import stock_chan_reference as p


def fixture():
    rows = [dict(time=(datetime(2026, 1, 5, 10)+timedelta(minutes=i*30)).isoformat(sep=' '),
                 open=100.+i, frequency=30) for i in range(10)]
    trades = []
    for i in range(0, 8, 2):
        trades.append(dict(status='natural_exit', buy_event=dict(event_id=str(i), signal_index=i,
            signal_time=rows[i]['time']), entry_index=i+1, exit_index=i+2,
            entry_time=p.opening_time(rows[i+1]), exit_time=p.opening_time(rows[i+2]),
            entry_price=rows[i+1]['open'], exit_price=rows[i+2]['open'],
            gross_change=rows[i+2]['open']/rows[i+1]['open']-1,
            sell_events=[dict(event_id='sell'+str(i), signal_index=i+1, signal_time=rows[i+1]['time'])]))
    return rows, trades


def test_latest_three_by_time_not_profit_or_input_order():
    rows, trades = fixture()
    original = deepcopy(trades)
    selected = p.select_windows(list(reversed(trades)), rows)
    assert [r['buy_event_id'] for r in selected] == ['2', '4', '6']
    assert trades == original


def test_terminal_not_counted_and_insufficient_rejected():
    rows, trades = fixture()
    trades[-1]['status'] = 'terminal_mark'
    assert [r['buy_event_id'] for r in p.select_windows(trades, rows)] == ['0', '2', '4']
    with pytest.raises(ValueError, match='insufficient'):
        p.select_windows(trades[1:], rows)


def test_duplicate_rejected():
    rows, trades = fixture()
    with pytest.raises(ValueError, match='duplicate'):
        p.select_windows(trades+[trades[0]], rows)


def test_wrong_execution_time_or_price_rejected():
    rows, trades = fixture()
    trades[-1]['entry_time'] = rows[trades[-1]['entry_index']]['time']
    with pytest.raises(AssertionError):
        p.select_windows(trades, rows)


def test_manifest_tamper_rejected_before_parse(tmp_path):
    (tmp_path/'manifest.json').write_text('{}')
    with pytest.raises(ValueError, match='manifest changed'):
        p.authenticate(tmp_path, 'wrong')
