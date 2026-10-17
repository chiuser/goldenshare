"""Literal clock and progress regressions from the 2026-10-17 risk audit.

Source responses use the existing public-contract fixtures; network and native
submission boundaries are replaced. These tests do not prove HTTP termination.
"""

from pathlib import Path

import pytest

from orchestrator.defs.source_readiness.moneyflow import collect_market_moneyflow
from orchestrator.defs.source_readiness.moneyflow_daily import collect_daily_moneyflow
from orchestrator.moneyflow_continuation.execution import apply, inspect
from orchestrator.moneyflow_continuation.plan import request_for
from tests.test_moneyflow_continuation_plan import AT, plan_for
from tests.test_moneyflow_continuation_submission import FakeNative
from tests.test_moneyflow_moneyflow import DAY, Source, row
from tests.test_moneyflow_moneyflow_mkt_dc import Source as MarketSource
from tests.test_moneyflow_moneyflow_mkt_dc import row as market_row

pytestmark = pytest.mark.usefixtures("isolated_moneyflow_transport")


class AdvancingClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        self.now += 0.0001
        return self.now

    def sleep(self, seconds):
        assert seconds > 0, "sleep must remain positive when guard crosses 60s"
        self.sleeps.append(seconds)
        self.now += max(0, seconds - 0.00015)


@pytest.mark.parametrize("kind", ["daily", "market"])
def test_guard_crosses_wait_boundary_without_negative_sleep(kind):
    clock = AdvancingClock()
    source = (
        Source([[row()], [row()]])
        if kind == "daily"
        else MarketSource([[market_row()], [market_row()]])
    )
    common = {
        "tushare": source,
        "trade_date": DAY,
        "clock": clock,
        "sleep_fn": clock.sleep,
    }
    if kind == "daily":
        result = collect_daily_moneyflow(
            **common,
            dataset="moneyflow",
            consume_page=lambda *_: None,
            complete_round=lambda *_: None,
        )
    else:
        result = collect_market_moneyflow(**common, on_first_round=lambda *_: None)
    assert result.stability_gap_seconds >= 60
    assert len(source.calls) == 2 and min(clock.sleeps) > 0


def partially_failed_native():
    plan = plan_for(days=("2026-10-08", "2026-10-09"))
    native = FakeNative()
    for unit in plan["units"]:
        native.registered.add((unit["dataset"], unit["trade_date"]))
    for layer in ("raw", "silver"):
        unit = plan["units"][0]
        native.native[(unit["dataset"], unit["trade_date"], layer)] = {
            "run_id": layer + "-done",
            "status": "SUCCESS",
            "body": request_for(unit, layer, AT.date().isoformat(), "b" * 64),
        }
    unit = plan["units"][1]
    native.native[(unit["dataset"], unit["trade_date"], "raw")] = {
        "run_id": "failed-raw",
        "status": "FAILURE",
        "body": request_for(unit, "raw", AT.date().isoformat()),
    }
    return plan, native


def test_failed_later_unit_preserves_actual_completed_progress(tmp_path):
    plan, native = partially_failed_native()
    code, report = apply(
        native,
        plan,
        root=Path(tmp_path),
        clock=lambda: AT,
        output=lambda _: None,
    )
    assert code == 3
    assert report["completed"] == 1 and report["remaining"] == 1
    assert native.posts == []


def test_inspect_keeps_both_completed_and_failed_unit_facts(tmp_path):
    plan, native = partially_failed_native()
    report = inspect(native, plan, root=Path(tmp_path))
    assert len(report["units"]) == 2
    assert report["units"][0]["next"] == "complete"
    assert report["units"][1]["reason"] == "native_run_failed"
    assert report["completed"] == 1 and not report["complete"]
    assert native.posts == []
