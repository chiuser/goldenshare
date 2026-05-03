from __future__ import annotations

from datetime import date

from lake_console.backend.app.services.stk_mins_windowing import (
    build_target_request_windows,
    estimate_target_request_count,
    get_trade_days_per_window,
)


def _full_year_trade_dates_2025() -> list[date]:
    month_open_days = [21, 20, 21, 21, 20, 20, 21, 21, 20, 20, 20, 20]
    trade_dates: list[date] = []
    for month, open_days in enumerate(month_open_days, start=1):
        for day in range(1, open_days + 1):
            trade_dates.append(date(2025, month, day))
    return trade_dates


def test_trade_days_per_window_matches_freq_capacity():
    assert get_trade_days_per_window(1) == 33
    assert get_trade_days_per_window(5) == 163
    assert get_trade_days_per_window(15) == 470
    assert get_trade_days_per_window(30) == 888
    assert get_trade_days_per_window(60) == 1600


def test_target_request_windows_counts_match_full_year_expectation():
    trade_dates = _full_year_trade_dates_2025()

    assert len(build_target_request_windows(trade_dates=trade_dates, freq=1)) == 8
    assert len(build_target_request_windows(trade_dates=trade_dates, freq=5)) == 2
    assert len(build_target_request_windows(trade_dates=trade_dates, freq=15)) == 1
    assert len(build_target_request_windows(trade_dates=trade_dates, freq=30)) == 1
    assert len(build_target_request_windows(trade_dates=trade_dates, freq=60)) == 1


def test_estimate_target_request_count_matches_71643_for_full_year_all_market():
    trade_dates = _full_year_trade_dates_2025()

    assert estimate_target_request_count(symbol_count=5511, trade_date_count=len(trade_dates), freqs=[1, 5, 15, 30, 60]) == 71_643
