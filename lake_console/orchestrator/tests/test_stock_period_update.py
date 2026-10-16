from datetime import date

import pytest

from orchestrator.defs.stock_period_update import close_day, daily_periods


def test_failed_friday_and_month_end_only_catch_periods():
    assert daily_periods(
        today=date(2026, 10, 19), freq="week", completed_through="2026-10-09"
    ) == ["2026-10-16", "2026-10-23"]
    assert daily_periods(
        today=date(2026, 10, 16), freq="month", completed_through="2026-08"
    ) == ["2026-09", "2026-10"]
    assert daily_periods(
        today=date(2026, 10, 19),
        freq="week",
        completed_through="2026-10-09",
        last_refresh="2026-10-19",
    ) == ["2026-10-16"]
    assert close_day("2026-10-09", "week", ["2026-10-08", "2026-10-09"]) == "2026-10-09"
    with pytest.raises(ValueError):
        daily_periods(today=date(2026, 10, 16), freq="week", completed_through=None)


def test_adjacent_factor_changes_refresh_both_frequencies_and_failure_keeps_notification(
    tmp_path, monkeypatch
):
    from orchestrator.defs.bootstrap import stock_period_history
    from orchestrator.defs.io.stock_period_raw import atomic_json, connection, read_json
    from orchestrator.defs.paths import (
        silver_adj_factor_path,
        silver_trade_calendar_path,
    )
    from orchestrator.defs.stock_period_update import execute_daily

    root = tmp_path / "lake"
    staging = tmp_path / "staging"
    with connection(tmp_path / "fixtures") as con:
        calendar = silver_trade_calendar_path(root)
        calendar.parent.mkdir(parents=True)
        con.sql(
            "SELECT unnest(['2026-10-15','2026-10-16'])::DATE cal_date,'SSE' exchange,1 is_open"
        ).write_parquet(str(calendar))
        for day, factor in [("2026-10-15", 1), ("2026-10-16", 2)]:
            path = silver_adj_factor_path(root, day)
            path.parent.mkdir(parents=True)
            con.sql(
                "SELECT '000001.SZ' ts_code,?::DOUBLE adj_factor UNION ALL SELECT '000002.SZ',1",
                params=[factor],
            ).write_parquet(str(path))
    atomic_json(
        staging / "stock_period/baseline.json",
        {"status": "ready", "listed": ["000001.SZ", "000002.SZ"]},
    )
    atomic_json(
        staging / "stock_period/daily.json",
        {
            "completed_through": {"week": "2026-10-16"},
            "last_refresh": {"week": "2026-10-16"},
            "factor_through": "2026-10-15",
        },
    )
    observed = []

    def failed(**kw):
        observed.append(kw["intent"])
        raise OSError("history_not_complete")

    monkeypatch.setattr(stock_period_history, "run_period", failed)
    kwargs = {
        "root": root,
        "staging": staging,
        "today": date(2026, 10, 16),
        "freq": "week",
        "listed": {"000001.SZ", "000002.SZ", "000003.SZ"},
        "aliases": {},
    }
    with pytest.raises(OSError):
        execute_daily(**kwargs)
    assert observed[0]["codes"] == ["000001.SZ", "000003.SZ"] and observed[0][
        "frequencies"
    ] == ["week", "month"]
    assert (
        read_json(staging / "stock_period/daily.json")["factor_through"] == "2026-10-15"
    )
    monkeypatch.setattr(stock_period_history, "run_period", lambda **kw: {"files": []})
    execute_daily(**kwargs)
    assert (
        read_json(staging / "stock_period/daily.json")["factor_through"] == "2026-10-16"
    )


def test_week_midpoint_success_does_not_close_period_or_replay_days(
    tmp_path, monkeypatch
):
    from orchestrator.defs.bootstrap import stock_period_history
    from orchestrator.defs.io.stock_period_raw import atomic_json, connection, read_json
    from orchestrator.defs.paths import silver_trade_calendar_path
    from orchestrator.defs.stock_period_update import execute_daily

    root = tmp_path / "lake"
    staging = tmp_path / "staging"
    with connection(tmp_path / "fixtures") as con:
        calendar = silver_trade_calendar_path(root)
        calendar.parent.mkdir(parents=True)
        con.sql(
            "SELECT unnest(['2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16'])::DATE cal_date,'SSE' exchange,1 is_open"
        ).write_parquet(str(calendar))
    atomic_json(
        staging / "stock_period/baseline.json",
        {"status": "ready", "listed": ["000001.SZ"]},
    )
    atomic_json(
        staging / "stock_period/daily.json",
        {
            "completed_through": {"week": "2026-10-09"},
            "last_refresh": {},
            "factor_through": "2026-10-14",
        },
    )
    calls = []

    def run(**kw):
        calls.append(kw["intent"])
        return {"files": [], "unit_asofs": {"week": {"2026-10-16": "20261014"}}}

    monkeypatch.setattr(stock_period_history, "run_period", run)
    execute_daily(
        root=root,
        staging=staging,
        today=date(2026, 10, 14),
        freq="week",
        listed={"000001.SZ"},
        aliases={},
    )
    state = read_json(staging / "stock_period/daily.json")
    assert (
        state["completed_through"]["week"] == "2026-10-09"
        and state["last_refresh"]["week"] == "2026-10-14"
    )
    assert calls[0]["periods"] == {"week": ["2026-10-16"]}


def test_final_completion_uses_source_observation_without_requiring_every_stock_cutoff_equal():
    from orchestrator.defs.stock_period_update import (
        CalendarDays,
        no_trading_period,
        source_final,
    )

    days = CalendarDays([(date(2026, 10, d), 1) for d in range(12, 17)])
    assert not source_final("2026-10-16", "week", "20261015", date(2026, 10, 16), days)
    assert source_final("2026-10-16", "week", "20261016", date(2026, 10, 16), days)
    assert not source_final("2026-10-16", "week", None, date(2026, 10, 16), days)
    holiday = CalendarDays([(date(2026, 2, d), 0) for d in range(16, 21)])
    assert no_trading_period("2026-02-20", "week", holiday)
    with pytest.raises(ValueError, match="coverage_missing"):
        no_trading_period("2026-02-20", "week", CalendarDays([]))
