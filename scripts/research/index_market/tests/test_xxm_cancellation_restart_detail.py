"""Independent literal arithmetic for restart diagnostics, not software truth."""
from dataclasses import replace

import pytest

from scripts.research.index_market.xxm.cancellation_restart_detail import qualifies, timing
from src.biz.services.wealth.market.index_detail_xxm.types import Wave


def setup():
    # Manually defined old low80/-30, nearer low90/-10; live low79/DIF-12.
    old = Wave(-1, "2020-01-01", "2020-01-02", 2, 80, -30, "2020-01-02", "2020-01-02")
    near = Wave(-1, "2020-01-04", "2020-01-04", 1, 90, -10, "2020-01-04", "2020-01-04")
    current = Wave(-1, "2020-01-06", "2020-01-09", 4, 79, -12, "2020-01-08", "2020-01-09")
    return current, [old, near], old.reference()


def test_prior_segment_low_can_qualify_while_current_close_does_not():
    wave, pool, ref = setup()
    assert qualifies(wave, pool, ref) is True
    assert qualifies(wave, pool, ref, current_close=81) is False


@pytest.mark.parametrize("field,value", [("price", 80), ("dif", -30), ("count", 1), ("sign", 1)])
def test_exact_price_dif_equalities_minimum_count_and_direction(field, value):
    wave, pool, ref = setup()
    assert qualifies(replace(wave, **{field: value}), pool, ref) is False


def test_nearest_price_gate_and_pool_membership_cannot_be_skipped():
    wave, pool, ref = setup()
    pool[-1] = replace(pool[-1], price=78)
    assert qualifies(wave, pool, ref) is False
    assert qualifies(wave, pool[1:], ref) is False
    assert qualifies(wave, [], ref) is False


@pytest.mark.parametrize("first,expected", [
    ("2020-01-07", "BEFORE"), ("2020-01-08", "SAME"), ("2020-01-09", "AFTER")])
def test_qualification_timing_is_separate_from_observed_signal_time(first, expected):
    assert timing(first, "2020-01-08") == expected
