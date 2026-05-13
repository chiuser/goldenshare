from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from lake_console.backend.app.services.parquet_writer import read_parquet_files, write_rows_to_parquet
from lake_console.backend.app.services.stk_mins_current_clean_missing_0930_repair_service import (
    StkMinsCurrentCleanMissing0930RepairService,
)


def test_repair_current_clean_missing_0930_dry_run_and_apply(tmp_path: Path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    trade_date = date(2024, 10, 31)
    affected_code = "002758.SZ"
    unaffected_code = "000001.SZ"
    csv_path = tmp_path / "stk_mins_clean_missing_0930_with_1min_availability.csv"

    _write_source_partition(tmp_path, trade_date=trade_date, ts_code=affected_code)
    _write_target_partition(
        tmp_path,
        trade_date=trade_date,
        freq=5,
        affected_code=affected_code,
        unaffected_code=unaffected_code,
    )
    _write_csv(csv_path, trade_date=trade_date, ts_code=affected_code, freq=5)

    service = StkMinsCurrentCleanMissing0930RepairService(
        lake_root=tmp_path,
        progress=lambda _: None,
        csv_path=csv_path,
    )

    dry_summary = service.repair(dry_run=True, apply=False)
    assert dry_summary["operation"] == "repair_current_clean_missing_0930"
    assert dry_summary["mode"] == "dry_run"
    assert dry_summary["targets_total"] == 1
    assert dry_summary["to_insert_total"] == 1
    assert dry_summary["already_present_total"] == 0
    assert dry_summary["partition_count"] == 1
    assert dry_summary["dry_run_partition_stats"][0]["freq"] == 5

    apply_summary = service.repair(dry_run=False, apply=True)
    assert apply_summary["mode"] == "apply"
    assert apply_summary["partitions_written_total"] == 1
    assert apply_summary["to_insert_total"] == 1

    rows = _read_partition_rows(tmp_path, trade_date=trade_date, freq=5)
    affected_rows = [row for row in rows if str(row["ts_code"]) == affected_code]
    unaffected_rows = [row for row in rows if str(row["ts_code"]) == unaffected_code]
    assert len(affected_rows) == 2
    assert len(unaffected_rows) == 1
    assert any(row["trade_time"].strftime("%H:%M:%S") == "09:30:00" for row in affected_rows)

    # idempotent
    dry_again = service.repair(dry_run=True, apply=False)
    assert dry_again["to_insert_total"] == 0
    assert dry_again["already_present_total"] == 1


def _write_csv(path: Path, *, trade_date: date, ts_code: str, freq: int) -> None:
    path.write_text(
        "issue_id,issue_type,status,latest_ts_code,freq,trade_date,expected_value,actual_value,expected_count,actual_count,action,reason,has_clean_1min_0930\n"
        f"test-1,missing_intraday_bar,needs_review,{ts_code},{freq},{trade_date.isoformat()},bar_count=49,bar_count=48,49,48,repair_required,unit-test,true\n",
        encoding="utf-8",
    )


def _write_source_partition(root: Path, *, trade_date: date, ts_code: str) -> None:
    rows = [
        {
            "ts_code": ts_code,
            "freq": 1,
            "trade_time": datetime.fromisoformat(f"{trade_date.isoformat()} 09:30:00"),
            "open": 10.0,
            "close": 10.1,
            "high": 10.2,
            "low": 9.9,
            "vol": 123,
            "amount": 1242.3,
            "trade_date": trade_date,
        },
        {
            "ts_code": ts_code,
            "freq": 1,
            "trade_time": datetime.fromisoformat(f"{trade_date.isoformat()} 09:31:00"),
            "open": 10.1,
            "close": 10.2,
            "high": 10.3,
            "low": 10.0,
            "vol": 50,
            "amount": 510.0,
            "trade_date": trade_date,
        },
    ]
    write_rows_to_parquet(rows, _partition_file(root, trade_date=trade_date, freq=1))


def _write_target_partition(
    root: Path,
    *,
    trade_date: date,
    freq: int,
    affected_code: str,
    unaffected_code: str,
) -> None:
    rows = [
        {
            "ts_code": affected_code,
            "freq": freq,
            "trade_time": datetime.fromisoformat(f"{trade_date.isoformat()} 09:35:00"),
            "open": 10.5,
            "close": 10.6,
            "high": 10.7,
            "low": 10.4,
            "vol": 500,
            "amount": 5300.0,
            "trade_date": trade_date,
        },
        {
            "ts_code": unaffected_code,
            "freq": freq,
            "trade_time": datetime.fromisoformat(f"{trade_date.isoformat()} 09:30:00"),
            "open": 8.0,
            "close": 8.1,
            "high": 8.2,
            "low": 7.9,
            "vol": 1,
            "amount": 8.1,
            "trade_date": trade_date,
        },
    ]
    write_rows_to_parquet(rows, _partition_file(root, trade_date=trade_date, freq=freq))


def _partition_file(root: Path, *, trade_date: date, freq: int) -> Path:
    return (
        root
        / "research"
        / "stk_mins_by_date_clean"
        / f"freq={freq}"
        / f"trade_date={trade_date.isoformat()}"
        / "part-00000.parquet"
    )


def _read_partition_rows(root: Path, *, trade_date: date, freq: int) -> list[dict]:
    files = sorted(
        (
            root
            / "research"
            / "stk_mins_by_date_clean"
            / f"freq={freq}"
            / f"trade_date={trade_date.isoformat()}"
        ).glob("*.parquet")
    )
    return read_parquet_files(files)
