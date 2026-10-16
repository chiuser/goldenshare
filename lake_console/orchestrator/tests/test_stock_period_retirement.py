"""Retired datasets, old plans and write parameters are rejected before doing any IO."""

import pytest

from orchestrator.defs.catalog.lake_assets import LAKE_ASSET_CATALOG
from orchestrator.defs.run_contracts.stock_monthly import (
    StockMonthlySource,
    monthly_asset_key,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_asset_key,
)


@pytest.mark.parametrize("source", ["primary_unadjusted", "weekly", "monthly"])
def test_retired_source_rejected(source):
    for resolve in (
        StockWeeklySource,
        StockMonthlySource,
        weekly_asset_key,
        monthly_asset_key,
    ):
        with pytest.raises(ValueError):
            resolve(source)


def test_all_old_mutating_cli_parameters_reject_before_io(tmp_path):
    from orchestrator.defs.bootstrap.stock_monthly_events_cli import main as monthevents
    from orchestrator.defs.bootstrap.stock_monthly_history_cli import main as monthly
    from orchestrator.defs.bootstrap.stock_weekly_events_cli import main as weekevents
    from orchestrator.defs.bootstrap.stock_weekly_history_cli import main as weekly

    for entry in (weekly, monthly, weekevents, monthevents):
        with pytest.raises(ValueError, match="retired"):
            entry(["apply", "--plan", str(tmp_path / "does-not-exist.json")])
    assert list(tmp_path.iterdir()) == []


def test_catalog_retains_only_the_two_direct_source_period_datasets():
    entries = {e.asset_key: e for e in LAKE_ASSET_CATALOG}
    assert {
        "raw_tushare_stk_period_bar_week",
        "raw_tushare_stk_period_bar_month",
        "raw_tushare_weekly",
    }.isdisjoint(entries)
    for freq in ("week", "month"):
        entry = entries["raw_tushare_stk_period_bar_adj_" + freq]
        assert entry.source_api == "stk_week_month_adj"
        assert len(entry.ingestion_sources) == 1
