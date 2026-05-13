from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from lake_console.backend.app.services.affected_partition import AffectedPartition
from lake_console.backend.app.services.parquet_writer import read_parquet_rows
from lake_console.backend.app.services.stk_mins_clean_next_gate import CleanNextPartitionGateService
from lake_console.backend.app.services.stk_mins_clean_next_refresh_service import CleanNextRefreshService


def test_clean_next_refresh_rebuilds_partition_writes_ledger_and_passed_gate(tmp_path: Path) -> None:
    _write_stock_basic(tmp_path)
    _write_raw_partition(
        tmp_path,
        freq=1,
        trade_date=date(2026, 5, 8),
        rows=[
            _raw_row("000001.SZ", 1, f"2026-05-08 {hour:02d}:{minute:02d}:00")
            for hour, minute in _minute_times(include_after_hours=False)
        ],
    )

    summary = CleanNextRefreshService(lake_root=tmp_path, progress=lambda _: None).refresh(
        affected_partitions=[_affected_partition(tmp_path, freq=1, trade_date=date(2026, 5, 8))],
        dry_run=False,
        apply=True,
    )

    clean_file = tmp_path / "research" / "stk_mins_by_date_clean_next" / "freq=1" / "trade_date=2026-05-08" / "part-000.parquet"
    gate_rows = CleanNextPartitionGateService(lake_root=tmp_path).read_statuses()
    assert summary["status"] == "passed"
    assert summary["partition_results"][0]["issue_count"] == 0
    assert clean_file.exists()
    assert len(read_parquet_rows(clean_file)) == 241
    assert gate_rows[0]["status"] == "passed"
    assert gate_rows[0]["issue_count"] == 0
    assert gate_rows[0]["raw_rows"] == 241
    assert gate_rows[0]["clean_rows"] == 241


def test_clean_next_refresh_blocks_gate_when_scoped_audit_finds_issue(tmp_path: Path) -> None:
    _write_stock_basic(tmp_path)
    _write_raw_partition(
        tmp_path,
        freq=1,
        trade_date=date(2026, 5, 8),
        rows=[
            _raw_row("000001.SZ", 1, f"2026-05-08 {hour:02d}:{minute:02d}:00")
            for hour, minute in _minute_times(include_after_hours=False)[:-1]
        ],
    )

    summary = CleanNextRefreshService(lake_root=tmp_path, progress=lambda _: None).refresh(
        affected_partitions=[_affected_partition(tmp_path, freq=1, trade_date=date(2026, 5, 8))],
        dry_run=False,
        apply=True,
    )

    gate_rows = CleanNextPartitionGateService(lake_root=tmp_path).read_statuses()
    ledger_rows = read_parquet_rows(tmp_path / "manifest" / "stk_mins_quality" / "clean_next_completeness_issue_ledger.parquet")
    assert summary["status"] == "blocked"
    assert summary["partition_results"][0]["issue_count"] == 1
    assert gate_rows[0]["status"] == "blocked"
    assert gate_rows[0]["issue_count"] == 1
    assert len(ledger_rows) == 1
    assert ledger_rows[0]["issue_state"] == "open"
    assert ledger_rows[0]["severity"] == "block"


def _write_stock_basic(root: Path) -> None:
    _write_parquet(
        root / "manifest" / "security_universe" / "tushare_stock_basic.parquet",
        [{"ts_code": "000001.SZ", "list_date": "20100101", "delist_date": None}],
    )


def _write_raw_partition(root: Path, *, freq: int, trade_date: date, rows: list[dict[str, object]]) -> None:
    _write_parquet(
        root / "raw_tushare" / "stk_mins_by_date" / f"freq={freq}" / f"trade_date={trade_date.isoformat()}" / "part-000.parquet",
        rows,
    )


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False, engine="pyarrow", compression="zstd")


def _raw_row(ts_code: str, freq: int, trade_time: str) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": freq,
        "trade_time": pd.Timestamp(trade_time),
        "open": 10.0,
        "close": 10.1,
        "high": 10.2,
        "low": 9.9,
        "vol": 1000,
        "amount": 10100.0,
        "exchange": None,
        "vwap": None,
    }


def _affected_partition(root: Path, *, freq: int, trade_date: date) -> AffectedPartition:
    partition_path = root / "raw_tushare" / "stk_mins_by_date" / f"freq={freq}" / f"trade_date={trade_date.isoformat()}"
    return AffectedPartition(
        dataset_key="stk_mins",
        source_key="tushare",
        layer="raw_tushare",
        partition_grain="trade_date",
        partition_values={"freq": str(freq), "trade_date": trade_date.isoformat()},
        partition_path=str(partition_path.relative_to(root)),
        source_run_id="raw-run-1",
        write_revision=f"raw-run-1:raw_tushare:freq={freq}:trade_date={trade_date.isoformat()}",
        rows_written=len(read_parquet_rows(partition_path / "part-000.parquet")),
        bytes_written=sum(item.stat().st_size for item in partition_path.glob("*.parquet")),
    )


def _minute_times(*, include_after_hours: bool) -> list[tuple[int, int]]:
    times = [(value // 60, value % 60) for value in range(9 * 60 + 30, 11 * 60 + 30 + 1)]
    times.extend((value // 60, value % 60) for value in range(13 * 60 + 1, 15 * 60 + 1))
    if include_after_hours:
        times.extend((15, minute) for minute in range(1, 31))
    return times
