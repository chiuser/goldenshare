from pathlib import Path

from orchestrator.defs.assets.dc_board_raw import (
    raw_tushare_dc_daily,
    raw_tushare_dc_index,
    raw_tushare_dc_member,
)
from orchestrator.defs.assets.dc_board_silver import (
    silver_dc_daily,
    silver_dc_index,
    silver_dc_member,
)
from orchestrator.defs.checks.dc_board_silver_checks import (
    silver_dc_daily_core_check,
    silver_dc_index_core_check,
    silver_dc_member_core_check,
)
from orchestrator.defs.partitions import cn_a_index_trade_days


def test_m5_silver_assets_and_checks_are_partitioned_and_raw_bound():
    assets = (silver_dc_index, silver_dc_member, silver_dc_daily)
    raw_assets = (raw_tushare_dc_index, raw_tushare_dc_member, raw_tushare_dc_daily)
    checks = (
        silver_dc_index_core_check,
        silver_dc_member_core_check,
        silver_dc_daily_core_check,
    )

    for asset, raw_asset in zip(assets, raw_assets, strict=True):
        assert asset.partitions_def is cn_a_index_trade_days
        assert raw_asset.key in asset.dependency_keys

    assert {spec.name for spec in silver_dc_index_core_check.check_specs} == {
        "silver_dc_index_core_check"
    }
    assert {spec.name for spec in silver_dc_member_core_check.check_specs} == {
        "silver_dc_member_core_check"
    }
    assert {spec.name for spec in silver_dc_daily_core_check.check_specs} == {
        "silver_dc_daily_core_check"
    }
    for check in checks:
        assert tuple(check.check_specs)[0].asset_key in {
            asset.key for asset in assets
        }


def test_m5_does_not_add_jobs_or_sensors():
    jobs_dir = Path("src/orchestrator/defs/jobs")
    sensors_dir = Path("src/orchestrator/defs/sensors")
    assert not list(jobs_dir.glob("dc_board_silver*.py"))
    assert not list(sensors_dir.glob("dc_board_silver*.py"))
