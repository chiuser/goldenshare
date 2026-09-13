from copy import deepcopy

import pytest

from scripts.research.index_market.chan.minute_data import slots
from scripts.research.index_market.chan.stock_timeframe_opportunity import (
    aggregate_bars,
    project,
)
from scripts.research.index_market.chan.stock_opportunity import outcome
from scripts.research.index_market.chan.stock_timeframe_opportunity import (
    attach_detection_indices,
)


def source():
    return [
        dict(
            code="002245.SZ",
            frequency=30,
            price_basis="qfq",
            date=d,
            time=f"{d} {s}",
            open=10 + i,
            high=12 + i,
            low=9 + i,
            close=11 + i,
            vol=100 + i,
            amount=1000 + i,
        )
        for d in ("2024-01-02", "2024-01-03")
        for i, s in enumerate(slots(30))
    ]


def test_exact_ohlcv_and_lunch_boundaries():
    data = source()
    bars = aggregate_bars(data)
    assert len(bars) == 8
    assert [r["time"][11:] for r in bars[:4]] == list(slots(60))
    b = bars[0]
    assert (b["open"], b["high"], b["low"], b["close"], b["vol"], b["amount"]) == (
        10,
        13,
        9,
        12,
        201,
        2001,
    )
    assert bars[2]["start_time"] == "2024-01-02 13:00:00"
    assert bars[3]["source_end"] == 7 and bars[4]["source_start"] == 8
    assert sum(r["vol"] for r in bars) == sum(r["vol"] for r in data)


@pytest.mark.parametrize(
    "kind", ["missing", "duplicate", "wrong_code", "wrong_frequency", "wrong_basis"]
)
def test_reject_bad_grid_and_identity(kind):
    data = source()
    if kind == "missing":
        data.pop()
    elif kind == "duplicate":
        data[1] = dict(data[0])
    elif kind == "wrong_code":
        data[0]["code"] = "920001.BJ"
    elif kind == "wrong_frequency":
        data[0]["frequency"] = 60
    else:
        data[0]["price_basis"] = "raw"
    with pytest.raises(ValueError):
        aggregate_bars(data)


def test_no_future_day_changes_and_no_partial_bar():
    data = source()
    first = aggregate_bars(data[:8])
    other = deepcopy(data)
    other[8]["high"] = 999
    assert aggregate_bars(other)[:4] == first
    with pytest.raises(ValueError):
        aggregate_bars(data[:9])


def test_projection_and_next_open_horizon():
    data = source()
    bars = aggregate_bars(data)
    e = dict(signal_index=1, start_index=0, end_index=1, anchor_index=1)
    p = project(e, bars)
    assert p["signal_index"] == 3 and p["detection_signal_index"] == 1
    x = outcome(data, p["signal_index"], 8)
    assert (
        x["entry_price"] == bars[2]["open"]
        and x["entry_index"] == 4
        and x["exit_index"] == 11
    )
    assert p["anchor_index"] == 3 and e["signal_index"] == 1
    result = {"events": [x]}
    attach_detection_indices(result, bars)
    assert x["detection_signal_index"] == 1
    assert x["detection_frequency"] == 60 and x["observation_frequency"] == 30
