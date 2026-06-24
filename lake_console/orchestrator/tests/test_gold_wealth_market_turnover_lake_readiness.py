import tempfile
import unittest
from pathlib import Path

import duckdb

from orchestrator.defs.asset_guards.wealth_market_turnover_lake_readiness import (
    batch_gold_wealth_market_turnover_lake_readiness,
)
from orchestrator.defs.paths import (
    gold_wealth_market_turnover_path,
    silver_stk_mins_path,
)
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_CONTINUITY_WINDOW_LIMIT,
    STK_MINS_FREQS,
)
from orchestrator.defs.wealth_market_turnover_contract import (
    wealth_market_turnover_input_paths,
    write_gold_wealth_market_turnover_partition,
)


class GoldWealthMarketTurnoverLakeReadinessTests(unittest.TestCase):
    def test_batch_readiness_reports_ready_for_valid_partition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self._write_all_silver_files(root, "2026-06-22")
            with duckdb.connect(database=":memory:") as connection:
                write_gold_wealth_market_turnover_partition(
                    connection=connection,
                    input_paths=wealth_market_turnover_input_paths(root, "2026-06-22"),
                    partition_key="2026-06-22",
                    target_path=gold_wealth_market_turnover_path(root, "2026-06-22"),
                    built_at_sql="TIMESTAMP '2026-06-22 20:00:00'",
                )
                readiness = batch_gold_wealth_market_turnover_lake_readiness(
                    connection=connection,
                    lake_root=root,
                    expected_trade_dates=("2026-06-22",),
                )

            status = readiness.status_for_trade_date("2026-06-22")
            self.assertTrue(status.ready)
            self.assertTrue(status.materialized)
            self.assertTrue(status.checks_passed)
            self.assertEqual(status.reason, "ready")

    def test_batch_readiness_reports_missing_gold_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            with duckdb.connect(database=":memory:") as connection:
                readiness = batch_gold_wealth_market_turnover_lake_readiness(
                    connection=connection,
                    lake_root=root,
                    expected_trade_dates=("2026-06-22",),
                )

            status = readiness.status_for_trade_date("2026-06-22")
            self.assertFalse(status.ready)
            self.assertFalse(status.materialized)
            self.assertEqual(status.reason, "missing_file")
            self.assertIn("gold_wealth_market_turnover_integrity_check", status.failed_check_names)

    def test_batch_readiness_rejects_window_larger_than_hotpath_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            dates = tuple(
                f"2026-06-{day:02d}"
                for day in range(1, STK_MINS_CONTINUITY_WINDOW_LIMIT + 2)
            )
            with duckdb.connect(database=":memory:") as connection:
                with self.assertRaisesRegex(ValueError, "window exceeds"):
                    batch_gold_wealth_market_turnover_lake_readiness(
                        connection=connection,
                        lake_root=root,
                        expected_trade_dates=dates,
                    )

    def _write_all_silver_files(self, root: Path, partition_key: str) -> None:
        for freq in STK_MINS_FREQS:
            self._write_silver_file(root, partition_key, freq)

    def _write_silver_file(self, root: Path, partition_key: str, freq: int) -> None:
        path = silver_stk_mins_path(root, freq, partition_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        values_sql = ", ".join(
            "(" + ", ".join(self._sql_literal(value) for value in row) + ")"
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

    @staticmethod
    def _sql_literal(value: object) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, str):
            return "'" + value.replace("'", "''") + "'"
        return str(value)
