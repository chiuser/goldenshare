from pathlib import Path
import dagster as dg

from orchestrator.defs.assets.dc_daily_technical_asset import gold_dc_daily_technical
from orchestrator.defs.checks.dc_daily_technical_checks import (
    gold_dc_daily_technical_core_check,
)
from orchestrator.defs.jobs.dc_daily_technical import gold_dc_daily_technical_update_job
from orchestrator.defs.partitions import cn_a_dc_daily_trade_days
from orchestrator.defs.sensors.dc_daily_technical_sensor import (
    gold_dc_daily_technical_update_job_sensor,
)


def test_gold_asset_and_core_check_are_single_partition_definitions() -> None:
    assert gold_dc_daily_technical.key == dg.AssetKey("gold_dc_daily_technical")
    assert gold_dc_daily_technical.partitions_def is cn_a_dc_daily_trade_days
    assert dg.AssetKey("silver_dc_daily") in gold_dc_daily_technical.dependency_keys

    check_specs = tuple(gold_dc_daily_technical_core_check.check_specs)
    assert len(check_specs) == 1
    assert check_specs[0].name == "gold_dc_daily_technical_core_check"
    assert check_specs[0].asset_key == gold_dc_daily_technical.key
    assert check_specs[0].partitions_def is cn_a_dc_daily_trade_days
    assert check_specs[0].blocking is True


def test_gold_job_selects_only_asset_and_its_check() -> None:
    source = Path("src/orchestrator/defs/jobs/dc_daily_technical.py").read_text()
    assert gold_dc_daily_technical_update_job.name == "gold_dc_daily_technical_update_job"
    assert "AssetSelection.assets(gold_dc_daily_technical)" in source
    assert "AssetSelection.checks_for_assets(gold_dc_daily_technical)" in source
    assert "AssetSelection.assets(silver" not in source


def test_gold_sensor_is_stopped_by_default_and_has_bounded_contract() -> None:
    assert gold_dc_daily_technical_update_job_sensor.default_status == dg.DefaultSensorStatus.STOPPED
    assert gold_dc_daily_technical_update_job_sensor.minimum_interval_seconds == 600
    assert gold_dc_daily_technical_update_job_sensor.job_name == (
        "gold_dc_daily_technical_update_job"
    )


def test_definition_modules_do_not_add_repair_or_event_backfill_paths() -> None:
    for relative_path in (
        "assets/dc_daily_technical_asset.py",
        "checks/dc_daily_technical_checks.py",
        "jobs/dc_daily_technical.py",
        "sensors/dc_daily_technical_sensor.py",
    ):
        source = Path("src/orchestrator/defs", relative_path).read_text()
        assert "report_runless_asset_event" not in source
        assert "repair_sensor" not in source.lower()
