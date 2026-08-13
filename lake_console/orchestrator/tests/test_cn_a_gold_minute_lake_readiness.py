from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.asset_guards.cn_a_gold_minute_lake_readiness import (
    batch_canonical_gold_minute_lake_readiness,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    CN_A_GOLD_MINUTE_FREQS,
    expected_gold_minute_times,
)

TRADE_DATE = "2026-08-12"
CHECK_NAMES = tuple(f"gold_test_{freq}m_core_check" for freq in CN_A_GOLD_MINUTE_FREQS)


def _target_path(root: Path, freq: int, trade_date: str) -> Path:
    return root / f"freq={freq}" / f"trade_date={trade_date}" / "part-000.parquet"


def _source_path(root: Path, freq: int, trade_date: str) -> Path:
    return root / "source" / f"freq={freq}" / f"trade_date={trade_date}.parquet"


def _write_gold_partition(
    root: Path,
    *,
    freq: int,
    trade_date: str = TRADE_DATE,
    invalid_time: str | None = None,
) -> Path:
    path = _target_path(root, freq, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    times = (
        (invalid_time,)
        if invalid_time is not None
        else expected_gold_minute_times("SSE", freq)
    )
    rows = [
        (
            "000001.SH",
            freq,
            trade_date,
            f"{trade_date} {trade_time}",
            10.0,
            11.0,
            9.0,
            10.5,
            1.0,
            10.5,
            "SSE",
            10.5 if freq == 1 else None,
        )
        for trade_time in times
    ]
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE rows (
              ts_code VARCHAR, freq INTEGER, trade_date DATE,
              trade_time TIMESTAMP, open DOUBLE, high DOUBLE, low DOUBLE,
              close DOUBLE, vol DOUBLE, amount DOUBLE, exchange VARCHAR,
              vwap DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute(copy_query_to_parquet("SELECT * FROM rows", path))
    return path


def _readiness(connection, root: Path):
    return batch_canonical_gold_minute_lake_readiness(
        connection=connection,
        lake_root=root,
        expected_trade_dates=(TRADE_DATE,),
        registered_trade_days=(TRADE_DATE,),
        target_path_builder=_target_path,
        source_path_builder=_source_path,
        check_names=CHECK_NAMES,
        expected_code_provider=lambda _date: ("000001.SH",),
        asset_family="test_family",
    )


def test_batch_readiness_marks_all_missing_as_not_materialized(tmp_path: Path) -> None:
    with duckdb.connect(":memory:") as connection:
        batch = _readiness(connection, tmp_path)

    status = batch.status_for_trade_date(TRADE_DATE)
    assert status.ready is False
    assert status.materialized is False
    assert status.summary["reason_code"] == "file_missing"
    assert batch.scanned_file_count == 0


def test_batch_readiness_marks_partial_family_as_materialized_failure(
    tmp_path: Path,
) -> None:
    _write_gold_partition(tmp_path, freq=1)
    with duckdb.connect(":memory:") as connection:
        batch = _readiness(connection, tmp_path)

    status = batch.status_for_trade_date(TRADE_DATE)
    assert status.ready is False
    assert status.materialized is True
    assert status.summary["reason_code"] == "partial_materialization"
    assert status.summary["existing_file_count"] == 1
    assert batch.scanned_file_count == 0


def test_batch_readiness_scans_seven_files_and_reports_ready(tmp_path: Path) -> None:
    for freq in CN_A_GOLD_MINUTE_FREQS:
        _write_gold_partition(tmp_path, freq=freq)
    with duckdb.connect(":memory:") as connection:
        batch = _readiness(connection, tmp_path)

    status = batch.status_for_trade_date(TRADE_DATE)
    assert status.ready is True
    assert status.materialized is True
    assert status.checks_passed is True
    assert status.summary["reason_code"] == "ready"
    assert batch.scanned_file_count == 7


def test_batch_readiness_fails_closed_on_non_one_minute_0930(tmp_path: Path) -> None:
    for freq in CN_A_GOLD_MINUTE_FREQS:
        _write_gold_partition(tmp_path, freq=freq)
    _write_gold_partition(tmp_path, freq=5, invalid_time="09:30:00")
    with duckdb.connect(":memory:") as connection:
        batch = _readiness(connection, tmp_path)

    status = batch.status_for_trade_date(TRADE_DATE)
    assert status.ready is False
    assert status.materialized is True
    assert status.summary["reason_code"] == "core_check_failed"
    assert CHECK_NAMES[1] in status.failed_check_names
    assert any("non_1m_0930" in item for item in status.summary["failed_rules"])


def test_batch_readiness_rejects_more_than_ten_dates(tmp_path: Path) -> None:
    dates = tuple(f"2026-08-{day:02d}" for day in range(1, 12))
    with (
        duckdb.connect(":memory:") as connection,
        pytest.raises(ValueError, match="exceeds 10 dates"),
    ):
        batch_canonical_gold_minute_lake_readiness(
            connection=connection,
            lake_root=tmp_path,
            expected_trade_dates=dates,
            registered_trade_days=dates,
            target_path_builder=_target_path,
            source_path_builder=_source_path,
            check_names=CHECK_NAMES,
            expected_code_provider=lambda _date: ("000001.SH",),
            asset_family="test_family",
        )
