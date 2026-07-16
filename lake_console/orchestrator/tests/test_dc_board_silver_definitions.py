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
from orchestrator.defs.jobs.dc_board_silver import (
    silver_dc_daily_update_job,
    silver_dc_index_update_job,
    silver_dc_member_update_job,
)
from orchestrator.defs.sensors.dc_board_silver_sensor import (
    silver_dc_daily_update_job_sensor,
    silver_dc_index_update_job_sensor,
    silver_dc_member_update_job_sensor,
)
from orchestrator.defs.partitions import (
    cn_a_dc_daily_trade_days,
    cn_a_dc_index_trade_days,
    cn_a_dc_member_trade_days,
)


def test_m5_silver_assets_and_checks_are_partitioned_and_raw_bound():
    assets = (silver_dc_index, silver_dc_member, silver_dc_daily)
    raw_assets = (raw_tushare_dc_index, raw_tushare_dc_member, raw_tushare_dc_daily)
    checks = (
        silver_dc_index_core_check,
        silver_dc_member_core_check,
        silver_dc_daily_core_check,
    )

    assert silver_dc_index.partitions_def is cn_a_dc_index_trade_days
    assert silver_dc_member.partitions_def is cn_a_dc_member_trade_days
    assert silver_dc_daily.partitions_def is cn_a_dc_daily_trade_days
    for asset, raw_asset in zip(assets, raw_assets, strict=True):
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


def test_m6_adds_silver_jobs_and_sensors_in_separate_modules():
    jobs_dir = Path("src/orchestrator/defs/jobs")
    sensors_dir = Path("src/orchestrator/defs/sensors")
    assert (jobs_dir / "dc_board_silver.py").exists()
    assert (sensors_dir / "dc_board_silver_sensor.py").exists()


def test_m6_silver_jobs_and_sensors_are_single_partition_stopped_definitions():
    jobs = (
        silver_dc_index_update_job,
        silver_dc_member_update_job,
        silver_dc_daily_update_job,
    )
    sensors = (
        silver_dc_index_update_job_sensor,
        silver_dc_member_update_job_sensor,
        silver_dc_daily_update_job_sensor,
    )
    assert {job.name for job in jobs} == {
        "silver_dc_index_update_job",
        "silver_dc_member_update_job",
        "silver_dc_daily_update_job",
    }
    for sensor in sensors:
        assert sensor.default_status.value == "STOPPED"
    source = Path("src/orchestrator/defs/jobs/dc_board_silver.py").read_text()
    assert source.count("AssetSelection.assets") == 3
    assert "AssetSelection.assets(raw_" not in source
    assert "AssetSelection.checks_for_assets" in source
