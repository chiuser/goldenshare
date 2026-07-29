from pathlib import Path

from orchestrator.defs.sensors.silver_index_global_sensor import (
    silver_index_global_update_job_sensor,
)


DEFS = Path("src/orchestrator/defs")


def test_p6_sensor_modules_use_shared_cursor_and_run_contract_builders():
    sources = {
        path.name: path.read_text()
        for path in (
            DEFS / "sensors" / "global_index_partition_sensor.py",
            DEFS / "sensors" / "index_global_sensor.py",
            DEFS / "sensors" / "index_global_retry_sensor.py",
            DEFS / "sensors" / "index_global_late_empty_sensor.py",
            DEFS / "sensors" / "silver_index_global_sensor.py",
            DEFS / "sensors" / "silver_index_global_retry_sensor.py",
        )
    }
    for name, source in sources.items():
        assert "build_sensor_cursor" in source or "run_status_sensor" in source
        assert "get_event_records" not in source
        assert "get_asset_check_execution_history" not in source
        assert "run_key=f" not in source
    assert "build_index_global_raw_run_config" in sources["index_global_sensor.py"]
    assert "build_index_global_silver_run_config" in sources["silver_index_global_sensor.py"]
    assert "parse_index_global_raw_run_config" in sources["index_global_retry_sensor.py"]
    assert "parse_index_global_silver_run_config" in sources["silver_index_global_retry_sensor.py"]


def test_p6_sensors_are_bounded_and_stopped_by_default():
    for filename in (
        "global_index_partition_sensor.py",
        "index_global_sensor.py",
        "index_global_retry_sensor.py",
        "index_global_late_empty_sensor.py",
        "silver_index_global_sensor.py",
        "silver_index_global_retry_sensor.py",
    ):
        source = (DEFS / "sensors" / filename).read_text()
        assert "default_status=dg.DefaultSensorStatus.STOPPED" in source
    assert "GLOBAL_INDEX_REPLAY_SLOT_LIMIT" in (
        DEFS / "sensors" / "index_global_sensor.py"
    ).read_text()
    assert "GLOBAL_INDEX_LATE_EMPTY_DATE_LIMIT" in (
        DEFS / "sensors" / "index_global_late_empty_sensor.py"
    ).read_text()


def test_silver_sensor_invalid_existing_file_is_fail_closed():
    source = (DEFS / "sensors" / "silver_index_global_sensor.py").read_text()
    assert "silver_existing_check_failed" in source
    assert "silver_index_global_file_status" in source


def test_silver_sensor_declares_resources_used_by_its_evaluator():
    assert silver_index_global_update_job_sensor.required_resource_keys == {
        "lake_root",
        "duckdb",
    }
