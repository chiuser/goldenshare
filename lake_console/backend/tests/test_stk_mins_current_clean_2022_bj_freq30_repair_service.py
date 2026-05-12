from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from lake_console.backend.app.services.parquet_writer import read_parquet_files, write_rows_to_parquet
from lake_console.backend.app.services.stk_mins_current_clean_2022_bj_freq30_repair_service import (
    LEDGER_PATH,
    SOURCE_FREQ,
    TARGET_END_DATE,
    TARGET_EXPECTED_ROWS_PER_CODE,
    TARGET_FREQ,
    TARGET_START_DATE,
    StkMinsCurrentClean2022BjFreq30RepairService,
)


def test_repair_current_clean_2022_bj_freq30_dry_run_and_apply(tmp_path: Path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    trade_date = TARGET_START_DATE
    affected_code = "920001.BJ"
    unaffected_code = "000001.SZ"
    _write_source_15min_partition(tmp_path, trade_date=trade_date, ts_code=affected_code, include_post_market=True)
    _write_target_30min_partition(tmp_path, trade_date=trade_date, affected_code=affected_code, unaffected_code=unaffected_code)
    _write_ledger(tmp_path, trade_date=trade_date, ts_code=affected_code)

    service = StkMinsCurrentClean2022BjFreq30RepairService(lake_root=tmp_path, progress=lambda _: None)

    dry_summary = service.repair(dry_run=True, apply=False)
    assert dry_summary["operation"] == "repair_current_clean_2022_bj_freq30"
    assert dry_summary["mode"] == "dry_run"
    assert dry_summary["source_freq"] == SOURCE_FREQ
    assert dry_summary["target_freq"] == TARGET_FREQ
    assert dry_summary["affected_trade_dates"] == 1
    assert dry_summary["affected_codes_total"] == 1
    assert dry_summary["old_affected_rows_total"] == 6
    assert dry_summary["rebuilt_rows_total"] == TARGET_EXPECTED_ROWS_PER_CODE

    apply_summary = service.repair(dry_run=False, apply=True)
    assert apply_summary["mode"] == "apply"
    assert apply_summary["run_id"]

    rows = _read_partition_rows(tmp_path, freq=TARGET_FREQ, trade_date=trade_date)
    affected_rows = [row for row in rows if str(row["ts_code"]) == affected_code]
    unaffected_rows = [row for row in rows if str(row["ts_code"]) == unaffected_code]
    assert len(affected_rows) == TARGET_EXPECTED_ROWS_PER_CODE
    assert len(unaffected_rows) == 1
    assert len(rows) == TARGET_EXPECTED_ROWS_PER_CODE + 1

    times = [row["trade_time"].strftime("%H:%M:%S") for row in sorted(affected_rows, key=lambda item: item["trade_time"])]
    assert times == ["09:30:00", "10:00:00", "10:30:00", "11:00:00", "11:30:00", "13:30:00", "14:00:00", "14:30:00", "15:00:00"]


def _write_source_15min_partition(
    root: Path,
    *,
    trade_date: date,
    ts_code: str,
    include_post_market: bool = False,
) -> None:
    times = [
        "09:30:00",
        "09:45:00",
        "10:00:00",
        "10:15:00",
        "10:30:00",
        "10:45:00",
        "11:00:00",
        "11:15:00",
        "11:30:00",
        "13:15:00",
        "13:30:00",
        "13:45:00",
        "14:00:00",
        "14:15:00",
        "14:30:00",
        "14:45:00",
        "15:00:00",
    ]
    rows: list[dict] = []
    for index, text in enumerate(times):
        value = 10.0 + index * 0.1
        rows.append(
            {
                "ts_code": ts_code,
                "freq": SOURCE_FREQ,
                "trade_time": datetime.fromisoformat(f"{trade_date.isoformat()} {text}"),
                "open": value,
                "close": value + 0.01,
                "high": value + 0.02,
                "low": value - 0.01,
                "vol": 100 + index,
                "amount": (100 + index) * (value + 0.01),
                "trade_date": trade_date,
            }
        )
    if include_post_market:
        rows.extend(
            [
                {
                    "ts_code": ts_code,
                    "freq": SOURCE_FREQ,
                    "trade_time": datetime.fromisoformat(f"{trade_date.isoformat()} 15:15:00"),
                    "open": 99.0,
                    "close": 99.1,
                    "high": 99.2,
                    "low": 98.9,
                    "vol": 3,
                    "amount": 297.3,
                    "trade_date": trade_date,
                },
                {
                    "ts_code": ts_code,
                    "freq": SOURCE_FREQ,
                    "trade_time": datetime.fromisoformat(f"{trade_date.isoformat()} 15:30:00"),
                    "open": 99.2,
                    "close": 99.3,
                    "high": 99.4,
                    "low": 99.1,
                    "vol": 4,
                    "amount": 397.2,
                    "trade_date": trade_date,
                },
            ]
        )
    write_rows_to_parquet(rows, _partition_file(root, freq=SOURCE_FREQ, trade_date=trade_date))


def _write_target_30min_partition(root: Path, *, trade_date: date, affected_code: str, unaffected_code: str) -> None:
    contaminated_times = ["10:00:00", "10:30:00", "11:00:00", "13:30:00", "14:00:00", "14:30:00"]
    rows: list[dict] = []
    for index, text in enumerate(contaminated_times):
        value = 20.0 + index * 0.1
        rows.append(
            {
                "ts_code": affected_code,
                "freq": TARGET_FREQ,
                "trade_time": datetime.fromisoformat(f"{trade_date.isoformat()} {text}"),
                "open": value,
                "close": value + 0.01,
                "high": value + 0.02,
                "low": value - 0.01,
                "vol": 200 + index,
                "amount": (200 + index) * (value + 0.01),
                "trade_date": trade_date,
            }
        )
    rows.append(
        {
            "ts_code": unaffected_code,
            "freq": TARGET_FREQ,
            "trade_time": datetime.fromisoformat(f"{trade_date.isoformat()} 10:00:00"),
            "open": 8.0,
            "close": 8.1,
            "high": 8.2,
            "low": 7.9,
            "vol": 1,
            "amount": 8.1,
            "trade_date": trade_date,
        }
    )
    write_rows_to_parquet(rows, _partition_file(root, freq=TARGET_FREQ, trade_date=trade_date))


def _write_ledger(root: Path, *, trade_date: date, ts_code: str) -> None:
    rows = [
        {
            "issue_id": "test-2022-bj-30m-1",
            "issue_type": "missing_intraday_bar",
            "trade_date": trade_date,
            "freq": TARGET_FREQ,
            "expected_value": "bar_count=9",
            "actual_value": "bar_count=6",
            "latest_ts_code": ts_code,
        },
        {
            "issue_id": "out-of-range-should-be-ignored",
            "issue_type": "missing_intraday_bar",
            "trade_date": TARGET_END_DATE.replace(year=2023),
            "freq": TARGET_FREQ,
            "expected_value": "bar_count=9",
            "actual_value": "bar_count=6",
            "latest_ts_code": ts_code,
        },
    ]
    write_rows_to_parquet(rows, root / LEDGER_PATH)


def _partition_file(root: Path, *, freq: int, trade_date: date) -> Path:
    return (
        root
        / "research"
        / "stk_mins_by_date_clean"
        / f"freq={freq}"
        / f"trade_date={trade_date.isoformat()}"
        / "part-00000.parquet"
    )


def _read_partition_rows(root: Path, *, freq: int, trade_date: date) -> list[dict]:
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
