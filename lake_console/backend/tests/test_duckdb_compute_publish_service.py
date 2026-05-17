from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")

from lake_console.backend.app.services.duckdb_compute_audit_service import DuckDbComputeAuditService
from lake_console.backend.app.services.duckdb_compute_executor_service import DuckDbComputeExecutorService
from lake_console.backend.app.services.duckdb_compute_plan_service import DuckDbComputePlanService
from lake_console.backend.app.services.duckdb_compute_prewrite_backup_service import DuckDbComputePrewriteBackupService
from lake_console.backend.app.services.duckdb_compute_publish_service import DuckDbComputePublishService
from lake_console.backend.app.services.indicators import IndicatorRecalcQueueService
from lake_console.backend.app.services.lake_job_state import LakeJobLockService, LakeJobStateStore
from lake_console.backend.app.services.stk_mins_clean_next_gate import CleanNextGateStatus, CleanNextPartitionGateService
from lake_console.backend.app.settings import LakeConsoleSettings


def test_preflight_stk_mins_qfq_publish_is_read_only_and_reports_gate_downstream_plan(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    run_id = _prepare_compute_audit_and_backup(settings)

    summary = DuckDbComputePublishService(settings=settings).preflight_stk_mins_qfq_publish(run_id=run_id)

    assert summary["status"] == "ready"
    assert summary["ready"] is True
    assert summary["write_intent"] is False
    assert summary["formal_paths_touched"] == []
    assert summary["metrics"]["publish_partition_count"] == 1
    assert summary["metrics"]["candidate_part_count"] == 1
    assert summary["target_partitions"][0]["target_path"] == "research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-02"
    assert summary["gate_plan"] == [
        {
            "partition_key": "freq=30/trade_date=2026-03-02",
            "current_status": None,
            "current_write_revision": None,
            "planned_before_replace": "publishing",
            "planned_after_downstream": "passed",
            "write_intent": False,
        }
    ]
    assert [row["target_layer"] for row in summary["downstream_requirements"]] == [
        "derived/stk_mins_by_date",
        "research/stk_mins_by_symbol_month",
        "indicator/*",
    ]
    assert not (tmp_path / "manifest" / "downstream_rebuild_requirements" / "stk_mins.parquet").exists()
    assert not (tmp_path / "manifest" / "stk_mins_quality" / "clean_next_partition_gate.parquet").exists()
    assert not (tmp_path / "manifest" / "indicator_recalc_queue" / "stk_mins_macd.parquet").exists()
    assert LakeJobLockService(LakeJobStateStore(tmp_path)).get_lock()["status"] == "idle"


def test_prepare_stk_mins_qfq_gate_publish_plan_writes_run_manifest_only(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    run_id = _prepare_compute_audit_and_backup(settings)

    summary = DuckDbComputePublishService(settings=settings).prepare_stk_mins_qfq_gate_publish_plan(run_id=run_id)

    assert summary["status"] == "gate_publish_plan_prepared"
    assert summary["ready"] is True
    assert summary["write_intent"] is True
    assert summary["formal_write_intent"] is False
    assert summary["run_manifest_write_intent"] is True
    assert summary["formal_paths_touched"] == []

    plan_path = tmp_path / summary["gate_publish_plan"]
    with plan_path.open("r", encoding="utf-8") as file:
        plan_payload = json.load(file)
    assert plan_payload["stage"] == "m3c_b_gate_publish_plan"
    assert plan_payload["publish_mode"] == "layer_cutover_publish"
    assert plan_payload["formal_write_intent"] is False
    assert plan_payload["metrics"]["planned_gate_row_count"] == 1
    assert plan_payload["gate_rows"] == [
        {
            "gate_schema_version": 1,
            "dataset_key": "stk_mins",
            "source_key": "tushare",
            "freq": 30,
            "trade_date": "2026-03-02",
            "partition_key": "freq=30/trade_date=2026-03-02",
            "clean_partition_path": "research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-02",
            "source_run_id": run_id,
            "clean_run_id": run_id,
            "write_revision": f"{run_id}:qfq:freq=30/trade_date=2026-03-02",
            "status": "publishing",
            "issue_count": 0,
            "raw_rows": 1,
            "clean_rows": 1,
            "checked_at": None,
            "ledger_path": f"manifest/duckdb_compute/runs/{run_id}/formal_audit_ledger.parquet",
            "message": "计划在正式 replace 前写入 publishing，用于阻断下游消费。",
        }
    ]

    with (tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id / "run.json").open("r", encoding="utf-8") as file:
        run_payload = json.load(file)
    assert run_payload["status"] == "prewrite_backup"
    assert run_payload["m3c_b_gate_publish_plan"]["status"] == "success"
    assert run_payload["m3c_b_gate_publish_plan"]["formal_gate_written"] is False

    assert not (tmp_path / "manifest" / "stk_mins_quality" / "clean_next_partition_gate.parquet").exists()
    assert not (tmp_path / "manifest" / "downstream_rebuild_requirements" / "stk_mins.parquet").exists()
    assert not (tmp_path / "manifest" / "indicator_recalc_queue" / "stk_mins_macd.parquet").exists()
    assert LakeJobLockService(LakeJobStateStore(tmp_path)).get_lock()["status"] == "idle"


def test_stage_stk_mins_qfq_gate_publishing_writes_formal_gate_only(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    run_id = _prepare_compute_audit_and_backup(settings)
    DuckDbComputePublishService(settings=settings).prepare_stk_mins_qfq_gate_publish_plan(run_id=run_id)

    summary = DuckDbComputePublishService(settings=settings).stage_stk_mins_qfq_gate_publishing(run_id=run_id)

    assert summary["status"] == "formal_gate_publishing_staged"
    assert summary["ready"] is True
    assert summary["write_intent"] is True
    assert summary["formal_paths_touched"] == ["manifest/stk_mins_quality/clean_next_partition_gate.parquet"]
    assert summary["gate_write"]["updated_partitions"] == 1

    gate_rows = CleanNextPartitionGateService(lake_root=tmp_path).read_statuses()
    assert len(gate_rows) == 1
    assert gate_rows[0]["partition_key"] == "freq=30/trade_date=2026-03-02"
    assert gate_rows[0]["status"] == "publishing"
    assert gate_rows[0]["write_revision"] == f"{run_id}:qfq:freq=30/trade_date=2026-03-02"

    manifest_root = tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id
    publish_rows = pd.read_parquet(manifest_root / "publish_partitions.parquet", engine="pyarrow").to_dict(orient="records")
    assert publish_rows[0]["audit_status"] == "passed"
    assert publish_rows[0]["publish_status"] == "publishing"

    with (manifest_root / "run.json").open("r", encoding="utf-8") as file:
        run_payload = json.load(file)
    assert run_payload["status"] == "publishing"
    assert run_payload["m3c_c_gate_publishing"]["status"] == "success"

    formal_rows = pd.read_parquet(
        tmp_path / "research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-02/part-000.parquet",
        engine="pyarrow",
    ).to_dict(orient="records")
    assert formal_rows[0]["close"] == 10.5
    assert not (tmp_path / "manifest" / "downstream_rebuild_requirements" / "stk_mins.parquet").exists()
    assert not (tmp_path / "manifest" / "indicator_recalc_queue" / "stk_mins_macd.parquet").exists()
    assert LakeJobLockService(LakeJobStateStore(tmp_path)).get_lock()["status"] == "idle"


def test_stage_stk_mins_qfq_formal_replace_and_audit_replaces_partition_but_keeps_gate_publishing(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    run_id = _prepare_compute_audit_and_backup(settings)
    service = DuckDbComputePublishService(settings=settings)
    service.prepare_stk_mins_qfq_gate_publish_plan(run_id=run_id)
    service.stage_stk_mins_qfq_gate_publishing(run_id=run_id)

    summary = service.stage_stk_mins_qfq_formal_replace_and_audit(run_id=run_id)

    assert summary["status"] == "formal_partitions_published"
    assert summary["ready"] is True
    assert summary["formal_paths_touched"] == ["research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-02"]
    assert summary["metrics"]["replaced_partition_count"] == 1
    assert summary["metrics"]["formal_audit_issue_count"] == 0

    formal_rows = pd.read_parquet(
        tmp_path / "research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-02/part-00000.parquet",
        engine="pyarrow",
    ).to_dict(orient="records")
    assert formal_rows[0]["close"] == 5.25
    assert formal_rows[0]["vwap"] == 5.1

    gate_rows = CleanNextPartitionGateService(lake_root=tmp_path).read_statuses()
    assert gate_rows[0]["status"] == "publishing"
    assert gate_rows[0]["write_revision"] == f"{run_id}:qfq:freq=30/trade_date=2026-03-02"

    manifest_root = tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id
    publish_rows = pd.read_parquet(manifest_root / "publish_partitions.parquet", engine="pyarrow").to_dict(orient="records")
    assert publish_rows[0]["publish_status"] == "published"
    audit_rows = pd.read_parquet(manifest_root / "formal_audit_ledger.parquet", engine="pyarrow").to_dict(orient="records")
    assert audit_rows == []
    with (manifest_root / "run.json").open("r", encoding="utf-8") as file:
        run_payload = json.load(file)
    assert run_payload["status"] == "publishing"
    assert run_payload["m3c_d_formal_publish"]["status"] == "success"

    assert not (tmp_path / "manifest" / "downstream_rebuild_requirements" / "stk_mins.parquet").exists()
    assert not (tmp_path / "manifest" / "indicator_recalc_queue" / "stk_mins_macd.parquet").exists()
    assert LakeJobLockService(LakeJobStateStore(tmp_path)).get_lock()["status"] == "idle"


def test_stage_stk_mins_qfq_formal_replace_blocks_before_gate_publishing(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    run_id = _prepare_compute_audit_and_backup(settings)
    service = DuckDbComputePublishService(settings=settings)
    service.prepare_stk_mins_qfq_gate_publish_plan(run_id=run_id)

    summary = service.stage_stk_mins_qfq_formal_replace_and_audit(run_id=run_id)

    assert summary["status"] == "blocked"
    assert {item["code"] for item in summary["blockers"]} == {
        "run_not_formal_gate_publishing",
        "m3c_c_gate_publishing_missing",
    }
    formal_rows = pd.read_parquet(
        tmp_path / "research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-02/part-000.parquet",
        engine="pyarrow",
    ).to_dict(orient="records")
    assert formal_rows[0]["close"] == 10.5


def test_stage_stk_mins_qfq_formal_replace_keeps_gate_publishing_when_formal_audit_fails(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    run_id = _prepare_compute_audit_and_backup(settings)
    service = DuckDbComputePublishService(settings=settings)
    service.prepare_stk_mins_qfq_gate_publish_plan(run_id=run_id)
    service.stage_stk_mins_qfq_gate_publishing(run_id=run_id)

    manifest_root = tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id
    publish_row = pd.read_parquet(manifest_root / "publish_partitions.parquet", engine="pyarrow").iloc[0].to_dict()
    candidate_path = tmp_path / json.loads(publish_row["source_candidate_parts_json"])[0]
    _write_parquet(
        candidate_path,
        [
            {
                "ts_code": "600000.SH",
                "freq": 30,
                "trade_time": "2026-03-02 10:00:00",
                "open": 5.0,
                "high": 5.5,
                "low": 4.5,
                "close": 5.25,
                "vol": 100,
                "amount": 1020.0,
            }
        ],
    )

    summary = service.stage_stk_mins_qfq_formal_replace_and_audit(run_id=run_id)

    assert summary["status"] == "blocked"
    assert summary["issue_count"] == 1
    gate_rows = CleanNextPartitionGateService(lake_root=tmp_path).read_statuses()
    assert gate_rows[0]["status"] == "publishing"
    publish_rows = pd.read_parquet(manifest_root / "publish_partitions.parquet", engine="pyarrow").to_dict(orient="records")
    assert publish_rows[0]["publish_status"] == "formal_audit_failed"
    audit_rows = pd.read_parquet(manifest_root / "formal_audit_ledger.parquet", engine="pyarrow").to_dict(orient="records")
    assert audit_rows[0]["issue_code"] == "formal_partition_schema_mismatch"
    assert not (tmp_path / "manifest" / "downstream_rebuild_requirements" / "stk_mins.parquet").exists()
    assert not (tmp_path / "manifest" / "indicator_recalc_queue" / "stk_mins_macd.parquet").exists()


def test_stage_stk_mins_qfq_downstream_and_gate_passed_writes_notifications_before_final_gate(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    run_id = _prepare_compute_audit_and_backup(settings)
    service = DuckDbComputePublishService(settings=settings)
    service.prepare_stk_mins_qfq_gate_publish_plan(run_id=run_id)
    service.stage_stk_mins_qfq_gate_publishing(run_id=run_id)
    service.stage_stk_mins_qfq_formal_replace_and_audit(run_id=run_id)

    summary = service.stage_stk_mins_qfq_downstream_and_gate_passed(run_id=run_id)
    repeat_summary = service.stage_stk_mins_qfq_downstream_and_gate_passed(run_id=run_id)

    assert summary["status"] == "published"
    assert summary["ready"] is True
    assert summary["gate_write"]["updated_partitions"] == 1
    assert repeat_summary["idempotent"] is True
    gate_rows = CleanNextPartitionGateService(lake_root=tmp_path).read_statuses()
    assert gate_rows[0]["status"] == "passed"
    assert gate_rows[0]["write_revision"] == f"{run_id}:qfq:freq=30/trade_date=2026-03-02"

    downstream_rows = pd.read_parquet(tmp_path / "manifest/downstream_rebuild_requirements/stk_mins.parquet", engine="pyarrow").to_dict(orient="records")
    assert sorted(row["target_layer"] for row in downstream_rows) == [
        "derived/stk_mins_by_date",
        "indicator/*",
        "research/stk_mins_by_symbol_month",
    ]
    queue_rows = IndicatorRecalcQueueService(lake_root=tmp_path).list_items(include_done=True)
    assert len(queue_rows) == 1
    assert queue_rows[0]["freq_value"] == 30
    assert queue_rows[0]["status"] == "pending"
    event_lines = (tmp_path / "manifest/source_partition_events/stk_mins.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1

    with (tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id / "run.json").open("r", encoding="utf-8") as file:
        run_payload = json.load(file)
    assert run_payload["status"] == "published"
    assert run_payload["m3c_e_downstream_and_gate_passed"]["status"] == "success"


def test_stage_stk_mins_qfq_downstream_failure_keeps_gate_publishing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    run_id = _prepare_compute_audit_and_backup(settings)
    service = DuckDbComputePublishService(settings=settings)
    service.prepare_stk_mins_qfq_gate_publish_plan(run_id=run_id)
    service.stage_stk_mins_qfq_gate_publishing(run_id=run_id)
    service.stage_stk_mins_qfq_formal_replace_and_audit(run_id=run_id)

    def fail_record(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("queue write failed")

    monkeypatch.setattr(IndicatorRecalcQueueService, "record_source_partitions_replaced", fail_record)

    with pytest.raises(RuntimeError, match="queue write failed"):
        service.stage_stk_mins_qfq_downstream_and_gate_passed(run_id=run_id)

    gate_rows = CleanNextPartitionGateService(lake_root=tmp_path).read_statuses()
    assert gate_rows[0]["status"] == "publishing"
    assert not (tmp_path / "manifest/indicator_recalc_queue/stk_mins_macd.parquet").exists()
    with (tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id / "run.json").open("r", encoding="utf-8") as file:
        run_payload = json.load(file)
    assert run_payload["status"] == "publishing"
    assert run_payload["m3c_e_downstream_and_gate_passed"]["status"] == "failed"


def test_stage_stk_mins_qfq_final_gate_failure_keeps_gate_publishing_after_notifications(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    run_id = _prepare_compute_audit_and_backup(settings)
    service = DuckDbComputePublishService(settings=settings)
    service.prepare_stk_mins_qfq_gate_publish_plan(run_id=run_id)
    service.stage_stk_mins_qfq_gate_publishing(run_id=run_id)
    service.stage_stk_mins_qfq_formal_replace_and_audit(run_id=run_id)

    def fail_gate_write(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("final gate write failed")

    monkeypatch.setattr(CleanNextPartitionGateService, "write_statuses", fail_gate_write)

    with pytest.raises(RuntimeError, match="final gate write failed"):
        service.stage_stk_mins_qfq_downstream_and_gate_passed(run_id=run_id)

    gate_rows = CleanNextPartitionGateService(lake_root=tmp_path).read_statuses()
    assert gate_rows[0]["status"] == "publishing"
    assert gate_rows[0]["write_revision"] == f"{run_id}:qfq:freq=30/trade_date=2026-03-02"

    downstream_rows = pd.read_parquet(tmp_path / "manifest/downstream_rebuild_requirements/stk_mins.parquet", engine="pyarrow").to_dict(orient="records")
    assert sorted(row["target_layer"] for row in downstream_rows) == [
        "derived/stk_mins_by_date",
        "indicator/*",
        "research/stk_mins_by_symbol_month",
    ]
    queue_rows = IndicatorRecalcQueueService(lake_root=tmp_path).list_items(include_done=True)
    assert len(queue_rows) == 1
    event_lines = (tmp_path / "manifest/source_partition_events/stk_mins.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1

    with (tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id / "run.json").open("r", encoding="utf-8") as file:
        run_payload = json.load(file)
    assert run_payload["status"] == "publishing"
    assert run_payload["m3c_e_downstream_and_gate_passed"]["status"] == "failed"
    assert run_payload["m3c_e_downstream_and_gate_passed"]["gate_passed"] is False
    assert run_payload["error"]["error_code"] == "LC_COMPUTE_FINAL_GATE_FAILED"

    event_payloads = [
        json.loads(line)
        for line in (tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert event_payloads[-1]["event_type"] == "final_gate_passed_failed"


def test_stage_stk_mins_qfq_gate_publishing_blocks_other_publishing_revision(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    run_id = _prepare_compute_audit_and_backup(settings)
    DuckDbComputePublishService(settings=settings).prepare_stk_mins_qfq_gate_publish_plan(run_id=run_id)
    CleanNextPartitionGateService(lake_root=tmp_path).write_statuses(
        [
            CleanNextGateStatus(
                freq=30,
                trade_date=date.fromisoformat("2026-03-02"),
                clean_partition_path="research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-02",
                source_run_id="other-run",
                clean_run_id="other-run",
                write_revision="other-run:qfq:freq=30/trade_date=2026-03-02",
                status="publishing",
                issue_count=0,
                raw_rows=1,
                clean_rows=1,
                ledger_path="other",
                message="other publishing gate",
            )
        ],
        run_id="seed-other-publishing-gate",
    )

    summary = DuckDbComputePublishService(settings=settings).stage_stk_mins_qfq_gate_publishing(run_id=run_id)

    assert summary["status"] == "blocked"
    assert {item["code"] for item in summary["blockers"]} == {"formal_gate_already_publishing_by_other_revision"}
    gate_rows = CleanNextPartitionGateService(lake_root=tmp_path).read_statuses()
    assert gate_rows[0]["write_revision"] == "other-run:qfq:freq=30/trade_date=2026-03-02"


def test_preflight_stk_mins_qfq_publish_blocks_before_prewrite_backup(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    prepare = DuckDbComputePlanService(settings=settings).prepare_stk_mins_qfq_run(
        start_date="2026-03-02",
        end_date="2026-03-02",
        freqs=[30],
    )
    run_id = prepare["run"]["run_id"]
    DuckDbComputeExecutorService(settings=settings).compute_stk_mins_qfq_candidates(run_id=run_id)
    DuckDbComputeAuditService(settings=settings).audit_stk_mins_qfq_candidates(run_id=run_id)

    summary = DuckDbComputePublishService(settings=settings).preflight_stk_mins_qfq_publish(run_id=run_id)

    assert summary["status"] == "blocked"
    assert {item["code"] for item in summary["blockers"]} >= {
        "m3b_prewrite_backup_missing",
        "prewrite_backup_file_missing",
    }
    assert summary["formal_paths_touched"] == []


def test_preflight_stk_mins_qfq_publish_blocks_when_candidate_part_missing(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    run_id = _prepare_compute_audit_and_backup(settings)
    manifest_root = tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id
    publish_row = pd.read_parquet(manifest_root / "publish_partitions.parquet", engine="pyarrow").iloc[0].to_dict()
    candidate_path = tmp_path / json.loads(publish_row["source_candidate_parts_json"])[0]
    candidate_path.unlink()

    summary = DuckDbComputePublishService(settings=settings).preflight_stk_mins_qfq_publish(run_id=run_id)

    assert summary["status"] == "blocked"
    assert {item["code"] for item in summary["blockers"]} >= {"candidate_part_file_missing"}
    assert summary["formal_paths_touched"] == []


def _prepare_compute_audit_and_backup(settings: LakeConsoleSettings) -> str:
    prepare = DuckDbComputePlanService(settings=settings).prepare_stk_mins_qfq_run(
        start_date="2026-03-02",
        end_date="2026-03-02",
        freqs=[30],
    )
    run_id = prepare["run"]["run_id"]
    DuckDbComputeExecutorService(settings=settings).compute_stk_mins_qfq_candidates(run_id=run_id)
    DuckDbComputeAuditService(settings=settings).audit_stk_mins_qfq_candidates(run_id=run_id)

    def fake_runner(argv: list[str]):
        root = Path(argv[3])
        return [{"rootEntry": {"obj": f"snapshot-{root.name}"}}]

    DuckDbComputePrewriteBackupService(settings=settings, kopia_runner=fake_runner).backup_stk_mins_qfq_prewrite(
        run_id=run_id
    )
    return run_id


def _settings(lake_root: Path) -> LakeConsoleSettings:
    return LakeConsoleSettings(
        lake_root=lake_root,
        tushare_token=None,
        compute_bucket_count=1,
        duckdb_threads=1,
        duckdb_memory_limit="1GB",
        duckdb_temp_directory="_tmp/duckdb-test",
    )


def _write_minimal_inputs(lake_root: Path) -> None:
    _write_parquet(
        lake_root / "research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-02/part-000.parquet",
        [
            {
                "ts_code": "600000.SH",
                "freq": 30,
                "trade_time": "2026-03-02 10:00:00",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "vol": 100,
                "amount": 1020.0,
                "exchange": "SSE",
                "vwap": 10.2,
            }
        ],
    )
    _write_parquet(
        lake_root / "raw_tushare/adj_factor/trade_date=2026-03-02/part-000.parquet",
        [{"ts_code": "600000.SH", "trade_date": "2026-03-02", "adj_factor": 2.0}],
    )
    _write_parquet(
        lake_root / "raw_tushare/adj_factor/trade_date=2026-05-14/part-000.parquet",
        [{"ts_code": "600000.SH", "trade_date": "2026-05-14", "adj_factor": 4.0}],
    )
    _write_parquet(
        lake_root / "manifest/security_identity/security_identity_map.parquet",
        [{"latest_ts_code": "600000.SH", "source_ts_code": "600000.SH"}],
    )


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False, engine="pyarrow", compression="zstd")
