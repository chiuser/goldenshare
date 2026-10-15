"""Retired identities fail before source, target creation or frozen-plan reuse."""

from dataclasses import replace
import json
import pytest
from orchestrator.defs.bootstrap.stock_weekly_history_cli import load_inventory
from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_asset_key,
)
from orchestrator.defs.run_contracts.stock_monthly import (
    StockMonthlySource,
    monthly_asset_key,
)
from orchestrator.defs.stock_monthly_point import deliver_month_intent
from orchestrator.defs.catalog.lake_assets import LAKE_ASSET_CATALOG
from .stock_weekly_capture_test_support import prod_plan


@pytest.mark.parametrize("source", ["primary_unadjusted", "weekly"])
def test_retired_source_rejected_before_work(tmp_path, source):
    for resolve in (
        StockWeeklySource,
        StockMonthlySource,
        weekly_asset_key,
        monthly_asset_key,
    ):
        with pytest.raises(ValueError):
            resolve(source)
    with pytest.raises(ValueError):
        replace(prod_plan(), source=source)
    with pytest.raises(ValueError):
        deliver_month_intent(
            source,
            "2026-08",
            target_root=tmp_path / "lake",
            staging_root=tmp_path / "stage",
            worker=None,
            execution_id="offline",
            upstream_bindings=lambda _: pytest.fail("upstream called"),
            fetch=lambda *_: pytest.fail("source called"),
        )
    assert not (tmp_path / "lake").exists() and not (tmp_path / "stage").exists()


@pytest.mark.parametrize(
    "kind,source",
    [
        ("weekly_history_inventory", "weekly"),
        ("prod_weekly_inventory", "primary_unadjusted"),
    ],
)
def test_retired_inventory_is_rejected_before_old_proofs_are_read(
    tmp_path, kind, source
):
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "kind": kind,
                "version": 1,
                "source": source,
                "candidates": {"path": "/not-read"},
            }
        )
    )
    with pytest.raises((ValueError, WeeklyCaptureError)):
        load_inventory(inventory)


def test_catalog_contains_only_retained_period_sources():
    keys = {x.asset_key for x in LAKE_ASSET_CATALOG}
    assert {
        "raw_tushare_stk_period_bar_week",
        "raw_tushare_stk_period_bar_month",
        "raw_tushare_weekly",
    }.isdisjoint(keys)
    assert {
        "raw_tushare_stk_period_bar_adj_week",
        "raw_tushare_stk_period_bar_adj_month",
    } <= keys
