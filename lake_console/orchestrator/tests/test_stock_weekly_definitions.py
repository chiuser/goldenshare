"""Retained weekly definitions and rejected retired write entries, entirely offline."""

import importlib.util

import dagster as dg
import pytest
from pydantic import ValidationError

from orchestrator.defs.assets import stock_weekly as assets
from orchestrator.defs.checks import stock_weekly_checks as checks
from orchestrator.defs.jobs import stock_weekly as jobs
from orchestrator.defs.run_contracts.configs import StockPeriodRawConfig
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_check_names,
)


def definition_for(tmp_path, source):
    from orchestrator.defs.resources import LakeRootResource
    from orchestrator.defs.run_contracts.stock_weekly import (
        weekly_asset_key,
        weekly_job_name,
    )

    StockWeeklySource(source)
    asset = getattr(assets, weekly_asset_key(source))
    check_defs = [getattr(checks, name) for name in weekly_check_names(source)]
    definitions = dg.Definitions(
        assets=[asset],
        asset_checks=check_defs,
        jobs=[getattr(jobs, weekly_job_name(source))],
        resources={"lake_root": LakeRootResource(root_path=str(tmp_path / "lake"))},
    )
    return definitions, asset, check_defs


def test_only_retained_weekly_asset_job_and_three_checks(tmp_path):
    from orchestrator.defs.resources import LakeRootResource

    assert not hasattr(assets, "raw_tushare_stk_period_bar_week")
    assert not hasattr(assets, "raw_tushare_weekly")
    assert not hasattr(jobs, "raw_stk_period_bar_week_update_job")
    assert not hasattr(jobs, "raw_tushare_weekly_update_job")
    asset = assets.raw_tushare_stk_period_bar_adj_week
    names = weekly_check_names(StockWeeklySource.PRIMARY_ADJUSTED)
    definitions = dg.Definitions(
        assets=[asset],
        asset_checks=[getattr(checks, n) for n in names],
        jobs=[jobs.raw_stk_period_bar_adj_week_update_job],
        resources={"lake_root": LakeRootResource(root_path=str(tmp_path))},
    )
    job = definitions.resolve_job_def("raw_stk_period_bar_adj_week_update_job")
    assert job.asset_layer.executable_asset_keys == {asset.key}
    assert len(names) == 3
    assert not any(
        n.startswith(("raw_tushare_weekly_", "raw_tushare_stk_period_bar_week_"))
        for n in vars(checks)
    )


def test_retired_point_writer_modules_and_config_are_removed():
    from orchestrator.defs.run_contracts import configs

    assert importlib.util.find_spec("orchestrator.defs.stock_weekly_point") is None
    assert (
        importlib.util.find_spec("orchestrator.defs.stock_weekly_update_execution")
        is None
    )
    assert not hasattr(configs, "StockWeeklyRawConfig")
    assert not hasattr(configs, "build_stock_weekly_update_job_run_config")


@pytest.mark.parametrize(
    "extra",
    [
        {"delivery_batch_id": "old", "closure_revision": 1},
        {"code_list_path": "x"},
        {"write_mode": "force"},
    ],
)
def test_retained_job_rejects_old_prod_options(extra):
    with pytest.raises(ValidationError):
        StockPeriodRawConfig(**extra)
