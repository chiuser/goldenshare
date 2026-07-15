from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import dagster as dg

from orchestrator.defs.jobs.dc_daily_technical_repair import (
    gold_dc_daily_technical_repair_job,
)
from orchestrator.defs.sensors import dc_daily_technical_repair_sensor
from tests.test_dc_daily_technical_repair import _MemoryDuckDB, _batch, _dates, _write_fixture


class _FakeInstance:
    def __init__(self, registered):
        self.registered = tuple(registered)

    def get_dynamic_partitions(self, _name):
        return list(self.registered)

    def get_event_records(self, *_args, **_kwargs):
        raise AssertionError("Gold repair sensor must not read event history")


def _context(root: Path, dates: tuple[str, ...], run_id: str, tags):
    resource = _MemoryDuckDB()
    return (
        SimpleNamespace(
            dagster_run=SimpleNamespace(run_id=run_id, tags=dict(tags)),
            cursor=None,
            instance=_FakeInstance(dates),
            resources=SimpleNamespace(
                lake_root=SimpleNamespace(
                    ensure_available_for_run=lambda: None,
                    root=lambda: root,
                ),
                duckdb=resource,
            ),
        ),
        resource,
    )


def _evaluate(context):
    return dc_daily_technical_repair_sensor.gold_dc_daily_technical_repair_job_sensor._run_status_sensor_fn(
        context
    )


def test_sensor_submits_one_upstream_triggered_request_from_scalar_tags(tmp_path: Path):
    dates = _dates()
    _write_fixture(tmp_path, dates)
    batch = _batch(tmp_path, dates)
    context, resource = _context(
        tmp_path,
        dates,
        batch.producer_run_id,
        {**batch.to_run_tags()},
    )

    result = _evaluate(context)

    assert isinstance(result, dg.RunRequest)
    assert result.run_key == f"gold_dc_daily_technical_repair:{batch.upstream_batch_id}"
    assert result.run_config == {
        "ops": {
            "gold_dc_daily_technical_repair_op": {
                "config": batch.to_payload(),
            }
        }
    }
    assert resource.connection_count == 1


def test_sensor_skips_producer_run_id_mismatch(tmp_path: Path):
    dates = _dates()
    _write_fixture(tmp_path, dates)
    batch = _batch(tmp_path, dates)
    context, _ = _context(
        tmp_path,
        dates,
        "different-producer-run",
        batch.to_run_tags(),
    )

    result = _evaluate(context)

    assert isinstance(result, dg.SkipReason)
    assert "producer_run_id_mismatch" in result.skip_message


def test_sensor_skips_non_ready_or_missing_batch_without_duckdb(tmp_path: Path):
    context, resource = _context(tmp_path, _dates(), "producer-run", {})

    result = _evaluate(context)

    assert isinstance(result, dg.SkipReason)
    assert "batch_not_ready" in result.skip_message
    assert resource.connection_count == 0


def test_sensor_is_stopped_and_does_not_scan_history():
    sensor = dc_daily_technical_repair_sensor.gold_dc_daily_technical_repair_job_sensor
    assert sensor.default_status == dg.DefaultSensorStatus.STOPPED
    source = Path("src/orchestrator/defs/sensors/dc_daily_technical_repair_sensor.py").read_text()
    assert "get_event_records" not in source
    assert "partition_dataset_readiness_status_from_latest_checks" not in source
    assert "@dg.run_status_sensor" in source
    assert gold_dc_daily_technical_repair_job.name == "gold_dc_daily_technical_repair_job"
