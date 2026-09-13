from copy import deepcopy

import pytest

from scripts.research.index_market.chan.stock_dg90_opportunity import validate, project


def sample():
    original = [dict(time=f"2025-01-02 {s}", date="2025-01-02", close=10) for s in
                ("10:00:00", "10:30:00", "11:00:00", "11:30:00", "13:30:00", "14:00:00", "14:30:00", "15:00:00")]
    rows = [dict(original[i], code="002245.SZ", frequency=90, exchange="SZSE", price_basis="qfq",
                 open=10, high=11, low=9, vol=1, amount=10) for i in (2, 5, 7)]
    return rows, original


def test_grid_and_projection():
    rows, original = sample()
    validate(rows, original)
    assert [r["source_end"] for r in rows] == [2, 5, 7]
    event = dict(signal_index=1, anchor_index=0, start_index=0, end_index=1)
    result = project(event, rows)
    assert result["signal_index"] == 5
    assert result["detection_signal_index"] == 1
    assert result["signal_index"] + 1 == 6  # next available 30-minute open


@pytest.mark.parametrize("key,value", [("frequency", 60), ("exchange", "BSE"),
    ("close", 10.1), ("high", 8), ("vol", -1), ("open", float("nan")),
    ("time", "2025-01-02 13:30:00"), ("date", "2025-01-03")])
def test_invalid_data_rejected(key, value):
    rows, original = sample()
    rows[0][key] = value
    with pytest.raises(ValueError):
        validate(rows, original)


def test_missing_duplicate_rejected():
    rows, original = sample()
    for bad in (rows[:-1], rows + [deepcopy(rows[-1])]):
        with pytest.raises(ValueError):
            validate(bad, original)


def test_float_precision_allowed_but_price_difference_rejected():
    rows, original = sample()
    original[2]["close"] *= 1 + 4e-8
    validate(rows, original)
    original[2]["close"] *= 1 + 2e-7
    with pytest.raises(ValueError, match="QFQ scale"):
        validate(rows, original)
