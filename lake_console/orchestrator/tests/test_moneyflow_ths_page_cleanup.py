"""Cleanup fixtures follow consume_page naming and the actual THS job/check identity.

Only the terminal-state integration uses a real isolated Dagster job. No test
opens the formal instance, source service, or Lake.
"""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import dagster as dg
import pytest

import orchestrator.defs.sensors.moneyflow_ths_page_cleanup_sensor as sensors
from orchestrator.defs.io.moneyflow_candidates import moneyflow_candidate_directory
from orchestrator.defs.io.moneyflow_ths_page_cleanup import cleanup_moneyflow_ths_pages
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_THS_RAW_CHECK,
    MoneyflowContractError,
)
from orchestrator.defs.run_contracts.moneyflow_automation import (
    STOCK_THS_MONEYFLOW_AUTOMATION,
)

DAY = "2026-11-10"


def raw_run(**changes):
    return dg.DagsterRun(
        **{
            "job_name": STOCK_THS_MONEYFLOW_AUTOMATION.raw_job,
            "run_id": str(uuid4()),
            "status": dg.DagsterRunStatus.SUCCESS,
            "tags": {"dagster/partition": DAY},
            **changes,
        }
    )


def raw_check(**changes):
    return SimpleNamespace(
        **{
            "passed": True,
            "asset_key": dg.AssetKey("raw_tushare_moneyflow_ths"),
            "check_name": MONEYFLOW_THS_RAW_CHECK,
            **changes,
        }
    )


def source_pages(root, run, count=4):
    directory = moneyflow_candidate_directory(
        root, run.run_id, DAY, dataset="moneyflow_ths"
    )
    pages = []
    for i in range(count):
        scope = directory / f"round-{i % 2 + 1}" / "scope-1"
        scope.mkdir(parents=True, exist_ok=True)
        page = scope / f"page-{(i // 2) * 2000}.json"
        # Bytes are intentionally not JSON: cleanup must never parse the data.
        page.write_bytes(b"downloaded page")
        pages.append(page)
    return directory, pages


def test_success_removes_only_its_pages_and_is_idempotent(tmp_path):
    run = raw_run()
    directory, pages = source_pages(tmp_path, run)
    kept = [
        directory / name
        for name in (
            "receipt.json",
            "promotion-raw.json",
            "raw.parquet",
            "verification.parquet",
            "round-1/scope-1/other.json",
            "round-1/scope-1/page-not-offset.json",
        )
    ]
    other_run = raw_run()
    _, other_pages = source_pages(tmp_path, other_run)
    other_dataset = tmp_path / "moneyflow" / run.run_id / "moneyflow_dc" / DAY
    other_dataset.mkdir(parents=True)
    kept.append(other_dataset / "page-0.json")
    formal = tmp_path / "formal" / "raw.parquet"
    formal.parent.mkdir()
    kept.append(formal)
    for path in kept:
        path.write_bytes(b"keep exactly")

    assert cleanup_moneyflow_ths_pages(
        staging_root=tmp_path, run=run, raw_check=raw_check()
    ) == (4, 60)
    assert all(not p.exists() for p in pages)
    assert all(p.read_bytes() == b"keep exactly" for p in kept)
    assert all(p.exists() for p in other_pages)
    assert cleanup_moneyflow_ths_pages(
        staging_root=tmp_path, run=run, raw_check=raw_check()
    ) == (0, 0)


@pytest.mark.parametrize(
    "changes,check",
    [
        ({"status": dg.DagsterRunStatus.FAILURE}, raw_check()),
        ({"status": dg.DagsterRunStatus.CANCELED}, raw_check()),
        ({"status": dg.DagsterRunStatus.STARTED}, raw_check()),
        ({"job_name": "silver_moneyflow_ths_update_job"}, raw_check()),
        ({"job_name": "raw_tushare_moneyflow_dc_update_job"}, raw_check()),
        ({"tags": {}}, raw_check()),
        ({}, None),
        ({}, raw_check(passed=False)),
        ({}, raw_check(asset_key=dg.AssetKey("raw_tushare_moneyflow_dc"))),
        ({}, raw_check(check_name="unrelated_check")),
    ],
)
def test_unsuccessful_or_unrelated_run_keeps_pages(tmp_path, changes, check):
    run = raw_run(**changes)
    _, pages = source_pages(tmp_path, run)
    assert cleanup_moneyflow_ths_pages(
        staging_root=tmp_path, run=run, raw_check=check
    ) == (0, 0)
    assert all(p.exists() for p in pages)


@pytest.mark.parametrize("count", [64, 65])
def test_existing_request_limit_applies_before_deleting(tmp_path, count):
    run = raw_run()
    _, pages = source_pages(tmp_path, run, count)
    if count == 64:
        assert cleanup_moneyflow_ths_pages(
            staging_root=tmp_path, run=run, raw_check=raw_check()
        ) == (64, 960)
    else:
        with pytest.raises(MoneyflowContractError, match="source_page_count"):
            cleanup_moneyflow_ths_pages(
                staging_root=tmp_path, run=run, raw_check=raw_check()
            )
        assert all(p.exists() for p in pages)


def test_symlink_refuses_whole_cleanup_before_deletion(tmp_path):
    run = raw_run()
    directory, pages = source_pages(tmp_path, run)
    outside = tmp_path / "keep.json"
    outside.write_text("keep")
    (directory / "round-2/scope-1/page-4000.json").symlink_to(outside)
    with pytest.raises(MoneyflowContractError, match="update_path"):
        cleanup_moneyflow_ths_pages(
            staging_root=tmp_path, run=run, raw_check=raw_check()
        )
    assert all(p.exists() for p in pages)
    assert outside.read_text() == "keep"


def test_interrupted_cleanup_continues_only_remaining_files(tmp_path, monkeypatch):
    run = raw_run()
    _, pages = source_pages(tmp_path, run)
    unlink = Path.unlink
    calls = []

    def interrupted(path, *args, **kwargs):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("interrupted deletion")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", interrupted)
    with pytest.raises(OSError, match="interrupted deletion"):
        cleanup_moneyflow_ths_pages(
            staging_root=tmp_path, run=run, raw_check=raw_check()
        )
    assert sum(p.exists() for p in pages) == 3
    monkeypatch.setattr(Path, "unlink", unlink)
    assert cleanup_moneyflow_ths_pages(
        staging_root=tmp_path, run=run, raw_check=raw_check()
    ) == (3, 45)


@pytest.mark.parametrize("passed", [True, False])
def test_real_job_terminal_state_controls_cleanup(tmp_path, monkeypatch, passed):
    # Independent fixture for the real job's one-date Raw + blocking-check shape.
    partitions = dg.StaticPartitionsDefinition([DAY])

    @dg.asset(name="raw_tushare_moneyflow_ths", partitions_def=partitions)
    def raw():
        return None

    @dg.asset_check(asset=raw, name=MONEYFLOW_THS_RAW_CHECK, blocking=True)
    def file_check():
        return dg.AssetCheckResult(passed=passed)

    job = dg.define_asset_job(
        name=STOCK_THS_MONEYFLOW_AUTOMATION.raw_job,
        selection=dg.AssetSelection.assets(raw) | dg.AssetSelection.checks_for_assets(raw),
    )
    definitions = dg.Definitions(
        assets=[raw],
        asset_checks=[file_check],
        jobs=[job],
        sensors=[sensors.raw_tushare_moneyflow_ths_page_cleanup_sensor],
    )
    with dg.DagsterInstance.ephemeral() as instance:
        result = definitions.resolve_job_def(job.name).execute_in_process(
            instance=instance, partition_key=DAY, raise_on_error=False
        )
        assert result.success is passed
        run = instance.get_run_by_id(result.run_id)
        _, pages = source_pages(tmp_path, run)
        evaluations = [
            e.asset_check_evaluation_data
            for e in result.all_events
            if e.event_type == dg.DagsterEventType.ASSET_CHECK_EVALUATION
        ]
        if not passed:
            assert cleanup_moneyflow_ths_pages(
                staging_root=tmp_path, run=run, raw_check=evaluations[0]
            ) == (0, 0)
            assert all(p.exists() for p in pages)
            return
        monkeypatch.setattr(sensors, "DEFAULT_LAKE_STAGING_ROOT", str(tmp_path))
        context = dg.build_run_status_sensor_context(
            sensor_name=sensors.raw_tushare_moneyflow_ths_page_cleanup_sensor.name,
            dagster_instance=instance,
            dagster_run=run,
            dagster_event=result.get_run_success_event(),
        )
        queries = []
        get_records = instance.event_log_storage.get_records_for_run

        def records(*args, **kwargs):
            queries.append((args, kwargs))
            return get_records(*args, **kwargs)

        monkeypatch.setattr(instance.event_log_storage, "get_records_for_run", records)
        sensors.raw_tushare_moneyflow_ths_page_cleanup_sensor(context)
        assert all(not p.exists() for p in pages)
        assert len(queries) == 1
        assert queries[0][0] == (run.run_id,)
        assert queries[0][1]["limit"] == 1
        assert sensors.raw_tushare_moneyflow_ths_page_cleanup_sensor.default_status == dg.DefaultSensorStatus.STOPPED
