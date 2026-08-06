from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from time import perf_counter
import tracemalloc

import duckdb
import pytest

from orchestrator.defs.bootstrap.major_index_mins_bootstrap_plan import (
    MajorIndexMinsBootstrapPlanError,
    MajorIndexMinsDatePlan,
    build_date_plan,
    build_source_plan,
    run_dry_run,
)
from orchestrator.defs.paths import (
    raw_major_index_mins_path,
    silver_trade_calendar_path,
)


class _MemoryDuckDB:
    @contextmanager
    def connect(self):
        connection = duckdb.connect(":memory:")
        try:
            yield connection
        finally:
            connection.close()


def _calendar(root: Path, dates: tuple[str, ...]) -> None:
    path = silver_trade_calendar_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(f"(DATE '{value}', 'SSE', true)" for value in dates)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"COPY (SELECT * FROM (VALUES {values}) AS t(trade_date, exchange, is_open)) TO ? (FORMAT PARQUET)",
            [str(path)],
        )


def test_date_and_source_plan_use_calendar_scope_and_bounded_windows(
    tmp_path: Path,
) -> None:
    dates = ("2025-01-02", "2025-01-03")
    _calendar(tmp_path, dates)
    with duckdb.connect(":memory:") as connection:
        date_plan = build_date_plan(connection=connection, lake_root=tmp_path)
    source_plan = build_source_plan(date_plan)
    assert date_plan.expected_trade_dates == dates
    assert len(date_plan.fingerprint) == 64
    assert len(source_plan.windows) == 50
    assert source_plan.request_count_by_frequency == {
        "1min": 10,
        "5min": 10,
        "15min": 10,
        "30min": 10,
        "60min": 10,
    }
    assert all(window.expected_row_count < 8_000 for window in source_plan.windows)


def test_duplicate_calendar_date_fails_closed(tmp_path: Path) -> None:
    _calendar(tmp_path, ("2025-01-02", "2025-01-02"))
    with (
        duckdb.connect(":memory:") as connection,
        pytest.raises(
            MajorIndexMinsBootstrapPlanError,
        ),
    ):
        build_date_plan(connection=connection, lake_root=tmp_path)


def test_dry_run_reports_file_disk_and_zero_write_contract(tmp_path: Path) -> None:
    dates = ("2025-01-02", "2025-01-03")
    _calendar(tmp_path, dates)

    report = run_dry_run(
        lake_root=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
    )
    assert report.should_stop is False
    assert report.expected_raw_file_count == 10
    assert report.expected_silver_file_count == 14
    assert report.expected_file_count == 24
    assert report.disk_budget.estimated_required_bytes > 0
    assert report.to_dict()["source_request_count"] == 0
    assert report.to_dict()["writes"] == {
        "formal_lake": 0,
        "dagster_db": 0,
        "dynamic_partitions": 0,
        "dagster_events": 0,
    }


def test_invalid_existing_target_blocks_without_overwrite(tmp_path: Path) -> None:
    _calendar(tmp_path, ("2025-01-02",))
    path = raw_major_index_mins_path(tmp_path, "1min", "2025-01-02")
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "COPY (SELECT 1 AS wrong_column) TO ? (FORMAT PARQUET)",
            [str(path)],
        )

    report = run_dry_run(
        lake_root=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
    )
    assert report.should_stop is True
    assert "invalid_existing_target" in report.stop_reason_codes
    assert path.exists()


def test_bootstrap_cli_has_no_apply_or_event_write_path() -> None:
    path = (
        Path(__file__).parents[1]
        / "src/orchestrator/defs/bootstrap/major_index_mins_bootstrap_cli.py"
    )
    source = path.read_text()
    assert 'subparsers.add_parser("dry-run")' in source
    assert "confirm-lake-write" not in source
    assert "os.replace" not in source
    assert "report_runless_asset_event" not in source
    assert "TushareResource" not in source


def test_full_history_source_planning_stays_bounded() -> None:
    current = date(2009, 1, 5)
    end = date(2026, 8, 4)
    dates: list[str] = []
    while current <= end:
        if current.weekday() < 5:
            dates.append(current.isoformat())
        current += timedelta(days=1)
    date_plan = MajorIndexMinsDatePlan(
        start_date=dates[0],
        end_date=dates[-1],
        expected_trade_dates=tuple(dates),
        fingerprint="b" * 64,
    )

    tracemalloc.start()
    started_at = perf_counter()
    source_plan = build_source_plan(date_plan)
    elapsed_ms = (perf_counter() - started_at) * 1000
    _, peak_memory_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(source_plan.windows) < 5_000
    assert all(window.expected_row_count < 8_000 for window in source_plan.windows)
    assert elapsed_ms < 3_000
    assert peak_memory_bytes < 64 * 1024 * 1024
