from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("pyarrow")

from lake_console.backend.app.services.lake_job_state import LakeJobLockBusyError, LakeJobLockService, LakeJobStateStore
from lake_console.backend.app.services.parquet_writer import read_parquet_rows
from lake_console.backend.app.services.duckdb_compute_plan_service import DuckDbComputePlanService
from lake_console.backend.app.settings import LakeConsoleSettings


def test_plan_stk_mins_qfq_builds_dry_run_graph_without_writes(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = LakeConsoleSettings(
        lake_root=tmp_path,
        tushare_token=None,
        compute_bucket_count=2,
        duckdb_threads=3,
        duckdb_memory_limit="2GB",
        duckdb_temp_directory="_tmp/duckdb-test",
    )

    summary = DuckDbComputePlanService(settings=settings).plan_stk_mins_qfq(
        start_date="2026-03-02",
        end_date="2026-03-02",
        freqs=[30],
    )

    assert summary["ready"] is True
    assert summary["run"]["status"] == "planned"
    assert summary["run"]["effective_config"]["compute_bucket_count"] == 2
    assert summary["metrics"] == {
        "partition_count": 1,
        "unit_count": 2,
        "publish_partition_count": 1,
        "expected_candidate_part_count": 2,
    }
    assert [unit["unit_key"] for unit in summary["units"]] == [
        "freq=30/trade_date=2026-03-02/bucket=00",
        "freq=30/trade_date=2026-03-02/bucket=01",
    ]
    assert summary["publish_partitions"][0]["partition_key"] == "freq=30/trade_date=2026-03-02"
    assert summary["candidate_part_manifest"]["status"] == "not_created_in_dry_run"
    source_roles = {item["source_role"] for item in summary["run"]["input_snapshot"]["source_items"]}
    assert source_roles == {"clean_next", "adj_factor", "latest_adj_factor", "security_identity_map"}
    assert summary["lock"]["status"] == "idle"
    assert not (tmp_path / "_tmp" / "duckdb_compute").exists()


def test_plan_stk_mins_qfq_blocks_when_adj_factor_is_missing(tmp_path: Path) -> None:
    _write_parquet(
        tmp_path / "research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-02/part-000.parquet",
        [{"ts_code": "600000.SH", "freq": 30, "trade_time": "2026-03-02 10:00:00", "close": 10.5}],
    )
    _write_parquet(
        tmp_path / "raw_tushare/adj_factor/trade_date=2026-05-14/part-000.parquet",
        [{"ts_code": "600000.SH", "trade_date": "2026-05-14", "adj_factor": 4.0}],
    )
    _write_parquet(
        tmp_path / "manifest/security_identity/security_identity_map.parquet",
        [{"latest_ts_code": "600000.SH", "source_ts_code": "600000.SH"}],
    )
    settings = LakeConsoleSettings(lake_root=tmp_path, tushare_token=None, compute_bucket_count=2)

    summary = DuckDbComputePlanService(settings=settings).plan_stk_mins_qfq(
        start_date="2026-03-02",
        end_date="2026-03-02",
        freqs=[30],
    )

    assert summary["ready"] is False
    assert summary["run"]["status"] == "blocked"
    assert summary["metrics"]["unit_count"] == 0
    assert [blocker["code"] for blocker in summary["blockers"]] == ["missing_adj_factor_partition"]


def test_prepare_stk_mins_qfq_run_persists_manifest_and_releases_lock(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = LakeConsoleSettings(lake_root=tmp_path, tushare_token=None, compute_bucket_count=2)

    summary = DuckDbComputePlanService(settings=settings).prepare_stk_mins_qfq_run(
        start_date="2026-03-02",
        end_date="2026-03-02",
        freqs=[30],
    )

    assert summary["ready"] is True
    assert summary["manifest"]["persisted"] is True
    assert summary["lock_acquired"]["status"] == "running"
    assert summary["lock_after"]["status"] == "idle"
    manifest_root = tmp_path / summary["manifest"]["manifest_root"]
    assert (manifest_root / "run.json").exists()
    assert (manifest_root / "units.parquet").exists()
    assert (manifest_root / "candidate_parts.parquet").exists()
    assert (manifest_root / "publish_partitions.parquet").exists()
    assert (manifest_root / "events.jsonl").exists()
    run_payload = json.loads((manifest_root / "run.json").read_text(encoding="utf-8"))
    assert run_payload["status"] == "planned"
    assert run_payload["metrics"]["unit_count"] == 2
    unit_rows = read_parquet_rows(manifest_root / "units.parquet")
    assert len(unit_rows) == 2
    assert unit_rows[0]["unit_key"] == "freq=30/trade_date=2026-03-02/bucket=00"
    candidate_rows = read_parquet_rows(manifest_root / "candidate_parts.parquet")
    assert candidate_rows == []
    publish_rows = read_parquet_rows(manifest_root / "publish_partitions.parquet")
    assert len(publish_rows) == 1
    assert publish_rows[0]["partition_key"] == "freq=30/trade_date=2026-03-02"
    events = [json.loads(line) for line in (manifest_root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events[0]["event_type"] == "manifest_prepared"
    assert LakeJobLockService(LakeJobStateStore(tmp_path)).get_lock()["status"] == "idle"
    assert not (tmp_path / "_tmp" / "duckdb_compute").exists()
    assert not (tmp_path / "manifest" / "duckdb_compute" / "_tmp").exists()


def test_prepare_stk_mins_qfq_run_does_not_write_manifest_when_plan_blocked(tmp_path: Path) -> None:
    _write_parquet(
        tmp_path / "research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-02/part-000.parquet",
        [{"ts_code": "600000.SH", "freq": 30, "trade_time": "2026-03-02 10:00:00", "close": 10.5}],
    )
    _write_parquet(
        tmp_path / "raw_tushare/adj_factor/trade_date=2026-05-14/part-000.parquet",
        [{"ts_code": "600000.SH", "trade_date": "2026-05-14", "adj_factor": 4.0}],
    )
    _write_parquet(
        tmp_path / "manifest/security_identity/security_identity_map.parquet",
        [{"latest_ts_code": "600000.SH", "source_ts_code": "600000.SH"}],
    )
    settings = LakeConsoleSettings(lake_root=tmp_path, tushare_token=None, compute_bucket_count=2)

    summary = DuckDbComputePlanService(settings=settings).prepare_stk_mins_qfq_run(
        start_date="2026-03-02",
        end_date="2026-03-02",
        freqs=[30],
    )

    assert summary["ready"] is False
    assert summary["manifest"]["persisted"] is False
    assert not (tmp_path / "manifest" / "duckdb_compute").exists()
    assert LakeJobLockService(LakeJobStateStore(tmp_path)).get_lock()["status"] == "idle"


def test_prepare_stk_mins_qfq_run_respects_existing_global_lock(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    lock_service = LakeJobLockService(LakeJobStateStore(tmp_path))
    lock_service.acquire(run_id="existing-run", profile_key="existing-profile")
    settings = LakeConsoleSettings(lake_root=tmp_path, tushare_token=None, compute_bucket_count=2)

    with pytest.raises(LakeJobLockBusyError):
        DuckDbComputePlanService(settings=settings).prepare_stk_mins_qfq_run(
            start_date="2026-03-02",
            end_date="2026-03-02",
            freqs=[30],
        )
    assert not (tmp_path / "manifest" / "duckdb_compute").exists()
    assert lock_service.get_lock()["run_id"] == "existing-run"


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
                "vwap": 10.2,
                "vol": 100,
                "amount": 1020.0,
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
