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
from lake_console.backend.app.services.lake_job_state import LakeJobLockService, LakeJobStateStore
from lake_console.backend.app.services.parquet_writer import read_parquet_rows
from lake_console.backend.app.settings import LakeConsoleSettings


def test_audit_stk_mins_qfq_candidates_updates_manifests_without_formal_writes(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    prepare = DuckDbComputePlanService(settings=settings).prepare_stk_mins_qfq_run(
        start_date="2026-03-02",
        end_date="2026-03-02",
        freqs=[30],
    )
    run_id = prepare["run"]["run_id"]
    DuckDbComputeExecutorService(settings=settings).compute_stk_mins_qfq_candidates(run_id=run_id)

    summary = DuckDbComputeAuditService(settings=settings).audit_stk_mins_qfq_candidates(run_id=run_id)

    assert summary["status"] == "prewrite_backup"
    assert summary["formal_paths_touched"] == []
    assert summary["metrics"]["issue_count"] == 0
    manifest_root = tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id
    run_payload = json.loads((manifest_root / "run.json").read_text(encoding="utf-8"))
    assert run_payload["status"] == "prewrite_backup"
    audit_rows = read_parquet_rows(manifest_root / "audit_ledger.parquet")
    assert audit_rows == []
    publish_rows = read_parquet_rows(manifest_root / "publish_partitions.parquet")
    assert publish_rows[0]["audit_status"] == "passed"
    assert publish_rows[0]["publish_status"] == "audit_passed"
    assert len(json.loads(publish_rows[0]["source_candidate_parts_json"])) == 1
    source_rows = read_parquet_rows(
        tmp_path / "research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-02/part-000.parquet"
    )
    assert source_rows[0]["close"] == 10.5
    assert not (tmp_path / "manifest" / "stk_mins_quality" / "clean_next_partition_gate.parquet").exists()
    assert LakeJobLockService(LakeJobStateStore(tmp_path)).get_lock()["status"] == "idle"


def test_audit_stk_mins_qfq_candidates_blocks_when_input_snapshot_changed(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = _settings(tmp_path)
    prepare = DuckDbComputePlanService(settings=settings).prepare_stk_mins_qfq_run(
        start_date="2026-03-02",
        end_date="2026-03-02",
        freqs=[30],
    )
    run_id = prepare["run"]["run_id"]
    DuckDbComputeExecutorService(settings=settings).compute_stk_mins_qfq_candidates(run_id=run_id)
    _write_parquet(
        tmp_path / "research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-02/part-000.parquet",
        [
            {
                "ts_code": "600000.SH",
                "freq": 30,
                "trade_time": "2026-03-02 10:00:00",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 99.9,
                "vol": 100,
                "amount": 1020.0,
                "exchange": "SSE",
                "vwap": 10.2,
            }
        ],
    )

    summary = DuckDbComputeAuditService(settings=settings).audit_stk_mins_qfq_candidates(run_id=run_id)

    assert summary["status"] == "blocked"
    assert summary["formal_paths_touched"] == []
    manifest_root = tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id
    issue_rows = read_parquet_rows(manifest_root / "audit_ledger.parquet")
    assert {row["issue_code"] for row in issue_rows} == {"input_snapshot_changed"}
    publish_rows = read_parquet_rows(manifest_root / "publish_partitions.parquet")
    assert publish_rows[0]["audit_status"] == "failed"
    assert publish_rows[0]["publish_status"] == "blocked"
    assert json.loads(publish_rows[0]["source_candidate_parts_json"]) == []
    assert not (tmp_path / "manifest" / "stk_mins_quality" / "clean_next_partition_gate.parquet").exists()


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
