"""M5 WEEK/MONTH/READ-05: civil identities never imply exchange sessions."""
from datetime import date

import pytest

from src.biz.queries.wealth.market.trading_assistant.return_windows import calendar_dates, curve_windows


def test_months_expand_both_ends_without_clipping_to_requested_range():
    start, end = date(2026, 8, 22), date(2026, 9, 22)
    points = list(curve_windows(start, end, granularity="MONTH", today=date(2026, 10, 1)))
    assert [(p.start, p.end, p.target_end, p.is_ended) for p in points] == [
        (date(2026, 8, 1), date(2026, 8, 31), date(2026, 8, 31), True),
        (date(2026, 9, 1), date(2026, 9, 30), date(2026, 9, 30), True),
    ]
    assert (start, end) == (date(2026, 8, 22), date(2026, 9, 22))


def test_week_expands_wednesday_to_friday_and_crosses_year():
    points = list(curve_windows(date(2025, 12, 31), date(2026, 1, 2),
                               granularity="WEEK", today=date(2026, 1, 10)))
    assert len(points) == 1
    assert (points[0].start, points[0].end) == (date(2025, 12, 29), date(2026, 1, 4))


def test_current_month_keeps_identity_but_excludes_future_results():
    points = list(curve_windows(date(2026, 8, 22), date(2027, 1, 31),
                               granularity="MONTH", today=date(2026, 9, 15)))
    assert len(points) == 2
    assert points[-1].end == date(2026, 9, 30)
    assert points[-1].target_end == date(2026, 9, 15)
    assert not points[-1].is_ended
    assert points[-1].effective_range(date(2026, 9, 10)) == (date(2026, 9, 10), date(2026, 9, 15))
    assert points[-1].effective_range(date(2026, 10, 1)) is None
    assert points[0].effective_range(date(2026, 9, 1)) is None
    assert points[-1].effective_range(date(2020, 1, 1)) == (date(2026, 9, 1), date(2026, 9, 15))


def test_future_only_returns_no_points_even_at_date_max():
    assert list(curve_windows(date(9999, 12, 31), date.max, granularity="WEEK", today=date(2026, 9, 15))) == []


def test_daily_preserves_civil_days_without_inventing_trading_sessions():
    points = list(curve_windows(date(2026, 9, 12), date(2026, 9, 15),
                               granularity="DAY", today=date(2026, 9, 14)))
    assert [point.start.day for point in points] == [12, 13, 14]
    assert all(point.start == point.end for point in points)
    assert [point.is_ended for point in points] == [True, True, False]


@pytest.mark.parametrize("year,last", [(2024, 29), (2025, 28), (2000, 29), (2100, 28)])
def test_real_february_month_ends(year, last):
    point = next(curve_windows(date(year, 2, 15), date(year, 2, 16),
                              granularity="MONTH", today=date(year, 3, 1)))
    assert point.end == date(year, 2, last)


def test_calendar_five_columns_complete_adjacent_months_not_only_known_results():
    dates = calendar_dates(date(2026, 9, 1))
    assert dates[0] == date(2026, 8, 31) and dates[-1] == date(2026, 10, 2)
    assert len(dates) == 25 and list(dates) == sorted(set(dates))
    assert all(day.weekday() < 5 for day in dates)
    assert len(calendar_dates(date(2026, 8, 1))) == 30
    assert calendar_dates(date(1, 1, 1))[0] == date.min
    assert calendar_dates(date(9999, 12, 1))[-1] == date.max


@pytest.mark.parametrize("start,end,grain", [
    (date(2026, 9, 2), date(2026, 9, 1), "DAY"),
    (date(2026, 9, 1), date(2026, 9, 2), "QUARTER"),
])
def test_invalid_windows_rejected(start, end, grain):
    with pytest.raises(ValueError):
        list(curve_windows(start, end, granularity=grain, today=date(2026, 9, 15)))


def test_calendar_rejects_non_first_day():
    with pytest.raises(ValueError):
        calendar_dates(date(2026, 9, 2))
