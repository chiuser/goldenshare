import tempfile
import unittest
from pathlib import Path

import duckdb

from orchestrator.defs.bootstrap.wealth_market_turnover_history import (
    WEALTH_MARKET_TURNOVER_RUNLESS_WINDOW_SIZE,
    audit_wealth_market_turnover_history,
    generate_wealth_market_turnover_history,
    plan_wealth_market_turnover_history,
)
from orchestrator.defs.paths import (
    gold_wealth_market_turnover_path,
    silver_stk_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS


DATE_1 = "2026-06-22"
DATE_2 = "2026-06-23"


class WealthMarketTurnoverHistoryBootstrapTests(unittest.TestCase):
    def test_history_helpers_do_not_define_active_dagster_components(self) -> None:
        helper_paths = (
            Path("src/orchestrator/defs/bootstrap/wealth_market_turnover_history.py"),
            Path(
                "src/orchestrator/defs/bootstrap/"
                "wealth_market_turnover_history_cli.py"
            ),
        )
        for helper_path in helper_paths:
            source = helper_path.read_text()
            for token in ("@dg.asset", "@dg.asset_check", "@dg.sensor", "define_asset_job"):
                self.assertNotIn(token, source)

    def test_plan_uses_only_complete_five_freq_silver_partitions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            lake_root = Path(temporary_dir)
            _write_all_silver_files(lake_root, DATE_1)
            for freq in STK_MINS_FREQS[:-1]:
                _write_silver_file(lake_root, DATE_2, freq)

            plan = plan_wealth_market_turnover_history(lake_root=lake_root)

        self.assertEqual(plan.selected_partition_keys, (DATE_1,))
        self.assertEqual(plan.complete_silver_partition_count, 1)
        self.assertEqual(plan.planned_write_count, 1)
        self.assertEqual(plan.planned_event_count, 2)
        self.assertEqual(plan.missing_input_count, 0)

    def test_history_plan_caps_runless_event_count_to_recent_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            lake_root = Path(temporary_dir)
            for day in range(1, WEALTH_MARKET_TURNOVER_RUNLESS_WINDOW_SIZE + 2):
                partition_key = f"2026-05-{day:02d}"
                for freq in STK_MINS_FREQS:
                    path = silver_stk_mins_path(lake_root, freq, partition_key)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()

            plan = plan_wealth_market_turnover_history(lake_root=lake_root)

        self.assertEqual(
            len(plan.selected_partition_keys),
            WEALTH_MARKET_TURNOVER_RUNLESS_WINDOW_SIZE + 1,
        )
        self.assertEqual(
            plan.planned_event_count,
            WEALTH_MARKET_TURNOVER_RUNLESS_WINDOW_SIZE * 2,
        )

    def test_requested_incomplete_partition_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            lake_root = Path(temporary_dir)
            _write_all_silver_files(lake_root, DATE_1)
            for freq in STK_MINS_FREQS[:-1]:
                _write_silver_file(lake_root, DATE_2, freq)

            with self.assertRaisesRegex(ValueError, "missing complete silver inputs"):
                plan_wealth_market_turnover_history(
                    lake_root=lake_root,
                    partition_keys=(DATE_1, DATE_2),
                )

    def test_generate_and_audit_history_partition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            lake_root = Path(temporary_dir)
            _write_all_silver_files(lake_root, DATE_1)

            write_report = generate_wealth_market_turnover_history(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(DATE_1,),
            )
            audit_report = audit_wealth_market_turnover_history(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(DATE_1,),
            )
            target_exists = gold_wealth_market_turnover_path(lake_root, DATE_1).exists()

        self.assertTrue(target_exists)
        self.assertEqual(write_report.written_partition_keys, (DATE_1,))
        self.assertEqual(write_report.write_results[0].row_count, 5)
        self.assertEqual(audit_report.failed_partition_count, 0)
        self.assertEqual(audit_report.target_file_count, 1)
        self.assertEqual(audit_report.target_row_count, 5)
        self.assertEqual(audit_report.target_date_min, DATE_1)
        self.assertEqual(audit_report.target_date_max, DATE_1)


def _write_all_silver_files(root: Path, partition_key: str) -> None:
    for freq in STK_MINS_FREQS:
        _write_silver_file(root, partition_key, freq)


def _write_silver_file(root: Path, partition_key: str, freq: int) -> None:
    path = silver_stk_mins_path(root, freq, partition_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(
        "(" + ", ".join(_sql_literal(value) for value in row) + ")"
        for row in (
            ("000001.SZ", freq, f"{partition_key} 09:30:00", 100, 1000.0),
            ("000002.SZ", freq, f"{partition_key} 09:30:00", 300, 3000.0),
            ("000001.SZ", freq, f"{partition_key} 09:31:00", 200, 2000.0),
            ("000002.SZ", freq, f"{partition_key} 09:31:00", 400, 4000.0),
        )
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                CAST(ts_code AS VARCHAR) AS ts_code,
                CAST(freq AS INTEGER) AS freq,
                DATE '{partition_key}' AS trade_date,
                CAST(trade_time AS TIMESTAMP) AS trade_time,
                CAST(vol AS DOUBLE) AS vol,
                CAST(amount AS DOUBLE) AS amount
              FROM (
                VALUES {values_sql}
              ) AS rows(ts_code, freq, trade_time, vol, amount)
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )


def _sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)


if __name__ == "__main__":
    unittest.main()
