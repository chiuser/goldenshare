from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("pyarrow")

from lake_console.backend.app.services.duckdb_compute_plan_service import _write_parquet_manifest
from lake_console.backend.app.services.duckdb_compute_run_lifecycle_service import DuckDbComputeRunLifecycleService
from lake_console.backend.app.services.stk_mins_clean_next_gate import CleanNextGateStatus, CleanNextPartitionGateService
from lake_console.backend.app.settings import LakeConsoleSettings


def test_abandon_stk_mins_qfq_run_marks_prewrite_backup_run_without_formal_writes(tmp_path: Path) -> None:
    run_id = "test-run"
    manifest_root = _write_run_manifest(tmp_path, run_id=run_id, status="prewrite_backup", publish_status="audit_passed")
    settings = LakeConsoleSettings(lake_root=tmp_path, tushare_token=None)

    summary = DuckDbComputeRunLifecycleService(settings=settings).abandon_stk_mins_qfq_run(
        run_id=run_id,
        reason="历史小样本停在 prewrite_backup，未进入正式发布",
    )

    assert summary["status"] == "abandoned"
    assert summary["formal_paths_touched"] == []
    run_payload = json.loads((manifest_root / "run.json").read_text(encoding="utf-8"))
    assert run_payload["status"] == "abandoned"
    assert run_payload["abandon_reason"] == "历史小样本停在 prewrite_backup，未进入正式发布"
    assert not (tmp_path / "manifest" / "stk_mins_quality" / "clean_next_partition_gate.parquet").exists()
    events = (manifest_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(events[-1])["event_type"] == "run_abandoned"


def test_abandon_stk_mins_qfq_run_blocks_after_publish_started(tmp_path: Path) -> None:
    run_id = "test-run"
    _write_run_manifest(tmp_path, run_id=run_id, status="publishing", publish_status="published")
    settings = LakeConsoleSettings(lake_root=tmp_path, tushare_token=None)

    summary = DuckDbComputeRunLifecycleService(settings=settings).abandon_stk_mins_qfq_run(
        run_id=run_id,
        reason="should block",
    )

    assert summary["status"] == "blocked"
    codes = {item["code"] for item in summary["blockers"]}
    assert "run_already_entered_publish_stage" in codes
    assert "publish_partitions_already_started" in codes


def test_abandon_stk_mins_qfq_run_blocks_when_formal_gate_references_run(tmp_path: Path) -> None:
    run_id = "test-run"
    _write_run_manifest(tmp_path, run_id=run_id, status="prewrite_backup", publish_status="audit_passed")
    CleanNextPartitionGateService(lake_root=tmp_path).write_statuses(
        [
            CleanNextGateStatus(
                freq=30,
                trade_date=pd.Timestamp("2026-03-02").date(),
                clean_partition_path="research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-02",
                source_run_id=run_id,
                clean_run_id=run_id,
                write_revision=f"qfq:{run_id}:freq=30/trade_date=2026-03-02",
                status="publishing",
                issue_count=0,
                raw_rows=1,
                clean_rows=1,
                ledger_path="manifest/stk_mins_quality/ledger.parquet",
                message="publishing",
            )
        ],
        run_id=run_id,
    )
    settings = LakeConsoleSettings(lake_root=tmp_path, tushare_token=None)

    summary = DuckDbComputeRunLifecycleService(settings=settings).abandon_stk_mins_qfq_run(
        run_id=run_id,
        reason="should block",
    )

    assert summary["status"] == "blocked"
    assert "formal_gate_references_run" in {item["code"] for item in summary["blockers"]}


def _write_run_manifest(tmp_path: Path, *, run_id: str, status: str, publish_status: str) -> Path:
    manifest_root = tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id
    manifest_root.mkdir(parents=True, exist_ok=True)
    (manifest_root / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "job_type": "stk_mins_qfq_clean_next",
                "status": status,
                "created_at": "2026-05-16T00:00:00+00:00",
                "finished_at": None,
                "input_range": {"start_date": "2026-03-02", "end_date": "2026-03-02", "freqs": [30]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_parquet_manifest(
        manifest_root / "publish_partitions.parquet",
        [
            {
                "run_id": run_id,
                "partition_key": "freq=30/trade_date=2026-03-02",
                "source_candidate_parts_json": "[]",
                "expected_candidate_part_paths_json": "[]",
                "expected_candidate_part_count": 0,
                "target_path": "research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-02",
                "audit_status": "passed",
                "publish_status": publish_status,
            }
        ],
        columns=[
            "run_id",
            "partition_key",
            "source_candidate_parts_json",
            "expected_candidate_part_paths_json",
            "expected_candidate_part_count",
            "target_path",
            "audit_status",
            "publish_status",
        ],
    )
    (manifest_root / "events.jsonl").write_text("", encoding="utf-8")
    return manifest_root
