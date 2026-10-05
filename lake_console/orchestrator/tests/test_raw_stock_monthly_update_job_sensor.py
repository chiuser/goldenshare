"""Sensor previews use doubles and never write events, partitions or lake files."""

from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.run_contracts.cursors import load_sensor_cursor
from orchestrator.defs.run_contracts.stock_monthly import (
    StockMonthlySource,
    monthly_job_name,
)
from orchestrator.defs.sensors import raw_stock_monthly_update_job_sensor as module

NOW = datetime.fromisoformat("2026-11-01T19:30:00+08:00")
SOURCES = tuple(StockMonthlySource)


class Instance:
    def __init__(self):
        self.pending = False
        self.tried = set()

    def get_runs(self, *, filters, limit):
        assert limit == 1
        if filters.statuses:
            return [object()] if self.pending else []
        return [object()] if filters.job_name in self.tried else []

    def has_dynamic_partition(self, name, key):
        assert name == "cn_a_stock_months" and key == "2026-10"
        return False


def context(
    tmp_path,
    monkeypatch,
    statuses=None,
    baseline="ready",
    days=("2026-10-30",),
    upstream=True,
):
    seen = []

    def status(instance, root, source, month):
        seen.append((source, month))
        return (
            baseline if month == "2026-09" else (statuses or {}).get(source, "missing")
        )

    monkeypatch.setattr(module, "monthly_period_status", status)
    monkeypatch.setattr(
        module,
        "monthly_upstream_bindings",
        lambda *args: {"ids": [1]} if upstream else None,
    )
    monkeypatch.setattr(
        module, "connect_configured_duckdb", lambda *args, **kwargs: nullcontext(None)
    )
    monkeypatch.setattr(module, "load_monthly_calendar", lambda *args: (days, {}))
    return SimpleNamespace(
        cursor=None,
        instance=Instance(),
        resources=SimpleNamespace(lake_root=SimpleNamespace(root=lambda: tmp_path)),
    ), seen


def reason(result):
    return load_sensor_cursor(result.cursor)["details"]["reason_code"]


def test_before_start_zero_external_reads():
    class Forbidden:
        def __getattr__(self, name):
            pytest.fail("external access before window")

    result = module.evaluate_stock_monthly_update(
        SimpleNamespace(cursor=None, instance=Forbidden(), resources=Forbidden()),
        datetime.fromisoformat("2026-11-01T19:29:59+08:00"),
    )
    assert reason(result) == "before_daily_start" and not result.run_requests


def test_stopped_exact_request_and_stable_daily_key(tmp_path, monkeypatch):
    ctx, seen = context(tmp_path, monkeypatch)
    result = module.evaluate_stock_monthly_update(ctx, NOW)
    request = result.run_requests[0]
    assert (
        request.job_name == "raw_stk_period_bar_month_update_job"
        and request.partition_key == "2026-10"
    )
    assert request.run_config == {
        "ops": {
            "raw_tushare_stk_period_bar_month": {
                "config": {"automatic_intent_date": "2026-11-01"}
            }
        }
    }
    assert result.dynamic_partitions_requests[0].partition_keys == ["2026-10"]
    assert (
        module.raw_stock_monthly_update_job_sensor.default_status
        is dg.DefaultSensorStatus.STOPPED
    )
    assert (
        module.evaluate_stock_monthly_update(ctx, NOW).run_requests[0].run_key
        == request.run_key
    )
    assert all(source in SOURCES for source, month in seen)


def test_pending_precedes_physical_scan(tmp_path, monkeypatch):
    ctx, seen = context(tmp_path, monkeypatch)
    ctx.instance.pending = True
    assert (
        reason(module.evaluate_stock_monthly_update(ctx, NOW)) == "writer_pending"
        and not seen
    )


@pytest.mark.parametrize(
    "baseline",
    ["missing", "orphan_file", "checks_failed_or_stale", "delivery_evidence_missing"],
)
def test_no_fake_bootstrap_baseline(tmp_path, monkeypatch, baseline):
    ctx, _ = context(tmp_path, monkeypatch, baseline=baseline)
    result = module.evaluate_stock_monthly_update(ctx, NOW)
    assert reason(result) == "baseline_not_ready" and not result.run_requests


def test_current_month_not_requested(tmp_path, monkeypatch):
    ctx, _ = context(tmp_path, monkeypatch)
    result = module.evaluate_stock_monthly_update(
        ctx, datetime.fromisoformat("2026-10-05T19:30:00+08:00")
    )
    assert reason(result) == "already_verified" and not result.run_requests


def test_same_day_failure_allows_other_source_then_waits(tmp_path, monkeypatch):
    ctx, _ = context(tmp_path, monkeypatch)
    ctx.instance.tried = {monthly_job_name(SOURCES[0])}
    result = module.evaluate_stock_monthly_update(ctx, NOW)
    assert result.run_requests[0].job_name == monthly_job_name(SOURCES[1])
    ctx.instance.tried = {monthly_job_name(s) for s in SOURCES}
    again = module.evaluate_stock_monthly_update(ctx, NOW)
    assert reason(again) == "daily_intent_already_submitted" and not again.run_requests
    assert len(again.cursor.encode()) < 2048


def test_verified_month_advances_one_debt_only(tmp_path, monkeypatch):
    ctx, _ = context(tmp_path, monkeypatch, statuses=dict.fromkeys(SOURCES, "ready"))
    result = module.evaluate_stock_monthly_update(ctx, NOW)
    assert reason(result) == "period_verified"
    ctx.cursor = result.cursor
    again = module.evaluate_stock_monthly_update(ctx, NOW)
    assert reason(again) == "already_verified"


def test_upstream_failure_never_requests_source(tmp_path, monkeypatch):
    ctx, _ = context(tmp_path, monkeypatch, upstream=False)
    assert (
        reason(module.evaluate_stock_monthly_update(ctx, NOW))
        == "monthly_upstream_not_ready"
    )


@pytest.mark.parametrize(
    "status", ["orphan_file", "checks_failed_or_stale", "formal_file_or_proof_changed"]
)
def test_orphan_or_changed_file_not_overwritten(tmp_path, monkeypatch, status):
    ctx, _ = context(tmp_path, monkeypatch, statuses=dict.fromkeys(SOURCES, status))
    result = module.evaluate_stock_monthly_update(ctx, NOW)
    assert reason(result) == status and not result.run_requests
