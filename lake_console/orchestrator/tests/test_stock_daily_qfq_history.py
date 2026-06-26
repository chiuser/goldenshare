import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.defs.bootstrap.gold_stock_daily_qfq_history import (
    generate_gold_stock_daily_qfq_history,
    plan_gold_stock_daily_qfq_history,
)
from orchestrator.defs.bootstrap.gold_stock_daily_qfq_history_cli import (
    main as history_cli_main,
)
from orchestrator.defs.paths import gold_stock_daily_qfq_path
from orchestrator.defs.resources import DuckDBResource
from tests.test_stock_daily_qfq_contracts import (
    EARLIER_DATE,
    PREVIOUS_DATE,
    TRADE_DATE,
    _adj_factor_row,
    _fetch_output_rows,
    _stock_daily_row,
    _write_adj_factor,
    _write_calendar,
    _write_stock_daily,
)


def _prepare_history_lake(root: Path) -> None:
    _write_calendar(root)
    for trade_date, close in (
        (EARLIER_DATE, 8.0),
        (PREVIOUS_DATE, 10.0),
        (TRADE_DATE, 12.0),
    ):
        _write_stock_daily(
            root,
            trade_date,
            [_stock_daily_row("000001.SZ", trade_date, close=close)],
        )
        _write_adj_factor(
            root,
            trade_date,
            [_adj_factor_row("000001.SZ", trade_date, 2.0)],
        )


class StockDailyQfqHistoryTests(unittest.TestCase):
    def test_history_plan_uses_complete_silver_inputs_and_does_not_write(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_history_lake(root)

            plan = plan_gold_stock_daily_qfq_history(
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                start_date=EARLIER_DATE,
                end_date=TRADE_DATE,
            )

        self.assertEqual(
            plan.selected_partition_keys,
            (EARLIER_DATE, PREVIOUS_DATE, TRADE_DATE),
        )
        self.assertEqual(plan.planned_write_count, 3)
        self.assertEqual(plan.missing_input_count, 0)

    def test_history_sample_generates_requested_partition(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_history_lake(root)

            report = generate_gold_stock_daily_qfq_history(
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(TRADE_DATE,),
            )
            target_rows = _fetch_output_rows(gold_stock_daily_qfq_path(root, TRADE_DATE))

        self.assertEqual(report.written_partition_keys, (TRADE_DATE,))
        self.assertEqual(report.skipped_existing_partition_keys, ())
        self.assertEqual(report.write_results[0].output_row_count, 1)
        self.assertEqual(target_rows[0]["ts_code"], "000001.SZ")

    def test_history_generation_skips_existing_when_requested(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_history_lake(root)

            first_report = generate_gold_stock_daily_qfq_history(
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(TRADE_DATE,),
            )
            second_report = generate_gold_stock_daily_qfq_history(
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(TRADE_DATE,),
            )

        self.assertEqual(first_report.written_partition_keys, (TRADE_DATE,))
        self.assertEqual(second_report.written_partition_keys, ())
        self.assertEqual(second_report.skipped_existing_partition_keys, (TRADE_DATE,))

    def test_history_cli_profile_writes_json_report_without_target_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "lake"
            report_dir = Path(temp_dir) / "reports"
            _prepare_history_lake(root)

            output_path = history_cli_main(
                [
                    "profile-history",
                    "--lake-root",
                    str(root),
                    "--start-date",
                    EARLIER_DATE,
                    "--end-date",
                    TRADE_DATE,
                    "--report-dir",
                    str(report_dir),
                ]
            )
            payload = json.loads(output_path.read_text())
            target_file_exists = gold_stock_daily_qfq_path(root, TRADE_DATE).exists()

        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["plan"]["planned_write_count"], 3)
        self.assertFalse(target_file_exists)

    def test_history_cli_write_sample_requires_apply_to_write(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "lake"
            report_dir = Path(temp_dir) / "reports"
            _prepare_history_lake(root)

            dry_run_output = history_cli_main(
                [
                    "write-sample",
                    "--lake-root",
                    str(root),
                    "--partition-keys",
                    TRADE_DATE,
                    "--report-dir",
                    str(report_dir),
                ]
            )
            dry_run_payload = json.loads(dry_run_output.read_text())
            apply_output = history_cli_main(
                [
                    "write-sample",
                    "--lake-root",
                    str(root),
                    "--partition-keys",
                    TRADE_DATE,
                    "--report-dir",
                    str(report_dir),
                    "--apply",
                ]
            )
            apply_payload = json.loads(apply_output.read_text())

        self.assertTrue(dry_run_payload["dry_run"])
        self.assertFalse(dry_run_payload.get("write_report"))
        self.assertFalse(apply_payload["dry_run"])
        self.assertEqual(
            apply_payload["write_report"]["written_partition_keys"],
            [TRADE_DATE],
        )

    def test_history_cli_build_history_defaults_to_dry_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "lake"
            report_dir = Path(temp_dir) / "reports"
            _prepare_history_lake(root)

            output_path = history_cli_main(
                [
                    "build-history",
                    "--lake-root",
                    str(root),
                    "--start-date",
                    EARLIER_DATE,
                    "--end-date",
                    TRADE_DATE,
                    "--report-dir",
                    str(report_dir),
                ]
            )
            payload = json.loads(output_path.read_text())
            target_file_exists = gold_stock_daily_qfq_path(root, TRADE_DATE).exists()

        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["would_write_count"], 3)
        self.assertFalse(target_file_exists)


if __name__ == "__main__":
    unittest.main()
