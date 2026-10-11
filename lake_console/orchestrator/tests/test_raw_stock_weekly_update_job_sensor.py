"""Pure sensor previews with bounded doubles; no daemon or formal instance."""

from datetime import datetime
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.run_contracts.cursors import (
    build_sensor_cursor,
    load_sensor_cursor,
)
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
        assert key in ("2026-10-02", "2026-10-09", "2020-02-28")
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


def test_old_cursor_cannot_start_adjusted_without_bootstrap(tmp_path, monkeypatch):
    ctx, _ = context(tmp_path, monkeypatch)
    ctx.instance.tried.add(weekly_job_name(AUTOMATIC_WEEKLY_SOURCES[0]))
    result = module.evaluate_stock_weekly_update(ctx, NOW)
    assert not result.run_requests
    assert "B0" in load_sensor_cursor(result.cursor)["details"]["next_action"]
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
    assert len(observed) == 1 and not result.run_requests
    ctx.cursor = result.cursor
    again = module.evaluate_stock_weekly_update(ctx, NOW)
    assert reason(again) == "adjusted_bootstrap_required" and not again.run_requests


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
    assert reason(module.evaluate_stock_weekly_update(ctx, NOW)) == "adjusted_bootstrap_required"


def test_calendar_missing_fail_closed(tmp_path, monkeypatch):
    ctx, _ = context(tmp_path, monkeypatch)

    def missing(*args):
        raise ValueError("calendar_incomplete")

    monkeypatch.setattr(module, "load_weekly_calendar", missing)
    result = module.evaluate_stock_weekly_update(ctx, NOW)
    assert reason(result) == "weekly_readiness_blocked" and not result.run_requests


def seed_adjusted_cursor(ctx, **updates):
    details = load_sensor_cursor(module.evaluate_stock_weekly_update(ctx, NOW).cursor)["details"]
    details["runtime_state"].update(adjusted_delivery_revision=1, **updates)
    ctx.cursor = build_sensor_cursor(evaluated_at=NOW, decision="skip", details=details)


class FeedReader:
    def __init__(self, header):
        self.header, self.calls = header, []

    def next_closed_batch(self, revision):
        self.calls.append(("head", revision))
        return self.header

    def verify_empty_batch(self, header):
        self.calls.append(("empty", header.revision))


def test_adjusted_backlog_requests_actual_anchor_without_lake_scan(tmp_path, monkeypatch):
    from .stock_weekly_adj_delivery_test_support import BATCH, delivery_fixture

    ctx, observed = context(tmp_path, monkeypatch)
    seed_adjusted_cursor(ctx)
    observed.clear()
    ctx.instance.calls.clear()
    monkeypatch.setattr(module, "connect_configured_duckdb", lambda *a, **k: pytest.fail("adjusted feed scanned Lake"))
    header, _ = delivery_fixture(historical_only=True)
    reader = FeedReader(header)
    result = module.evaluate_stock_weekly_update(ctx, NOW, delivery_reader=reader)
    request = result.run_requests[0]
    assert reason(result) == "request_adjusted_batch" and not observed
    assert request.partition_key == "2020-02-28"
    assert request.run_config["ops"]["raw_tushare_stk_period_bar_adj_week"]["config"] == {
        "contract_version": 1, "delivery_batch_id": BATCH, "closure_revision": header.revision}
    assert request.tags["goldenshare/weekly_adjusted_batch_id"] == BATCH
    assert reader.calls == [("head", 1)] and len(ctx.instance.calls) <= 4
    again = module.evaluate_stock_weekly_update(ctx, NOW, delivery_reader=reader)
    assert again.run_requests[0].run_key == request.run_key


def test_empty_batch_advances_only_revision_without_fake_events_or_files(tmp_path, monkeypatch):
    from .stock_weekly_adj_delivery_test_support import delivery_fixture

    ctx, observed = context(tmp_path, monkeypatch)
    seed_adjusted_cursor(ctx)
    observed.clear()
    header, _ = delivery_fixture(empty=True)
    reader = FeedReader(header)
    result = module.evaluate_stock_weekly_update(ctx, NOW, delivery_reader=reader)
    state = load_sensor_cursor(result.cursor)["details"]["runtime_state"]
    assert reason(result) == "adjusted_empty_consumed" and not result.run_requests
    assert not result.dynamic_partitions_requests and not observed
    assert state["adjusted_delivery_revision"] == header.revision
    assert state["verified_through"] == "2026-09-25"
    assert reader.calls == [("head", 1), ("empty", header.revision)]


def test_failed_adjusted_batch_preserved_for_manual_retry_unadjusted_continues(tmp_path, monkeypatch):
    from orchestrator.defs.run_contracts.configs import (
        build_stock_weekly_adj_prod_run_config,
    )

    from .stock_weekly_adj_delivery_test_support import BATCH, delivery_fixture

    ctx, _ = context(tmp_path, monkeypatch)
    header, _ = delivery_fixture()
    pending = {"batch_id": BATCH, "revision": header.revision, "anchor": header.anchor_partition,
               "rows_written": header.rows_written, "run_key": "old-intent"}
    seed_adjusted_cursor(ctx, pending_adjusted=pending)
    original = ctx.instance.get_runs

    def get_runs(*, filters, limit):
        if not filters.statuses and filters.job_name == "raw_stk_period_bar_adj_week_update_job":
            return [SimpleNamespace(status=dg.DagsterRunStatus.FAILURE,
                                    run_config=build_stock_weekly_adj_prod_run_config(BATCH, header.revision))]
        return original(filters=filters, limit=limit)

    ctx.instance.get_runs = get_runs
    reader = FeedReader(header)
    result = module.evaluate_stock_weekly_update(ctx, NOW, delivery_reader=reader)
    assert result.run_requests[0].job_name == "raw_stk_period_bar_week_update_job"
    state = load_sensor_cursor(result.cursor)["details"]["runtime_state"]
    assert state["pending_adjusted"] == pending and state["adjusted_delivery_revision"] == 1
    assert not reader.calls
    assert "重试同批" in load_sensor_cursor(result.cursor)["details"]["next_action"]


def test_zero_is_not_a_bootstrap_revision_and_before_window_never_reads_feed(tmp_path, monkeypatch):
    ctx, _ = context(tmp_path, monkeypatch)
    seed_adjusted_cursor(ctx)
    details = load_sensor_cursor(ctx.cursor)["details"]
    details["runtime_state"]["adjusted_delivery_revision"] = 0
    ctx.cursor = build_sensor_cursor(evaluated_at=NOW, decision="skip", details=details)
    reader = FeedReader(None)
    result = module.evaluate_stock_weekly_update(ctx, NOW, delivery_reader=reader)
    assert not reader.calls
    assert "无法安全核验" in load_sensor_cursor(result.cursor)["details"]["next_action"]
    result = module.evaluate_stock_weekly_update(ctx, datetime.fromisoformat("2026-10-04T19:29:59+08:00"), delivery_reader=reader)
    assert reason(result) == "before_daily_start" and not reader.calls
