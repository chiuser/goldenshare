from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")

from lake_console.backend.app.services.duckdb_compute_executor_service import DuckDbComputeExecutorService
import lake_console.backend.app.services.duckdb_compute_executor_service as executor_module
from lake_console.backend.app.services.duckdb_compute_plan_service import DuckDbComputePlanService
from lake_console.backend.app.services.lake_job_state import LakeJobLockService, LakeJobStateStore
from lake_console.backend.app.services.parquet_writer import read_parquet_rows
from lake_console.backend.app.settings import LakeConsoleSettings


def test_compute_stk_mins_qfq_candidates_writes_tmp_candidate_only(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = LakeConsoleSettings(
        lake_root=tmp_path,
        tushare_token=None,
        compute_bucket_count=3,
        duckdb_threads=1,
        duckdb_memory_limit="1GB",
        duckdb_temp_directory="_tmp/duckdb-test",
    )
    prepare = DuckDbComputePlanService(settings=settings).prepare_stk_mins_qfq_run(
        start_date="2026-03-02",
        end_date="2026-03-02",
        freqs=[30],
    )
    run_id = prepare["run"]["run_id"]

    summary = DuckDbComputeExecutorService(settings=settings).compute_stk_mins_qfq_candidates(run_id=run_id)

    assert summary["status"] == "compute_completed"
    assert summary["metrics"]["executed_unit_count"] == 1
    assert summary["metrics"]["candidate_part_count"] == 1
    assert summary["formal_paths_touched"] == []
    manifest_root = tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id
    run_payload = json.loads((manifest_root / "run.json").read_text(encoding="utf-8"))
    assert run_payload["status"] == "compute_completed"
    unit_rows = read_parquet_rows(manifest_root / "units.parquet")
    assert [row["status"] for row in unit_rows] == ["succeeded"]
    candidate_rows = read_parquet_rows(manifest_root / "candidate_parts.parquet")
    assert len(candidate_rows) == 1
    candidate = candidate_rows[0]
    assert candidate["status"] == "staged"
    candidate_path = tmp_path / candidate["candidate_part_path"]
    assert "_tmp/duckdb_compute" in str(candidate_path)
    assert "bucket=" not in candidate["candidate_part_path"]
    assert candidate_path.exists()
    assert candidate["row_count"] == 1
    assert candidate["byte_count"] > 0
    assert candidate["checksum"]
    candidate_data = read_parquet_rows(candidate_path)
    assert len(candidate_data) == 1
    assert candidate_data[0]["ts_code"] == "600000.SH"
    assert candidate_data[0]["freq"] == 30
    assert candidate_data[0]["exchange"] == "SSE"
    assert candidate_data[0]["vol"] == 100
    assert candidate_data[0]["amount"] == 1020.0
    assert candidate_data[0]["open"] == 5.0
    assert candidate_data[0]["high"] == 5.5
    assert candidate_data[0]["low"] == 4.5
    assert candidate_data[0]["close"] == 5.25
    assert candidate_data[0]["vwap"] == 5.1
    source_rows = read_parquet_rows(
        tmp_path / "research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-02/part-000.parquet"
    )
    assert source_rows[0]["close"] == 10.5
    assert not (tmp_path / "manifest" / "stk_mins_quality" / "clean_next_partition_gate.parquet").exists()
    assert LakeJobLockService(LakeJobStateStore(tmp_path)).get_lock()["status"] == "idle"


def test_compute_stk_mins_qfq_candidates_blocks_factor_holes_without_candidate(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path, include_day_factor=False)
    _write_parquet(
        tmp_path / "raw_tushare/adj_factor/trade_date=2026-03-02/part-000.parquet",
        [{"ts_code": "000001.SZ", "trade_date": "2026-03-02", "adj_factor": 2.0}],
    )
    settings = LakeConsoleSettings(
        lake_root=tmp_path,
        tushare_token=None,
        compute_bucket_count=1,
        duckdb_threads=1,
        duckdb_memory_limit="1GB",
        duckdb_temp_directory="_tmp/duckdb-test",
    )
    prepare = DuckDbComputePlanService(settings=settings).prepare_stk_mins_qfq_run(
        start_date="2026-03-02",
        end_date="2026-03-02",
        freqs=[30],
    )
    run_id = prepare["run"]["run_id"]

    with pytest.raises(RuntimeError, match="qfq factor coverage 未通过"):
        DuckDbComputeExecutorService(settings=settings).compute_stk_mins_qfq_candidates(run_id=run_id)

    manifest_root = tmp_path / "manifest" / "duckdb_compute" / "runs" / run_id
    run_payload = json.loads((manifest_root / "run.json").read_text(encoding="utf-8"))
    assert run_payload["status"] == "failed"
    unit_rows = read_parquet_rows(manifest_root / "units.parquet")
    assert unit_rows[0]["status"] == "failed"
    candidate_rows = read_parquet_rows(manifest_root / "candidate_parts.parquet")
    assert candidate_rows == []
    assert not (tmp_path / "_tmp" / "duckdb_compute" / run_id / "candidate_parts").exists()
    assert LakeJobLockService(LakeJobStateStore(tmp_path)).get_lock()["status"] == "idle"


def test_compute_stk_mins_qfq_candidates_checkpoints_in_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_minimal_inputs(tmp_path)
    _write_parquet(
        tmp_path / "research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-03/part-000.parquet",
        [
            {
                "ts_code": "600000.SH",
                "freq": 30,
                "trade_time": "2026-03-03 10:00:00",
                "open": 12.0,
                "high": 13.0,
                "low": 11.0,
                "close": 12.5,
                "vol": 200,
                "amount": 2500.0,
                "exchange": "SSE",
                "vwap": 12.2,
            }
        ],
    )
    _write_parquet(
        tmp_path / "raw_tushare/adj_factor/trade_date=2026-03-03/part-000.parquet",
        [{"ts_code": "600000.SH", "trade_date": "2026-03-03", "adj_factor": 2.0}],
    )
    settings = LakeConsoleSettings(
        lake_root=tmp_path,
        tushare_token=None,
        compute_bucket_count=8,
        compute_checkpoint_interval_units=10,
        duckdb_threads=1,
        duckdb_memory_limit="1GB",
        duckdb_temp_directory="_tmp/duckdb-test",
    )
    prepare = DuckDbComputePlanService(settings=settings).prepare_stk_mins_qfq_run(
        start_date="2026-03-02",
        end_date="2026-03-03",
        freqs=[30],
    )
    run_id = prepare["run"]["run_id"]
    write_counts = {"units": 0, "candidate_parts": 0}
    original_write_units = executor_module._write_units_manifest
    original_write_candidates = executor_module._write_candidate_parts_manifest

    def count_units(*args, **kwargs):  # type: ignore[no-untyped-def]
        write_counts["units"] += 1
        return original_write_units(*args, **kwargs)

    def count_candidates(*args, **kwargs):  # type: ignore[no-untyped-def]
        write_counts["candidate_parts"] += 1
        return original_write_candidates(*args, **kwargs)

    monkeypatch.setattr(executor_module, "_write_units_manifest", count_units)
    monkeypatch.setattr(executor_module, "_write_candidate_parts_manifest", count_candidates)

    summary = DuckDbComputeExecutorService(settings=settings).compute_stk_mins_qfq_candidates(run_id=run_id)

    assert summary["status"] == "compute_completed"
    assert summary["metrics"]["executed_unit_count"] == 2
    assert summary["metrics"]["candidate_part_count"] == 2
    assert write_counts == {"units": 1, "candidate_parts": 1}


def _write_minimal_inputs(lake_root: Path, *, include_day_factor: bool = True) -> None:
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
    if include_day_factor:
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
