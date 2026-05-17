from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("pyarrow")

from lake_console.backend.app.services.duckdb_compute_readiness_service import DuckDbComputeReadinessService
from lake_console.backend.app.services.lake_job_state import LakeJobLockService, LakeJobStateStore
from lake_console.backend.app.services.stk_mins_clean_next_gate import CleanNextGateStatus, CleanNextPartitionGateService
from lake_console.backend.app.settings import LakeConsoleSettings


def test_readiness_stk_mins_qfq_reports_ready_without_writes(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    settings = LakeConsoleSettings(lake_root=tmp_path, tushare_token=None, compute_bucket_count=2)

    summary = DuckDbComputeReadinessService(settings=settings).scan_stk_mins_qfq_readiness(
        start_date="2026-03-02",
        end_date="2026-03-02",
        freqs=[30],
    )

    assert summary["ready"] is True
    assert summary["blockers"] == []
    assert summary["checks"]["clean_next"]["partition_count"] == 1
    assert summary["checks"]["clean_next"]["partition_key_samples"] == ["freq=30/trade_date=2026-03-02"]
    assert "partition_keys" not in summary["checks"]["clean_next"]
    assert summary["checks"]["adj_factor"]["missing_target_trade_date_count"] == 0
    assert summary["checks"]["latest_adj_factor"]["latest_trade_date"] == "2026-05-14"
    assert summary["checks"]["security_identity_map"]["latest_code_count"] == 1
    assert summary["checks"]["lock"]["status"] == "idle"
    assert not (tmp_path / "manifest" / "duckdb_compute").exists()
    assert not (tmp_path / "_tmp" / "duckdb_compute").exists()


def test_readiness_stk_mins_qfq_blocks_missing_adj_factor(tmp_path: Path) -> None:
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
    settings = LakeConsoleSettings(lake_root=tmp_path, tushare_token=None)

    summary = DuckDbComputeReadinessService(settings=settings).scan_stk_mins_qfq_readiness(
        start_date="2026-03-02",
        end_date="2026-03-02",
        freqs=[30],
    )

    assert summary["ready"] is False
    assert "missing_adj_factor_partition" in {item["code"] for item in summary["blockers"]}
    assert summary["checks"]["adj_factor"]["missing_target_trade_date_count"] == 1


def test_readiness_stk_mins_qfq_blocks_active_lock_and_publishing_gate(tmp_path: Path) -> None:
    _write_minimal_inputs(tmp_path)
    LakeJobLockService(LakeJobStateStore(tmp_path)).acquire(run_id="running-run", profile_key="duckdb_compute_stk_mins_qfq")
    CleanNextPartitionGateService(lake_root=tmp_path).write_statuses(
        [
            CleanNextGateStatus(
                freq=30,
                trade_date=pd.Timestamp("2026-03-02").date(),
                clean_partition_path="research/stk_mins_by_date_clean_next/freq=30/trade_date=2026-03-02",
                source_run_id="source-run",
                clean_run_id="clean-run",
                write_revision="publishing-revision",
                status="publishing",
                issue_count=0,
                raw_rows=1,
                clean_rows=1,
                ledger_path="manifest/stk_mins_quality/ledger.parquet",
                message="publishing in progress",
            )
        ],
        run_id="gate-test",
    )
    settings = LakeConsoleSettings(lake_root=tmp_path, tushare_token=None)

    summary = DuckDbComputeReadinessService(settings=settings).scan_stk_mins_qfq_readiness(
        start_date="2026-03-02",
        end_date="2026-03-02",
        freqs=[30],
    )

    blocker_codes = {item["code"] for item in summary["blockers"]}
    assert "lake_write_lock_active" in blocker_codes
    assert "formal_gate_publishing_exists" in blocker_codes
    assert summary["checks"]["formal_gate"]["publishing_count"] == 1


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
                "exchange": "SSE",
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
