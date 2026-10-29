from datetime import date

import pytest

from orchestrator.defs.paths import silver_stock_lifecycle_path
from orchestrator.defs.stock_period_update import close_day, daily_periods
from tests.factor_repair_fixtures import write_repair_lifecycle


def test_calendar_consumer_reads_real_producer_contract(tmp_path):
    from orchestrator.defs.duckdb_sql import silver_trade_calendar_select
    from orchestrator.defs.io.stock_period_raw import connection
    from orchestrator.defs.paths import (
        raw_trade_calendar_path,
        silver_trade_calendar_path,
    )
    from orchestrator.defs.stock_period_update import calendar_days

    root = tmp_path / "lake"
    source = raw_trade_calendar_path(root)
    calendar = silver_trade_calendar_path(root)
    source.parent.mkdir(parents=True)
    calendar.parent.mkdir(parents=True)
    # Real producer: duckdb_sql.silver_trade_calendar_select. Independent schema
    # witness: run_contracts.asset_column_schemas.SILVER_TRADE_CALENDAR_SCHEMA.
    with connection(tmp_path / "fixtures") as con:
        con.sql(
            "SELECT * FROM (VALUES ('SSE','20261015',1,'20261014'),"
            "('SSE','20261016',1,'20261015'),('SSE','20261017',0,'20261016'),"
            "('SZSE','20261018',1,'20261016')) "
            "t(exchange,cal_date,is_open,pretrade_date)"
        ).write_parquet(str(source))
        con.sql(silver_trade_calendar_select(source)).write_parquet(str(calendar))
        observed = con.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(calendar)]
        ).fetchall()
        assert [(row[0], row[1]) for row in observed] == [
            ("exchange", "VARCHAR"),
            ("trade_date", "DATE"),
            ("is_open", "BOOLEAN"),
            ("pretrade_date", "DATE"),
        ]
        assert con.execute(
            "SELECT trade_date,is_open,pretrade_date FROM read_parquet(?) "
            "WHERE exchange='SSE' ORDER BY trade_date",
            [str(calendar)],
        ).fetchall() == [
            (date(2026, 10, 15), True, date(2026, 10, 14)),
            (date(2026, 10, 16), True, date(2026, 10, 15)),
            (date(2026, 10, 17), False, date(2026, 10, 16)),
        ]

    days = calendar_days(root, tmp_path / "consumer")
    assert days == ["2026-10-15", "2026-10-16"]
    assert days.covered == {"2026-10-15", "2026-10-16", "2026-10-17"}


def test_calendar_consumer_rejects_raw_field_at_silver_path(tmp_path):
    import duckdb

    from orchestrator.defs.io.stock_period_raw import connection
    from orchestrator.defs.paths import silver_trade_calendar_path
    from orchestrator.defs.stock_period_update import calendar_days

    root = tmp_path / "lake"
    calendar = silver_trade_calendar_path(root)
    calendar.parent.mkdir(parents=True)
    # Deliberately wrong: Raw cal_date cannot stand in for Silver trade_date.
    with connection(tmp_path / "fixtures") as con:
        con.sql(
            "SELECT 'SSE' exchange,DATE '2026-10-16' cal_date,"
            "true is_open,NULL::DATE pretrade_date"
        ).write_parquet(str(calendar))
    with pytest.raises(duckdb.BinderException, match="trade_date"):
        calendar_days(root, tmp_path / "consumer")


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
        # Silver calendar contract: trade_date DATE, is_open BOOLEAN.
        con.sql(
            "SELECT 'SSE' exchange,unnest(['2026-10-15','2026-10-16'])::DATE trade_date,"
            "true is_open,NULL::DATE pretrade_date"
        ).write_parquet(str(calendar))
        for day, factor in [("2026-10-15", 1), ("2026-10-16", 2)]:
            path = silver_adj_factor_path(root, day)
            path.parent.mkdir(parents=True)
            con.sql(
                "SELECT '000001.SZ' ts_code,?::DATE trade_date,?::DOUBLE adj_factor "
                "UNION ALL SELECT '000002.SZ',?::DATE,1",
                params=[day, factor, day],
            ).write_parquet(str(path))
    atomic_json(
        staging / "stock_period/baseline.json",
        {"status": "ready", "listed": ["000001.SZ", "000002.SZ"]},
    )
    atomic_json(
        staging / "stock_period/daily.json",
        {
            "completed_through": {"week": "2026-10-16", "month": "2026-09"},
            "last_refresh": {"week": "2026-10-16"},
            "factor_through": "2026-10-15",
        },
    )
    write_repair_lifecycle(silver_stock_lifecycle_path(root), [
        {"ts_code": "000001.SZ"}, {"ts_code": "000002.SZ"},
    ])
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
            "SELECT 'SSE' exchange,unnest(['2026-10-12','2026-10-13','2026-10-14',"
            "'2026-10-15','2026-10-16'])::DATE trade_date,true is_open,NULL::DATE pretrade_date"
        ).write_parquet(str(calendar))
    atomic_json(
        staging / "stock_period/baseline.json",
        {"status": "ready", "listed": ["000001.SZ"]},
    )
    atomic_json(
        staging / "stock_period/daily.json",
        {
            "completed_through": {"week": "2026-10-09", "month": "2026-09"},
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
