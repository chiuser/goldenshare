from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")

from lake_console.backend.app.services.duckdb_compute_audit_service import DuckDbComputeAuditService
from lake_console.backend.app.services.duckdb_compute_executor_service import DuckDbComputeExecutorService
from lake_console.backend.app.services.duckdb_compute_plan_service import DuckDbComputePlanService
from lake_console.backend.app.services.duckdb_compute_prewrite_backup_service import DuckDbComputePrewriteBackupService
from lake_console.backend.app.services.kopia_prewrite_backup_service import KopiaPrewriteBackupError
from lake_console.backend.app.services.lake_job_state import LakeJobLockService, LakeJobStateStore
from lake_console.backend.app.settings import LakeConsoleSettings


def test_backup_stk_mins_qfq_prewrite_records_backup_without_formal_writes(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    run_id = _prepare_compute_and_audit(settings)
    captured: list[list[str]] = []

    def fake_runner(argv: list[str]):
        captured.append(argv)
        return [{"rootEntry": {"obj": f"snapshot-{len(captured):03d}"}}]

    summary = DuckDbComputePrewriteBackupService(settings=settings, kopia_runner=fake_runner).backup_stk_mins_qfq_prewrite(
        run_id=run_id
    )

    assert summary["status"] == "prewrite_backup_completed"
    assert summary["formal_paths_touched"] == []
    assert len(captured) == 2
    assert sorted(Path(argv[3]).relative_to(tmp_path).as_posix() for argv in captured) == [
        "manifest",
        "research/stk_mins_by_date_clean_next",
    ]
    manifest_root = tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id
    backup_record = json.loads((manifest_root / "prewrite_backup.json").read_text(encoding="utf-8"))
    assert backup_record["status"] == "success"
    assert backup_record["snapshot_ids"] == ["snapshot-001", "snapshot-002"]
    assert backup_record["snapshot_paths"] == ["manifest", "research/stk_mins_by_date_clean_next"]
    assert "manifest/duckdb_compute/runs/" + run_id in backup_record["backup_paths"]
    run_payload = json.loads((manifest_root / "run.json").read_text(encoding="utf-8"))
    assert run_payload["status"] == "prewrite_backup"
    assert run_payload["m3b_prewrite_backup"]["status"] == "success"
    assert not (tmp_path / "manifest" / "stk_mins_quality" / "clean_next_partition_gate.parquet").exists()
    assert not (tmp_path / "manifest" / "indicator_recalc_queue" / "stk_mins_macd.parquet").exists()
    assert (tmp_path / "manifest" / "lake_jobs" / "backups" / f"{run_id}-kopia.json").exists()
    assert LakeJobLockService(LakeJobStateStore(tmp_path)).get_lock()["status"] == "idle"

    second = DuckDbComputePrewriteBackupService(settings=settings, kopia_runner=lambda _: pytest.fail("unexpected kopia call")).backup_stk_mins_qfq_prewrite(
        run_id=run_id
    )
    assert second["message"].startswith("M3-B Kopia 写前备份已存在")


def test_backup_stk_mins_qfq_prewrite_requires_audit_passed(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    prepare = DuckDbComputePlanService(settings=settings).prepare_stk_mins_qfq_run(
        start_date="2026-03-02",
        end_date="2026-03-02",
        freqs=[30],
    )
    run_id = prepare["run"]["run_id"]

    with pytest.raises(RuntimeError, match="不能进入 M3-B"):
        DuckDbComputePrewriteBackupService(settings=settings, kopia_runner=lambda _: {}).backup_stk_mins_qfq_prewrite(
            run_id=run_id
        )

    assert not (tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id / "prewrite_backup.json").exists()
    assert LakeJobLockService(LakeJobStateStore(tmp_path)).get_lock()["status"] == "idle"


def test_backup_stk_mins_qfq_prewrite_blocks_on_kopia_failure(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    run_id = _prepare_compute_and_audit(settings)

    def failing_runner(argv: list[str]):
        raise KopiaPrewriteBackupError("kopia repository is not connected")

    with pytest.raises(KopiaPrewriteBackupError, match="repository"):
        DuckDbComputePrewriteBackupService(settings=settings, kopia_runner=failing_runner).backup_stk_mins_qfq_prewrite(
            run_id=run_id
        )

    manifest_root = tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id
    run_payload = json.loads((manifest_root / "run.json").read_text(encoding="utf-8"))
    assert run_payload["status"] == "blocked"
    assert run_payload["error"]["stage"] == "prewrite_backup"
    assert not (manifest_root / "prewrite_backup.json").exists()
    assert not (tmp_path / "manifest" / "lake_jobs" / "backups" / f"{run_id}-kopia.json").exists()
    assert LakeJobLockService(LakeJobStateStore(tmp_path)).get_lock()["status"] == "idle"


def _prepare_compute_and_audit(settings: LakeConsoleSettings) -> str:
    prepare = DuckDbComputePlanService(settings=settings).prepare_stk_mins_qfq_run(
        start_date="2026-03-02",
        end_date="2026-03-02",
        freqs=[30],
    )
    run_id = prepare["run"]["run_id"]
    DuckDbComputeExecutorService(settings=settings).compute_stk_mins_qfq_candidates(run_id=run_id)
    DuckDbComputeAuditService(settings=settings).audit_stk_mins_qfq_candidates(run_id=run_id)
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
