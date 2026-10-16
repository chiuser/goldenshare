"""Sensor previews: preserve old cursor evidence, plan debt, never request source or write data."""

from datetime import datetime
from types import SimpleNamespace as NS

import pytest

from orchestrator.defs.io.stock_period_raw import atomic_json, connection
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursors import (
    build_sensor_cursor,
    load_sensor_cursor,
)
from orchestrator.defs.stock_period_update import evaluate_daily_sensor

NOW = datetime.fromisoformat("2026-10-19T19:30:00+08:00")


def exercise_sensor(tmp_path, freq):
    root = tmp_path / "lake"
    staging = tmp_path / "staging"
    seen = []

    def runs(**kw):
        seen.append(kw)
        return []

    ctx = NS(
        cursor=build_sensor_cursor(
            evaluated_at=NOW,
            decision="skip",
            details={
                "summary": "old evidence",
                "next_action": "wait",
                "runtime_state": {
                    "verified_through": "2026-09-25",
                    "adjusted_delivery_revision": 1785,
                },
            },
        ),
        instance=NS(get_runs=runs),
        resources=NS(lake_root=NS(root=lambda: root)),
    )
    p = silver_trade_calendar_path(root)
    p.parent.mkdir(parents=True)
    with connection(tmp_path / "fixture") as con:
        # Contract: SILVER_TRADE_CALENDAR_SCHEMA, not Raw trade_cal fields.
        con.sql(
            "SELECT 'SSE' exchange,DATE '2026-10-19' trade_date,"
            "true is_open,NULL::DATE pretrade_date"
        ).write_parquet(str(p))
    atomic_json(staging / "stock_period/baseline.json", {"status": "ready"})
    atomic_json(
        staging / "stock_period/daily.json",
        {
            "completed_through": {"week": "2026-10-09", "month": "2026-08"},
            "last_refresh": {},
        },
    )
    result = evaluate_daily_sensor(ctx, NOW, freq=freq, staging_root=staging)
    assert len(result.run_requests) == 1 and len(seen) == 2
    request = result.run_requests[0]
    assert request.partition_key == ("2026-10-23" if freq == "week" else "2026-10")
    runtime = load_sensor_cursor(result.cursor)["details"]["runtime_state"]
    assert (
        runtime["adjusted_delivery_revision"] == 1785
        and runtime["verified_through"] == "2026-09-25"
    )
    assert load_sensor_cursor(result.cursor)["details"]["evidence"][
        "pending_periods"
    ] == (["2026-10-16", "2026-10-23"] if freq == "week" else ["2026-09", "2026-10"])
    assert (
        request.run_config["ops"]["raw_tushare_stk_period_bar_adj_" + freq]["config"][
            "intent"
        ]
        == "daily"
    )
    return ctx, staging


def test_weekly_backlog_and_current_request_preserve_cursor(tmp_path):
    exercise_sensor(tmp_path, "week")


@pytest.mark.parametrize("freq", ["week", "month"])
def test_sensor_rejects_raw_calendar_field(tmp_path, freq):
    import duckdb

    ctx, staging = exercise_sensor(tmp_path, freq)
    original_cursor = ctx.cursor
    calendar = silver_trade_calendar_path(ctx.resources.lake_root.root())
    with connection(tmp_path / "wrong_fixture") as con:
        con.sql(
            "SELECT 'SSE' exchange,DATE '2026-10-19' cal_date,"
            "true is_open,NULL::DATE pretrade_date"
        ).write_parquet(str(calendar))
    with pytest.raises(duckdb.BinderException, match="trade_date"):
        evaluate_daily_sensor(ctx, NOW, freq=freq, staging_root=staging)
    assert ctx.cursor == original_cursor


@pytest.mark.parametrize("freq", ["week", "month"])
def test_sensor_skips_closed_calendar_day(tmp_path, freq):
    ctx, staging = exercise_sensor(tmp_path, freq)
    calendar = silver_trade_calendar_path(ctx.resources.lake_root.root())
    with connection(tmp_path / "closed_fixture") as con:
        con.sql(
            "SELECT 'SSE' exchange,DATE '2026-10-19' trade_date,"
            "false is_open,NULL::DATE pretrade_date"
        ).write_parquet(str(calendar))
    result = evaluate_daily_sensor(ctx, NOW, freq=freq, staging_root=staging)
    assert not result.run_requests and result.cursor is None
    assert result.skip_reason.skip_message == "非交易日，不请求周/月源。"


@pytest.mark.parametrize("freq", ["week", "month"])
def test_before_window_and_bootstrap_handoff_have_no_source_or_formal_reads(
    tmp_path, freq
):
    class Forbidden:
        def __getattr__(self, name):
            pytest.fail("external read before window")

    early = NS(instance=Forbidden(), resources=Forbidden(), cursor="kept")
    result = evaluate_daily_sensor(
        early,
        NOW.replace(hour=19, minute=29),
        freq=freq,
        staging_root=tmp_path / "stage",
    )
    assert not result.run_requests and result.cursor is None
    ctx = NS(instance=NS(get_runs=lambda **_: []), resources=Forbidden(), cursor="kept")
    result = evaluate_daily_sensor(ctx, NOW, freq=freq, staging_root=tmp_path / "stage")
    assert (
        not result.run_requests
        and result.cursor is None
        and not (tmp_path / "stage").exists()
    )
