from datetime import datetime, time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import duckdb

from orchestrator.defs.asset_guards.bounded_continuity import (
    DEFAULT_CONTINUITY_SAMPLE_LIMIT,
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    build_continuity_cursor_details,
    build_registered_gap_status,
    load_expected_trade_date_window,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.duckdb_sql import duckdb_string


def _write_calendar_parquet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (
                VALUES
                  ('SSE', true, DATE '2026-06-10'),
                  ('SSE', true, DATE '2026-06-11'),
                  ('SSE', true, DATE '2026-06-12'),
                  ('SSE', false, DATE '2026-06-14'),
                  ('SSE', true, DATE '2026-06-15'),
                  ('SZSE', true, DATE '2026-06-15'),
                  ('SSE', true, DATE '2026-06-16'),
                  ('SSE', true, DATE '2026-06-17')
              ) AS calendar(exchange, is_open, trade_date)
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )


def _ready_status(trade_date: str) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=True,
        materialized=True,
        checks_passed=True,
        reason="ready",
    )


def _missing_status(trade_date: str) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=False,
        checks_passed=False,
        reason="missing_materialization",
        missing_file_paths=(f"/lake/{trade_date}.parquet",),
    )


class BoundedContinuityTests(unittest.TestCase):
    def test_expected_date_window_respects_min_same_day_and_window_limit(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            calendar_path = Path(temp_dir) / "calendar.parquet"
            _write_calendar_parquet(calendar_path)
            with duckdb.connect(database=":memory:") as connection:
                before_window = load_expected_trade_date_window(
                    connection,
                    calendar_path,
                    evaluated_at=datetime(2026, 6, 17, 5, 59),
                    min_trade_date="2026-06-11",
                    same_day_register_start=time(6, 0),
                    window_limit=3,
                )
                after_window = load_expected_trade_date_window(
                    connection,
                    calendar_path,
                    evaluated_at=datetime(2026, 6, 17, 6, 1),
                    min_trade_date="2026-06-11",
                    same_day_register_start=time(6, 0),
                    window_limit=3,
                )

        self.assertEqual(
            before_window.expected_trade_dates,
            ("2026-06-12", "2026-06-15", "2026-06-16"),
        )
        self.assertEqual(before_window.max_trade_date, "2026-06-16")
        self.assertEqual(
            after_window.expected_trade_dates,
            ("2026-06-15", "2026-06-16", "2026-06-17"),
        )
        self.assertEqual(after_window.max_trade_date, "2026-06-17")

    def test_expected_date_window_rejects_invalid_window_limit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            calendar_path = Path(temp_dir) / "calendar.parquet"
            _write_calendar_parquet(calendar_path)
            with duckdb.connect(database=":memory:") as connection:
                with self.assertRaises(ValueError):
                    load_expected_trade_date_window(
                        connection,
                        calendar_path,
                        evaluated_at=datetime(2026, 6, 17, 6, 1),
                        window_limit=0,
                    )

    def test_registered_gap_reports_first_missing_and_small_sample(self) -> None:
        status = build_registered_gap_status(
            expected_trade_dates=(
                "2026-06-10",
                "2026-06-11",
                "2026-06-12",
                "2026-06-15",
            ),
            registered_trade_dates=("2026-06-10", "2026-06-15"),
            sample_limit=2,
        )

        self.assertFalse(status.ready)
        self.assertEqual(status.first_missing_registered_date, "2026-06-11")
        self.assertEqual(
            status.missing_registered_dates,
            ("2026-06-11", "2026-06-12"),
        )
        self.assertEqual(status.registered_trade_dates, ("2026-06-10", "2026-06-15"))
        self.assertEqual(
            status.to_cursor_details()["first_missing_registered_date"],
            "2026-06-11",
        )

    def test_date_readiness_rejects_ready_mismatch(self) -> None:
        with self.assertRaises(ValueError):
            ContinuityDateReadiness(
                trade_date="2026-06-15",
                ready=True,
                materialized=False,
                checks_passed=False,
                reason="bad_status",
            )

    def test_batch_readiness_unknown_date_fails_closed(self) -> None:
        batch = ContinuityBatchReadiness(
            expected_trade_dates=("2026-06-15",),
            statuses_by_trade_date={"2026-06-15": _ready_status("2026-06-15")},
            elapsed_ms=3,
        )

        unknown_status = batch.status_for_trade_date("2026-06-16")

        self.assertFalse(unknown_status.ready)
        self.assertFalse(unknown_status.materialized)
        self.assertFalse(unknown_status.checks_passed)
        self.assertEqual(unknown_status.reason, "unknown_trade_date")
        self.assertEqual(
            unknown_status.failed_check_names,
            ("continuity_unknown_trade_date",),
        )

    def test_selector_returns_first_not_ready_in_expected_order(self) -> None:
        batch = ContinuityBatchReadiness(
            expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
            statuses_by_trade_date={
                "2026-06-13": _ready_status("2026-06-13"),
                "2026-06-15": _missing_status("2026-06-15"),
                "2026-06-16": _missing_status("2026-06-16"),
            },
            elapsed_ms=7,
        )

        selection = select_first_not_ready_trade_date(
            expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
            readiness=batch,
        )

        self.assertEqual(selection.selected_trade_date, "2026-06-15")
        self.assertEqual(selection.first_not_ready_trade_date, "2026-06-15")
        self.assertEqual(selection.ready_through_trade_date, "2026-06-13")
        self.assertIsNone(selection.blocked_reason)

    def test_selector_blocks_materialized_check_failure(self) -> None:
        failed_status = ContinuityDateReadiness(
            trade_date="2026-06-15",
            ready=False,
            materialized=True,
            checks_passed=False,
            reason="blocking_checks_failed",
            failed_check_names=("sample_check",),
        )
        batch = ContinuityBatchReadiness(
            expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
            statuses_by_trade_date={
                "2026-06-13": _ready_status("2026-06-13"),
                "2026-06-15": failed_status,
                "2026-06-16": _missing_status("2026-06-16"),
            },
            elapsed_ms=7,
        )

        selection = select_first_not_ready_trade_date(
            expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
            readiness=batch,
        )

        self.assertIsNone(selection.selected_trade_date)
        self.assertEqual(selection.selected_status, failed_status)
        self.assertEqual(selection.first_not_ready_trade_date, "2026-06-15")
        self.assertEqual(selection.blocked_reason, "materialized_check_failed")

    def test_selector_blocks_missing_readiness_status(self) -> None:
        batch = ContinuityBatchReadiness(
            expected_trade_dates=("2026-06-13", "2026-06-15"),
            statuses_by_trade_date={"2026-06-13": _ready_status("2026-06-13")},
            elapsed_ms=7,
        )

        selection = select_first_not_ready_trade_date(
            expected_trade_dates=("2026-06-13", "2026-06-15"),
            readiness=batch,
        )

        self.assertIsNone(selection.selected_trade_date)
        self.assertEqual(selection.first_not_ready_trade_date, "2026-06-15")
        self.assertEqual(selection.blocked_reason, "readiness_status_missing")

    def test_selector_all_ready_sets_ready_frontier(self) -> None:
        batch = ContinuityBatchReadiness(
            expected_trade_dates=("2026-06-13", "2026-06-15"),
            statuses_by_trade_date={
                "2026-06-13": _ready_status("2026-06-13"),
                "2026-06-15": _ready_status("2026-06-15"),
            },
            elapsed_ms=5,
        )

        selection = select_first_not_ready_trade_date(
            expected_trade_dates=("2026-06-13", "2026-06-15"),
            readiness=batch,
        )

        self.assertIsNone(selection.selected_trade_date)
        self.assertEqual(selection.ready_through_trade_date, "2026-06-15")
        self.assertIsNone(selection.first_not_ready_trade_date)
        self.assertIsNone(selection.blocked_reason)

    def test_cursor_details_are_summary_only(self) -> None:
        with TemporaryDirectory() as temp_dir:
            calendar_path = Path(temp_dir) / "calendar.parquet"
            _write_calendar_parquet(calendar_path)
            with duckdb.connect(database=":memory:") as connection:
                window = load_expected_trade_date_window(
                    connection,
                    calendar_path,
                    evaluated_at=datetime(2026, 6, 17, 6, 1),
                    window_limit=3,
                )
        gap_status = build_registered_gap_status(
            expected_trade_dates=window.expected_trade_dates,
            registered_trade_dates=("2026-06-15", "2026-06-16", "2026-06-17"),
        )
        batch = ContinuityBatchReadiness(
            expected_trade_dates=window.expected_trade_dates,
            statuses_by_trade_date={
                trade_date: _ready_status(trade_date)
                for trade_date in window.expected_trade_dates
            },
            elapsed_ms=9,
            scanned_file_count=3,
        )
        selection = select_first_not_ready_trade_date(
            expected_trade_dates=window.expected_trade_dates,
            readiness=batch,
        )

        details = build_continuity_cursor_details(
            expected_window=window,
            gap_status=gap_status,
            batch_readiness=batch,
            selection=selection,
        )

        self.assertEqual(details["expected_count"], 3)
        self.assertEqual(details["registered_count"], 3)
        self.assertEqual(details["batch_elapsed_ms"], 9)
        self.assertEqual(len(details["status_samples"]), 3)
        self.assertNotIn("statuses_by_trade_date", details)
        self.assertLessEqual(
            len(details["status_samples"]),
            DEFAULT_CONTINUITY_SAMPLE_LIMIT,
        )


if __name__ == "__main__":
    unittest.main()
