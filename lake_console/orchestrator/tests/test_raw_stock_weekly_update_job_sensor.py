"""Pure sensor previews with bounded doubles; no daemon or formal instance."""

from datetime import datetime
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.run_contracts.cursors import load_sensor_cursor
from orchestrator.defs.run_contracts.stock_weekly import weekly_job_name
from orchestrator.defs.sensors import raw_stock_weekly_update_job_sensor as module
from orchestrator.defs.stock_weekly_update import AUTOMATIC_WEEKLY_SOURCES

NOW = datetime.fromisoformat("2026-10-04T19:30:00+08:00")


class Instance:
    def __init__(self):
        self.calls = []
        self.pending = False
        self.tried = set()

    def get_runs(self, *, filters, limit):
        assert limit == 1
        self.calls.append(filters)
        if filters.statuses:
            return [object()] if self.pending else []
        return [object()] if filters.job_name in self.tried else []

    def has_dynamic_partition(self, name, key):
        assert key == "2026-10-02"
        return False


def context(tmp_path, monkeypatch, statuses=None, days=("2026-09-30",)):
    from contextlib import nullcontext

    instance = Instance()
    ctx = SimpleNamespace(
        cursor=None,
        instance=instance,
        resources=SimpleNamespace(lake_root=SimpleNamespace(root=lambda: tmp_path)),
    )
    observed = []

    def status(instance, root, source, week):
        observed.append((source, week))
        if week == "2026-09-25":
            pytest.fail("completed bootstrap baseline must not be reread")
        return (statuses or {}).get(source, "missing")

    monkeypatch.setattr(module, "weekly_period_status", status)
    monkeypatch.setattr(module, "weekly_upstream_events_ready", lambda *args: True)
    monkeypatch.setattr(
        module, "connect_configured_duckdb", lambda *args, **kwargs: nullcontext(None)
    )
    monkeypatch.setattr(
        module, "load_weekly_calendar", lambda connection, root, week: (days, {})
    )
    return ctx, observed


def reason(result):
    return load_sensor_cursor(result.cursor)["details"]["reason_code"]


def test_before_window_has_no_external_reads():
    class Forbidden:
        def __getattr__(self, name):
            pytest.fail(f"external read before window: {name}")

    ctx = SimpleNamespace(cursor=None, instance=Forbidden(), resources=Forbidden())
    result = module.evaluate_stock_weekly_update(
        ctx, datetime.fromisoformat("2026-10-04T19:29:59+08:00")
    )
    assert reason(result) == "before_daily_start" and not result.run_requests


def test_exact_primary_selection_stopped_and_one_run(tmp_path, monkeypatch):
    ctx, observed = context(tmp_path, monkeypatch)
    result = module.evaluate_stock_weekly_update(ctx, NOW)
    assert len(result.run_requests) == 1
    request = result.run_requests[0]
    assert request.job_name == "raw_stk_period_bar_week_update_job"
    assert request.partition_key == "2026-10-02"
    assert request.run_config == {
        "ops": {
            "raw_tushare_stk_period_bar_week": {
                "config": {"automatic_intent_date": "2026-10-04"}
            }
        }
    }
    assert all(source in AUTOMATIC_WEEKLY_SOURCES for source, week in observed)
    assert result.dynamic_partitions_requests[0].partition_keys == ["2026-10-02"]
    assert (
        module.raw_stock_weekly_update_job_sensor.default_status
        is dg.DefaultSensorStatus.STOPPED
    )
    repeated = module.evaluate_stock_weekly_update(ctx, NOW)
    assert repeated.run_requests[0].run_key == request.run_key


def test_pending_blocks_before_physical_queries(tmp_path, monkeypatch):
    ctx, observed = context(tmp_path, monkeypatch)
    ctx.instance.pending = True
    result = module.evaluate_stock_weekly_update(ctx, NOW)
    assert reason(result) == "writer_pending" and observed == []
    assert len(ctx.instance.calls) == 1


def test_same_day_failed_primary_does_not_stop_other_source(tmp_path, monkeypatch):
    ctx, _ = context(tmp_path, monkeypatch)
    ctx.instance.tried.add(weekly_job_name(AUTOMATIC_WEEKLY_SOURCES[0]))
    result = module.evaluate_stock_weekly_update(ctx, NOW)
    assert result.run_requests[0].job_name == "raw_stk_period_bar_adj_week_update_job"
    ctx.instance.tried.add(weekly_job_name(AUTOMATIC_WEEKLY_SOURCES[1]))
    again = module.evaluate_stock_weekly_update(ctx, NOW)
    assert not again.run_requests and reason(again) == "daily_intent_already_submitted"
    assert len(again.cursor.encode()) <= 2048


@pytest.mark.parametrize(
    "status", ["checks_failed_or_stale", "orphan_file", "formal_file_changed"]
)
def test_bad_file_is_not_auto_overwritten_or_replaced_by_alternate(
    tmp_path, monkeypatch, status
):
    ctx, observed = context(
        tmp_path, monkeypatch, dict.fromkeys(AUTOMATIC_WEEKLY_SOURCES, status)
    )
    result = module.evaluate_stock_weekly_update(ctx, NOW)
    assert reason(result) == status and not result.run_requests
    assert all(source in AUTOMATIC_WEEKLY_SOURCES for source, week in observed)


def test_two_verified_sources_advance_only_one_period(tmp_path, monkeypatch):
    ctx, observed = context(
        tmp_path, monkeypatch, dict.fromkeys(AUTOMATIC_WEEKLY_SOURCES, "ready")
    )
    result = module.evaluate_stock_weekly_update(ctx, NOW)
    runtime = load_sensor_cursor(result.cursor)["details"]["runtime_state"]
    assert runtime["verified_through"] == "2026-10-02"
    assert len(observed) == 2 and not result.run_requests
    ctx.cursor = result.cursor
    again = module.evaluate_stock_weekly_update(ctx, NOW)
    assert reason(again) == "already_verified" and not again.run_requests


def test_closed_week_keeps_real_file_baseline(tmp_path, monkeypatch):
    ctx, _ = context(tmp_path, monkeypatch, days=())
    result = module.evaluate_stock_weekly_update(ctx, NOW)
    runtime = load_sensor_cursor(result.cursor)["details"]["runtime_state"]
    assert reason(result) == "no_trading_week"
    assert runtime == {
        "verified_through": "2026-09-25",
        "examined_through": "2026-10-02",
        "policy_version": "completed-week-v1",
    }
    ctx.cursor = result.cursor
    assert reason(module.evaluate_stock_weekly_update(ctx, NOW)) == "already_verified"


def test_calendar_missing_fail_closed(tmp_path, monkeypatch):
    ctx, _ = context(tmp_path, monkeypatch)

    def missing(*args):
        raise ValueError("calendar_incomplete")

    monkeypatch.setattr(module, "load_weekly_calendar", missing)
    result = module.evaluate_stock_weekly_update(ctx, NOW)
    assert reason(result) == "weekly_readiness_blocked" and not result.run_requests
