from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from lake_console.backend.app.services.parquet_writer import read_parquet_files, write_rows_to_parquet
from lake_console.backend.app.services.stk_mins_current_clean_20241030_multifreq_repair_service import (
    EXPECTED_TARGET_ROWS_PER_CODE,
    LEDGER_PATH,
    SOURCE_FREQ,
    TARGET_FREQS,
    TARGET_TRADE_DATE,
    StkMinsCurrentClean20241030MultifreqRepairService,
)


def test_repair_current_clean_20241030_multifreq_dry_run_and_apply(tmp_path: Path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    affected_code = "920001.BJ"
    unaffected_code = "000001.SZ"
    _write_clean_source_partition(tmp_path, ts_code=affected_code)
    _write_target_partitions_with_contamination(tmp_path, affected_code=affected_code, unaffected_code=unaffected_code)
    _write_issue_ledger(tmp_path, affected_code=affected_code)

    service = StkMinsCurrentClean20241030MultifreqRepairService(lake_root=tmp_path, progress=lambda _: None)
    dry_summary = service.repair(dry_run=True, apply=False)

    assert dry_summary["operation"] == "repair_current_clean_20241030_multifreq"
    assert dry_summary["mode"] == "dry_run"
    assert dry_summary["source_freq"] == SOURCE_FREQ
    assert dry_summary["target_freqs"] == list(TARGET_FREQS)
    assert dry_summary["source_checks"]["validated_codes"] == 1
    for item in dry_summary["dry_run_freq_stats"]:
        assert item["old_affected_rows"] == 271
        assert item["rebuilt_rows"] == EXPECTED_TARGET_ROWS_PER_CODE[item["freq"]]
        assert item["target_rows_after"] == EXPECTED_TARGET_ROWS_PER_CODE[item["freq"]] + 1

    apply_summary = service.repair(dry_run=False, apply=True)
    assert apply_summary["mode"] == "apply"
    assert apply_summary["run_id"]
    assert len(apply_summary["apply_freq_stats"]) == 4

    for freq in TARGET_FREQS:
        rows = _read_partition_rows(tmp_path, freq=freq, trade_date=TARGET_TRADE_DATE)
        affected_rows = [row for row in rows if str(row["ts_code"]) == affected_code]
        unaffected_rows = [row for row in rows if str(row["ts_code"]) == unaffected_code]
        assert len(affected_rows) == EXPECTED_TARGET_ROWS_PER_CODE[freq]
        assert len(unaffected_rows) == 1
        assert len(rows) == EXPECTED_TARGET_ROWS_PER_CODE[freq] + 1


def _write_clean_source_partition(root: Path, *, ts_code: str) -> None:
    rows = _build_271_rows(ts_code=ts_code, freq=1)
    write_rows_to_parquet(rows, _partition_file(root, freq=1, trade_date=TARGET_TRADE_DATE))


def _write_target_partitions_with_contamination(root: Path, *, affected_code: str, unaffected_code: str) -> None:
    source_rows = _build_271_rows(ts_code=affected_code, freq=1)
    for freq in TARGET_FREQS:
        contaminated = []
        for row in source_rows:
            contaminated.append({**row, "freq": freq})
        contaminated.append(
            {
                "ts_code": unaffected_code,
                "freq": freq,
                "trade_time": datetime(2024, 10, 30, 9, 30, 0),
                "open": 10.0,
                "close": 10.0,
                "high": 10.0,
                "low": 10.0,
                "vol": 1,
                "amount": 10.0,
                "trade_date": TARGET_TRADE_DATE,
            }
        )
        write_rows_to_parquet(contaminated, _partition_file(root, freq=freq, trade_date=TARGET_TRADE_DATE))


def _write_issue_ledger(root: Path, *, affected_code: str) -> None:
    rows = []
    for freq in TARGET_FREQS:
        rows.append(
            {
                "issue_id": f"test-{freq}",
                "trade_date": TARGET_TRADE_DATE,
                "freq": freq,
                "actual_value": "bar_count=271",
                "latest_ts_code": affected_code,
            }
        )
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


def _build_271_rows(*, ts_code: str, freq: int) -> list[dict]:
    rows: list[dict] = []
    rows.extend(_build_time_rows(ts_code=ts_code, freq=freq, start=time(9, 30), minutes=121))
    rows.extend(_build_time_rows(ts_code=ts_code, freq=freq, start=time(13, 1), minutes=120))
    rows.extend(_build_time_rows(ts_code=ts_code, freq=freq, start=time(15, 1), minutes=30))
    return rows


def _build_time_rows(*, ts_code: str, freq: int, start: time, minutes: int) -> list[dict]:
    base = datetime(2024, 10, 30, start.hour, start.minute, 0)
    rows: list[dict] = []
    for index in range(minutes):
        value = 10.0 + index * 0.01 + start.hour * 0.001
        rows.append(
            {
                "ts_code": ts_code,
                "freq": freq,
                "trade_time": base + timedelta(minutes=index),
                "open": value,
                "close": value + 0.01,
                "high": value + 0.02,
                "low": value - 0.01,
                "vol": 100 + index,
                "amount": (100 + index) * (value + 0.01),
                "trade_date": TARGET_TRADE_DATE,
            }
        )
    return rows
