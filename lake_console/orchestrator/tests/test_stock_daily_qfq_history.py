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
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    silver_adj_factor_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_TRADE_CALENDAR_SCHEMA,
)
from orchestrator.defs.resources import DuckDBResource
from tests.test_stock_daily_qfq_contracts import (
    EARLIER_DATE,
    PREVIOUS_DATE,
    TRADE_DATE,
    _adj_factor_row,
    _column_types,
    _fetch_output_rows,
    _stock_daily_row,
    _write_adj_factor,
    _write_calendar,
    _write_rows,
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
                as_of_trade_date=TRADE_DATE,
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
                as_of_trade_date=TRADE_DATE,
            )
            target_rows = _fetch_output_rows(gold_stock_daily_qfq_path(root, TRADE_DATE))

        self.assertEqual(report.written_partition_keys, (TRADE_DATE,))
        self.assertEqual(report.skipped_existing_partition_keys, ())
        self.assertEqual(report.write_results[0].output_row_count, 1)
        self.assertEqual(target_rows[0]["ts_code"], "000001.SZ")

    def test_history_bootstrap_uses_latest_effective_as_of_factor_for_delisted_stock(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_calendar(root)
            _write_stock_daily(
                root,
                EARLIER_DATE,
                [_stock_daily_row("000638.SZ", EARLIER_DATE, close=5.0)],
            )
            _write_adj_factor(
                root,
                EARLIER_DATE,
                [_adj_factor_row("000638.SZ", EARLIER_DATE, 2.0)],
            )
            _write_adj_factor(
                root,
                PREVIOUS_DATE,
                [_adj_factor_row("000638.SZ", PREVIOUS_DATE, 4.0)],
            )
            _write_adj_factor(
                root,
                TRADE_DATE,
                [_adj_factor_row("000001.SZ", TRADE_DATE, 1.0)],
            )

            report = generate_gold_stock_daily_qfq_history(
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(EARLIER_DATE,),
                as_of_trade_date=TRADE_DATE,
            )
            target_rows = _fetch_output_rows(
                gold_stock_daily_qfq_path(root, EARLIER_DATE)
            )

        self.assertEqual(report.written_partition_keys, (EARLIER_DATE,))
        self.assertEqual(report.write_results[0].output_row_count, 1)
        self.assertEqual(target_rows[0]["ts_code"], "000638.SZ")
        self.assertAlmostEqual(target_rows[0]["close"], 2.5)

    def test_history_generation_skips_existing_when_requested(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_history_lake(root)

            first_report = generate_gold_stock_daily_qfq_history(
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(TRADE_DATE,),
                as_of_trade_date=TRADE_DATE,
            )
            second_report = generate_gold_stock_daily_qfq_history(
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(TRADE_DATE,),
                as_of_trade_date=TRADE_DATE,
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
                    "--as-of-trade-date",
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
                    "--as-of-trade-date",
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
                    "--as-of-trade-date",
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
                    "--as-of-trade-date",
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

    def test_history_bootstrap_records_explicit_as_of_trade_date(self) -> None:
        source_date = "2025-06-17"
        as_of_date = "2026-06-26"
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_rows(
                silver_trade_calendar_path(root),
                column_types=_column_types(SILVER_TRADE_CALENDAR_SCHEMA),
                rows=[
                    {
                        "exchange": "SSE",
                        "trade_date": source_date,
                        "is_open": True,
                        "pretrade_date": "2025-06-16",
                    },
                    {
                        "exchange": "SSE",
                        "trade_date": as_of_date,
                        "is_open": True,
                        "pretrade_date": "2026-06-25",
                    },
                ],
                order_by="exchange, trade_date",
            )
            _write_stock_daily(
                root,
                source_date,
                [_stock_daily_row("000001.SZ", source_date, close=10.0)],
            )
            _write_adj_factor(
                root,
                source_date,
                [_adj_factor_row("000001.SZ", source_date, 2.0)],
            )
            _write_adj_factor(
                root,
                as_of_date,
                [_adj_factor_row("000001.SZ", as_of_date, 3.0)],
            )

            report = generate_gold_stock_daily_qfq_history(
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(source_date,),
                as_of_trade_date=as_of_date,
            )

        self.assertEqual(report.bootstrap_as_of_trade_date, as_of_date)
        self.assertEqual(
            report.as_of_adj_factor_file_path,
            str(silver_adj_factor_path(root, as_of_date)),
        )
        self.assertIn(
            "effective_as_of_adj_factor_2026-06-26.parquet",
            str(report.write_results[0].as_of_adj_factor_file_path),
        )

    def test_history_cli_requires_as_of_trade_date(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "lake"
            report_dir = Path(temp_dir) / "reports"
            _prepare_history_lake(root)

            with self.assertRaises(SystemExit):
                history_cli_main(
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


if __name__ == "__main__":
    unittest.main()
