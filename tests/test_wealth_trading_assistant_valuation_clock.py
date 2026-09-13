from datetime import date, datetime, timezone

import pytest

from src.biz.services.wealth.market.trading_assistant.valuation_clock import valuation_cutoff
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationDataUnavailable


@pytest.mark.parametrize("clock", ["2026-09-11T07:00:00+00:00", "2026-09-11T20:00:00+08:00", "2026-09-12T08:00:00+08:00"])
def test_close_cutoff_is_independent_of_arrival_or_fee_selection_time(clock):
    assert valuation_cutoff(date(2026, 9, 11), is_open=True, observed_at=datetime.fromisoformat(clock)) == (
        datetime(2026, 9, 11, 7, tzinfo=timezone.utc))


@pytest.mark.parametrize("day,is_open,clock", [
    (date(2026, 9, 11), True, "2026-09-11T14:59:59.999999+08:00"),
    (date(2026, 9, 14), True, "2026-09-12T20:00:00+08:00"),
    (date(2026, 9, 13), False, "2026-09-12T20:00:00+08:00"),
])
def test_no_intraday_or_future_daily_snapshot(day, is_open, clock):
    with pytest.raises(CalculationDataUnavailable):
        valuation_cutoff(day, is_open=is_open, observed_at=datetime.fromisoformat(clock))


def test_closed_date_cash_cutoff_is_never_in_future():
    now = datetime.fromisoformat("2026-09-12T12:30:00+08:00")
    assert valuation_cutoff(date(2026, 9, 12), is_open=False, observed_at=now) == now
    end = valuation_cutoff(date(2026, 9, 6), is_open=False, observed_at=now)
    assert end.isoformat() == "2026-09-06T23:59:59.999999+08:00"


@pytest.mark.parametrize("clock", [None, "2026-09-11", datetime(2026, 9, 11, 20)])
def test_no_untrusted_or_timezone_naive_time(clock):
    with pytest.raises(ValueError):
        valuation_cutoff(date(2026, 9, 11), is_open=True, observed_at=clock)
