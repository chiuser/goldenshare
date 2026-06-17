from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import dagster as dg
import duckdb

from orchestrator.defs.asset_guards.stk_mins_continuity import (
    assert_exact_previous_state_path,
    assert_expected_dates_registered,
    build_registered_gap_status,
    expected_trade_dates_between,
    load_stock_mins_expected_trade_dates,
    previous_expected_trade_date,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import gold_stk_mins_qfq_macd_kdj_state_path


@dataclass(frozen=True)
class _ReadinessStatus:
    ready: bool
    reason: str
    materialized: bool = False
    checks_passed: bool = False


def _has_materialized_check_problem(status: _ReadinessStatus) -> bool:
    return status.materialized and not status.checks_passed


def _write_calendar_parquet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (
                VALUES
                  ('SSE', true, DATE '2026-06-12'),
                  ('SSE', true, DATE '2026-06-13'),
                  ('SSE', false, DATE '2026-06-14'),
                  ('SSE', true, DATE '2026-06-15'),
                  ('SZSE', true, DATE '2026-06-15'),
                  ('SSE', true, DATE '2026-06-16'),
                  ('SSE', true, DATE '2026-06-17')
              ) AS calendar(exchange, is_open, trade_date)
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )


class StockMinsContinuityTests(unittest.TestCase):
    def test_expected_trade_dates_respect_history_start_and_same_day_window(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            calendar_path = Path(temp_dir) / "trade_calendar.parquet"
            _write_calendar_parquet(calendar_path)

            with duckdb.connect(database=":memory:") as connection:
                before_window = load_stock_mins_expected_trade_dates(
                    connection,
                    calendar_path,
                    min_trade_date="2026-06-13",
                    evaluated_at=datetime(2026, 6, 17, 17, 59),
                    same_day_register_start=time(18, 0),
                )
                after_window = load_stock_mins_expected_trade_dates(
                    connection,
                    calendar_path,
                    min_trade_date="2026-06-13",
                    evaluated_at=datetime(2026, 6, 17, 18, 1),
                    same_day_register_start=time(18, 0),
                )

        self.assertEqual(
            before_window,
            ("2026-06-13", "2026-06-15", "2026-06-16"),
        )
        self.assertEqual(
            after_window,
            ("2026-06-13", "2026-06-15", "2026-06-16", "2026-06-17"),
        )

    def test_registered_gap_status_reports_first_missing_registered_date(
        self,
    ) -> None:
        status = build_registered_gap_status(
            partition_set_name="cn_a_stock_mins_silver_trade_days",
            expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
            registered_trade_days=("2026-06-13", "2026-06-16"),
            target_trade_date="2026-06-16",
        )

        self.assertEqual(status.first_missing_registered_date, "2026-06-15")
        self.assertEqual(status.missing_registered_date_samples, ("2026-06-15",))
        self.assertEqual(status.previous_expected_trade_date, "2026-06-15")
        self.assertEqual(status.ready_through_trade_date, "2026-06-13")
        self.assertEqual(status.next_actionable_trade_date, "2026-06-15")
        self.assertTrue(status.blocked)
        self.assertEqual(
            status.to_cursor_details()["first_missing_registered_date"],
            "2026-06-15",
        )

    def test_previous_expected_trade_date_ignores_registered_partitions(self) -> None:
        previous_trade_date = previous_expected_trade_date(
            ("2026-06-13", "2026-06-15", "2026-06-16"),
            "2026-06-16",
        )

        self.assertEqual(previous_trade_date, "2026-06-15")

    def test_expected_trade_dates_between_returns_calendar_closed_range(self) -> None:
        trade_dates = expected_trade_dates_between(
            ("2026-06-13", "2026-06-15", "2026-06-16"),
            start_trade_date="2026-06-14",
            end_trade_date="2026-06-16",
        )

        self.assertEqual(trade_dates, ("2026-06-15", "2026-06-16"))

    def test_selector_stops_at_missing_registered_date_before_readiness_scan(
        self,
    ) -> None:
        calls: list[str] = []

        def readiness_for_trade_date(trade_date: str) -> _ReadinessStatus:
            calls.append(trade_date)
            return _ReadinessStatus(ready=True, reason="ready")

        selection = select_first_not_ready_trade_date(
            partition_set_name="cn_a_stock_mins_silver_trade_days",
            expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
            registered_trade_days=("2026-06-13", "2026-06-16"),
            readiness_for_trade_date=readiness_for_trade_date,
            has_materialized_check_problem=_has_materialized_check_problem,
        )

        self.assertIsNone(selection.selected_trade_date)
        self.assertIsNone(selection.selected_status)
        self.assertEqual(calls, [])
        self.assertEqual(
            selection.status.first_missing_registered_date,
            "2026-06-15",
        )
        self.assertIsNone(selection.status.ready_through_trade_date)
        self.assertEqual(selection.status.previous_expected_trade_date, "2026-06-13")
        self.assertEqual(
            selection.status.blocked_reason,
            "missing_registered_partition",
        )

    def test_selector_returns_first_not_ready_trade_date_in_order(self) -> None:
        calls: list[str] = []
        statuses = {
            "2026-06-13": _ReadinessStatus(ready=True, reason="ready"),
            "2026-06-15": _ReadinessStatus(ready=False, reason="missing materialization"),
            "2026-06-16": _ReadinessStatus(ready=False, reason="should not be called"),
        }

        def readiness_for_trade_date(trade_date: str) -> _ReadinessStatus:
            calls.append(trade_date)
            return statuses[trade_date]

        selection = select_first_not_ready_trade_date(
            partition_set_name="cn_a_stock_mins_silver_trade_days",
            expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
            registered_trade_days=("2026-06-13", "2026-06-15", "2026-06-16"),
            readiness_for_trade_date=readiness_for_trade_date,
            has_materialized_check_problem=_has_materialized_check_problem,
        )

        self.assertEqual(calls, ["2026-06-13", "2026-06-15"])
        self.assertEqual(selection.selected_trade_date, "2026-06-15")
        self.assertEqual(selection.selected_status, statuses["2026-06-15"])
        self.assertEqual(selection.status.first_not_ready_trade_date, "2026-06-15")
        self.assertEqual(selection.status.previous_expected_trade_date, "2026-06-13")
        self.assertEqual(selection.status.ready_through_trade_date, "2026-06-13")
        self.assertEqual(selection.status.next_actionable_trade_date, "2026-06-15")

    def test_selector_blocks_materialized_check_problem_without_later_date(
        self,
    ) -> None:
        calls: list[str] = []
        statuses = {
            "2026-06-13": _ReadinessStatus(ready=True, reason="ready"),
            "2026-06-15": _ReadinessStatus(
                ready=False,
                reason="blocking checks failed",
                materialized=True,
                checks_passed=False,
            ),
            "2026-06-16": _ReadinessStatus(ready=False, reason="should not be called"),
        }

        def readiness_for_trade_date(trade_date: str) -> _ReadinessStatus:
            calls.append(trade_date)
            return statuses[trade_date]

        selection = select_first_not_ready_trade_date(
            partition_set_name="cn_a_stock_mins_silver_trade_days",
            expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
            registered_trade_days=("2026-06-13", "2026-06-15", "2026-06-16"),
            readiness_for_trade_date=readiness_for_trade_date,
            has_materialized_check_problem=_has_materialized_check_problem,
        )

        self.assertEqual(calls, ["2026-06-13", "2026-06-15"])
        self.assertIsNone(selection.selected_trade_date)
        self.assertEqual(selection.status.first_not_ready_trade_date, "2026-06-15")
        self.assertEqual(selection.status.blocked_reason, "materialized_check_problem")
        self.assertIsNone(selection.status.next_actionable_trade_date)

    def test_selector_all_ready_sets_ready_frontier(self) -> None:
        selection = select_first_not_ready_trade_date(
            partition_set_name="cn_a_stock_mins_silver_trade_days",
            expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
            registered_trade_days=("2026-06-13", "2026-06-15", "2026-06-16"),
            readiness_for_trade_date=lambda _trade_date: _ReadinessStatus(
                ready=True,
                reason="ready",
            ),
            has_materialized_check_problem=_has_materialized_check_problem,
        )

        self.assertIsNone(selection.selected_trade_date)
        self.assertEqual(selection.status.ready_count, 3)
        self.assertEqual(selection.status.ready_through_trade_date, "2026-06-16")
        self.assertIsNone(selection.status.blocked_reason)

    def test_assert_expected_dates_registered_fails_with_missing_metadata(
        self,
    ) -> None:
        with self.assertRaises(dg.Failure) as failure:
            assert_expected_dates_registered(
                expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
                registered_trade_days=("2026-06-13", "2026-06-16"),
                partition_set_name="cn_a_stock_mins_silver_trade_days",
                start_trade_date="2026-06-13",
                end_trade_date="2026-06-16",
            )

        self.assertIn(
            "first_missing_registered_date=2026-06-15",
            failure.exception.description,
        )
        self.assertIn("first_missing_registered_date", failure.exception.metadata)
        self.assertIn("missing_registered_date_samples", failure.exception.metadata)

    def test_assert_expected_dates_registered_returns_expected_range(self) -> None:
        trade_dates = assert_expected_dates_registered(
            expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
            registered_trade_days=("2026-06-13", "2026-06-15", "2026-06-16"),
            partition_set_name="cn_a_stock_mins_silver_trade_days",
            start_trade_date="2026-06-15",
            end_trade_date="2026-06-16",
        )

        self.assertEqual(trade_dates, ("2026-06-15", "2026-06-16"))

    def test_assert_exact_previous_state_path_returns_existing_state(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            previous_state_path = gold_stk_mins_qfq_macd_kdj_state_path(
                lake_root,
                1,
                "2026-06-15",
            )
            previous_state_path.parent.mkdir(parents=True, exist_ok=True)
            previous_state_path.touch()

            resolved_path = assert_exact_previous_state_path(
                lake_root=lake_root,
                freq=1,
                target_trade_date="2026-06-16",
                previous_expected_trade_date="2026-06-15",
                allow_without_previous_state=False,
            )

        self.assertEqual(resolved_path, previous_state_path)

    def test_assert_exact_previous_state_path_fails_when_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with self.assertRaises(dg.Failure) as failure:
                assert_exact_previous_state_path(
                    lake_root=Path(temp_dir),
                    freq=1,
                    target_trade_date="2026-06-16",
                    previous_expected_trade_date="2026-06-15",
                    allow_without_previous_state=False,
                )

        self.assertIn(
            "previous expected state is missing",
            failure.exception.description,
        )

    def test_assert_exact_previous_state_path_allows_baseline_without_previous(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            resolved_path = assert_exact_previous_state_path(
                lake_root=Path(temp_dir),
                freq=1,
                target_trade_date="2014-01-02",
                previous_expected_trade_date=None,
                allow_without_previous_state=True,
            )

        self.assertIsNone(resolved_path)


if __name__ == "__main__":
    unittest.main()
