from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")

from lake_console.backend.app.services.duckdb_compute_benchmark_service import DuckDbComputeBenchmarkService
from lake_console.backend.app.settings import LakeConsoleSettings


def test_duckdb_compute_benchmark_reads_sample_inputs(tmp_path: Path) -> None:
    lake_root = tmp_path
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
            },
            {
                "ts_code": "000001.SZ",
                "freq": 30,
                "trade_time": "2026-03-02 10:00:00",
                "open": 20.0,
                "high": 21.0,
                "low": 19.0,
                "close": 20.5,
                "vwap": 20.2,
                "vol": 200,
                "amount": 4040.0,
            },
        ],
    )
    _write_parquet(
        lake_root / "raw_tushare/adj_factor/trade_date=2026-03-02/part-000.parquet",
        [
            {"ts_code": "600000.SH", "trade_date": "2026-03-02", "adj_factor": 2.0},
            {"ts_code": "000001.SZ", "trade_date": "2026-03-02", "adj_factor": 4.0},
        ],
    )
    _write_parquet(
        lake_root / "raw_tushare/adj_factor/trade_date=2026-05-14/part-000.parquet",
        [
            {"ts_code": "600000.SH", "trade_date": "2026-05-14", "adj_factor": 4.0},
            {"ts_code": "000001.SZ", "trade_date": "2026-05-14", "adj_factor": 8.0},
        ],
    )
    _write_parquet(
        lake_root / "manifest/security_identity/security_identity_map.parquet",
        [
            {
                "latest_ts_code": "600000.SH",
                "source_ts_code": "600000.SH",
                "valid_from": "1999-01-01",
                "valid_to": None,
            },
            {
                "latest_ts_code": "000001.SZ",
                "source_ts_code": "000001.SZ",
                "valid_from": "1991-01-01",
                "valid_to": None,
            },
        ],
    )
    settings = LakeConsoleSettings(
        lake_root=lake_root,
        tushare_token=None,
        duckdb_threads=2,
        duckdb_memory_limit="1GB",
        duckdb_temp_directory="_tmp/duckdb-test",
        compute_bucket_count=8,
    )

    summary = DuckDbComputeBenchmarkService(settings=settings).run_stk_mins_qfq_sample(
        sample_month="2026-03",
        freqs=[30],
    )

    assert summary["config"]["duckdb_threads"] == 2
    assert summary["config"]["compute_bucket_count"] == 8
    assert summary["metrics"]["row_count"] == 2
    assert summary["metrics"]["security_count"] == 2
    assert summary["metrics"]["missing_adj_factor_rows"] == 0
    assert summary["metrics"]["missing_latest_adj_factor_rows"] == 0
    assert summary["metrics"]["non_positive_factor_rows"] == 0
    assert summary["metrics"]["identity_row_count"] == 2


def test_duckdb_compute_benchmark_rejects_temp_dir_outside_lake_root(tmp_path: Path) -> None:
    settings = LakeConsoleSettings(
        lake_root=tmp_path,
        tushare_token=None,
        duckdb_temp_directory="/tmp/outside-lake",
    )
    with pytest.raises(ValueError, match="DuckDB temp 目录必须位于 Lake Root 下"):
        DuckDbComputeBenchmarkService(settings=settings).run_stk_mins_qfq_sample(sample_month="2026-03", freqs=[30])


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False, engine="pyarrow", compression="zstd")
