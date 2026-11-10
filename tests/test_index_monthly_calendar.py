from calendar import monthrange
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from src.foundation.ingestion import (
    DatasetActionRequest,
    DatasetActionResolver,
    DatasetTimeInput,
)
from src.foundation.ingestion.errors import IngestionPlanningError


def _calendar_rows(start, end, *, holidays=()):
    return [
        (
            start + timedelta(days=i),
            (start + timedelta(days=i)).weekday() < 5
            and start + timedelta(days=i) not in holidays,
        )
        for i in range((end - start).days + 1)
    ]


def _resolver(mocker, *, missing=None, holidays=(), weekly=False):
    session = mocker.Mock()

    def execute(statement):
        params = statement.compile().params
        start, end = params["trade_date_1"], params["trade_date_2"]
        if weekly:
            assert (start.weekday(), end.weekday()) == (0, 6)
        else:
            assert start.day == 1
            assert end.day == monthrange(end.year, end.month)[1]
        rows = [
            row
            for row in _calendar_rows(start, end, holidays=holidays)
            if row[0] != missing
        ]
        return SimpleNamespace(all=lambda: rows)

    session.execute.side_effect = execute
    session.scalars.side_effect = lambda statement: [
        day
        for day, is_open in _calendar_rows(
            statement.compile().params["trade_date_1"],
            statement.compile().params["trade_date_2"],
            holidays=holidays,
        )
        if is_open and day != missing
    ]
    return DatasetActionResolver(session)


@pytest.mark.parametrize(
    ("end", "expected"),
    [
        (date(2026, 7, 30), [date(2026, 6, 30)]),
        (date(2026, 9, 1), [date(2026, 6, 30), date(2026, 7, 31), date(2026, 8, 31)]),
    ],
)
def test_monthly_range_uses_whole_calendar_not_clipped_end(mocker, end, expected):
    plan = _resolver(mocker).build_plan(
        DatasetActionRequest(
            dataset_key="index_monthly",
            action="maintain",
            time_input=DatasetTimeInput(
                mode="range", start_date=date(2026, 6, 30), end_date=end
            ),
        )
    )
    assert [unit.trade_date for unit in plan.units] == expected
    assert [unit.request_params for unit in plan.units] == [
        {"trade_date": day.strftime("%Y%m%d")} for day in expected
    ]


@pytest.mark.parametrize("day", [date(2026, 7, 30), date(2026, 8, 1)])
def test_monthly_point_rejects_non_month_end(mocker, day):
    with pytest.raises(IngestionPlanningError, match="最后一个交易日"):
        _resolver(mocker).build_plan(
            DatasetActionRequest(
                dataset_key="index_monthly",
                action="maintain",
                time_input=DatasetTimeInput(mode="point", trade_date=day),
            )
        )


@pytest.mark.parametrize(
    ("day", "holidays"),
    [
        (date(2026, 5, 29), ()),
        (date(2026, 7, 30), (date(2026, 7, 31),)),
    ],
)
def test_monthly_true_month_end_handles_weekend_and_holiday(mocker, day, holidays):
    plan = _resolver(mocker, holidays=holidays).build_plan(
        DatasetActionRequest(
            dataset_key="index_monthly",
            action="maintain",
            filters={"ts_code": "000001.SH"},
            time_input=DatasetTimeInput(mode="point", trade_date=day),
        )
    )
    assert plan.units[0].request_params == {
        "ts_code": "000001.SH",
        "trade_date": day.strftime("%Y%m%d"),
    }


def test_monthly_missing_calendar_day_fails_instead_of_guessing(mocker):
    with pytest.raises(IngestionPlanningError, match="交易日历"):
        _resolver(mocker, missing=date(2026, 7, 31)).build_plan(
            DatasetActionRequest(
                dataset_key="index_monthly",
                action="maintain",
                time_input=DatasetTimeInput(
                    mode="range",
                    start_date=date(2026, 7, 1),
                    end_date=date(2026, 7, 30),
                ),
            )
        )


def test_weekly_range_ending_midweek_excludes_that_week(mocker):
    plan = _resolver(mocker, weekly=True).build_plan(
        DatasetActionRequest(
            dataset_key="index_weekly",
            action="maintain",
            time_input=DatasetTimeInput(
                mode="range", start_date=date(2026, 7, 24), end_date=date(2026, 7, 30)
            ),
        )
    )
    assert [unit.request_params for unit in plan.units] == [{"trade_date": "20260724"}]


@pytest.mark.parametrize("day", [date(2026, 9, 29), date(2026, 10, 2)])
def test_weekly_short_week_rejects_non_period_end(mocker, day):
    holidays = (date(2026, 10, 1), date(2026, 10, 2))
    with pytest.raises(IngestionPlanningError, match="2026-09-30"):
        _resolver(mocker, holidays=holidays, weekly=True).build_plan(
            DatasetActionRequest("index_weekly", "maintain", DatasetTimeInput(mode="point", trade_date=day))
        )


def test_weekly_short_week_accepts_its_actual_period_end(mocker):
    holidays = (date(2026, 10, 1), date(2026, 10, 2))
    plan = _resolver(mocker, holidays=holidays, weekly=True).build_plan(
        DatasetActionRequest(
            dataset_key="index_weekly", action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 9, 30)),
        )
    )
    assert [unit.request_params for unit in plan.units] == [{"trade_date": "20260930"}]
