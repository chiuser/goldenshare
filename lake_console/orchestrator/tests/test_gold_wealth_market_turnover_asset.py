import tempfile
import unittest
from pathlib import Path

import duckdb

from orchestrator.defs.paths import (
    gold_wealth_market_turnover_path,
    gold_wealth_market_turnover_staging_path,
    silver_stk_mins_path,
    silver_stock_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS
from orchestrator.defs.wealth_market_turnover_contract import (
    GOLD_WEALTH_MARKET_TURNOVER_COLUMNS,
    _normalise_decimal,
    audit_gold_wealth_market_turnover_file_contract,
    wealth_market_turnover_source_paths,
    write_gold_wealth_market_turnover_partition,
)


class GoldWealthMarketTurnoverAssetTests(unittest.TestCase):
    def test_gold_wealth_market_turnover_path_contract(self) -> None:
        self.assertEqual(
            gold_wealth_market_turnover_path(Path("/lake"), "2026-06-22"),
            Path("/lake/gold/wealth/market_turnover/trade_date=2026-06-22/part-000.parquet"),
        )
        self.assertEqual(
            gold_wealth_market_turnover_staging_path(
                Path("/lake-staging"),
                operation_id="run-123",
                partition_key="2026-06-22",
            ),
            Path(
                "/lake-staging/wealth_market_turnover/operation_id=run-123/"
                "trade_date=2026-06-22/part-000.parquet"
            ),
        )

    def test_decimal_compare_normalization_ignores_insignificant_scale(self) -> None:
        self.assertEqual(_normalise_decimal("5803875.0"), "5803875")
        self.assertEqual(_normalise_decimal("5803875.00"), "5803875")
        self.assertEqual(_normalise_decimal("0.0100"), "0.01")

    def test_write_partition_outputs_five_ready_json_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self._write_all_silver_files(root, "2026-06-22")
            target_path = gold_wealth_market_turnover_path(root, "2026-06-22")

            with duckdb.connect(database=":memory:") as connection:
                audit = write_gold_wealth_market_turnover_partition(
                    duckdb_resource=DuckDBResource(),
                    source_paths=wealth_market_turnover_source_paths(root, "2026-06-22"),
                    partition_key="2026-06-22",
                    staging_path=root / "staging/part-000.parquet",
                    target_path=target_path,
                    built_at_sql="TIMESTAMP '2026-06-22 20:00:00'",
                )
                file_audit = audit_gold_wealth_market_turnover_file_contract(
                    connection=connection,
                    target_path=target_path,
                    partition_key="2026-06-22",
                )
                rows = connection.execute(
                    f"""
                    SELECT
                      type,
                      market,
                      CAST(trade_date AS VARCHAR),
                      freq,
                      build_status,
                      CAST(total_amount AS VARCHAR),
                      total_vol,
                      security_count,
                      source_row_count,
                      CAST(points_json AS VARCHAR)
                    FROM read_parquet('{target_path.as_posix()}', hive_partitioning=false)
                    ORDER BY freq
                    """
                ).fetchall()
                describe_rows = connection.execute(
                    f"DESCRIBE SELECT * FROM read_parquet('{target_path.as_posix()}', hive_partitioning=false)"
                ).fetchall()

            self.assertTrue(target_path.exists())
            self.assertEqual(audit.row_count, 5)
            self.assertEqual(audit.observed_columns, GOLD_WEALTH_MARKET_TURNOVER_COLUMNS)
            self.assertEqual(audit.source_row_count, 20)
            self.assertTrue(file_audit.passed)
            self.assertEqual(len(rows), 5)
            self.assertEqual(rows[0][:9], ("stock", "CN_A", "2026-06-22", 1, "READY", "13.00", 1300, 2, 4))
            self.assertIn('"tradeTime":"09:30"', rows[0][9])
            self.assertIn('"amount":2.01', rows[0][9])
            self.assertEqual(audit.bse_residual_vol_by_freq["1"], 899)
            self.assertEqual(audit.bse_residual_vol_by_freq["60"], 840)
            self.assertEqual(audit.bse_residual_amount_by_freq["1"], "8990")
            self.assertEqual(
                [row[1].upper() for row in describe_rows if row[0] == "points_json"],
                ["JSON"],
            )

    def test_write_partition_fails_closed_for_missing_freq(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            for freq in STK_MINS_FREQS[:-1]:
                self._write_silver_file(root, "2026-06-22", freq)

            with self.assertRaisesRegex(FileNotFoundError, "Missing silver stk_mins"):
                write_gold_wealth_market_turnover_partition(
                    duckdb_resource=DuckDBResource(),
                    source_paths=wealth_market_turnover_source_paths(root, "2026-06-22"),
                    partition_key="2026-06-22",
                    staging_path=root / "staging/part-000.parquet",
                    target_path=gold_wealth_market_turnover_path(root, "2026-06-22"),
                )

            self.assertFalse(gold_wealth_market_turnover_path(root, "2026-06-22").exists())

    def test_write_partition_fails_closed_for_duplicate_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self._write_all_silver_files(root, "2026-06-22")
            self._write_silver_file(
                root,
                "2026-06-22",
                1,
                duplicate_first_row=True,
            )

            with self.assertRaisesRegex(RuntimeError, "duplicate_key_count=1"):
                write_gold_wealth_market_turnover_partition(
                    duckdb_resource=DuckDBResource(),
                    source_paths=wealth_market_turnover_source_paths(root, "2026-06-22"),
                    partition_key="2026-06-22",
                    staging_path=root / "staging/part-000.parquet",
                    target_path=gold_wealth_market_turnover_path(root, "2026-06-22"),
                )

            self.assertFalse(gold_wealth_market_turnover_path(root, "2026-06-22").exists())

    def test_write_partition_fails_closed_for_missing_stock_daily(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            for freq in STK_MINS_FREQS:
                self._write_silver_file(root, "2026-06-22", freq)

            with self.assertRaisesRegex(
                FileNotFoundError,
                "missing_stock_daily_source",
            ):
                write_gold_wealth_market_turnover_partition(
                    duckdb_resource=DuckDBResource(),
                    source_paths=wealth_market_turnover_source_paths(
                        root,
                        "2026-06-22",
                    ),
                    partition_key="2026-06-22",
                    staging_path=root / "staging/part-000.parquet",
                    target_path=gold_wealth_market_turnover_path(
                        root,
                        "2026-06-22",
                    ),
                )

    def test_write_partition_rejects_invalid_stock_daily_contracts(self) -> None:
        cases = (
            (
                "wrong_date",
                {"trade_date": "2026-06-21"},
                "stock_daily_partition_mismatch",
            ),
            (
                "empty",
                {"empty": True},
                "stock_daily_empty",
            ),
            (
                "duplicate_key",
                {"duplicate_bse": True},
                "stock_daily_duplicate_key",
            ),
            (
                "code_set_mismatch",
                {"extra_bse": True},
                "bse_code_set_mismatch",
            ),
            (
                "negative_volume_residual",
                {"bse_vol": 0.5},
                "negative_bse_volume_residual",
            ),
            (
                "nonpositive_amount_residual",
                {"bse_amount": 1.0},
                "nonpositive_bse_amount_residual",
            ),
        )
        for case_name, daily_options, expected_reason in cases:
            with (
                self.subTest(case_name=case_name),
                tempfile.TemporaryDirectory() as temporary_dir,
            ):
                root = Path(temporary_dir)
                for freq in STK_MINS_FREQS:
                    self._write_silver_file(root, "2026-06-22", freq)
                self._write_stock_daily_file(
                    root,
                    "2026-06-22",
                    **daily_options,
                )

                with self.assertRaisesRegex(RuntimeError, expected_reason):
                    write_gold_wealth_market_turnover_partition(
                        duckdb_resource=DuckDBResource(),
                        source_paths=wealth_market_turnover_source_paths(
                            root,
                            "2026-06-22",
                        ),
                        partition_key="2026-06-22",
                        staging_path=root / "staging/part-000.parquet",
                        target_path=gold_wealth_market_turnover_path(
                            root,
                            "2026-06-22",
                        ),
                    )

    def test_write_partition_rejects_missing_bse_close_point(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self._write_all_silver_files(root, "2026-06-22")
            self._write_silver_file(
                root,
                "2026-06-22",
                1,
                omit_bse_close=True,
            )

            with self.assertRaisesRegex(RuntimeError, "bse_close_point_missing"):
                write_gold_wealth_market_turnover_partition(
                    duckdb_resource=DuckDBResource(),
                    source_paths=wealth_market_turnover_source_paths(
                        root,
                        "2026-06-22",
                    ),
                    partition_key="2026-06-22",
                    staging_path=root / "staging/part-000.parquet",
                    target_path=gold_wealth_market_turnover_path(
                        root,
                        "2026-06-22",
                    ),
                )

    def test_write_partition_keeps_existing_file_when_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self._write_all_silver_files(root, "2026-06-22")
            target_path = gold_wealth_market_turnover_path(root, "2026-06-22")

            with duckdb.connect(database=":memory:") as connection:
                write_gold_wealth_market_turnover_partition(
                    duckdb_resource=DuckDBResource(),
                    source_paths=wealth_market_turnover_source_paths(root, "2026-06-22"),
                    partition_key="2026-06-22",
                    staging_path=root / "staging/part-000.parquet",
                    target_path=target_path,
                    built_at_sql="TIMESTAMP '2026-06-22 20:00:00'",
                )
                stale_total = connection.execute(
                    f"SELECT sum(total_vol) FROM read_parquet('{target_path.as_posix()}', hive_partitioning=false)"
                ).fetchone()[0]

            self._write_silver_file(root, "2026-06-22", 1, trade_date="2026-06-21")
            with duckdb.connect(database=":memory:") as connection:
                with self.assertRaisesRegex(RuntimeError, "invalid key/date/freq"):
                    write_gold_wealth_market_turnover_partition(
                        duckdb_resource=DuckDBResource(),
                        source_paths=wealth_market_turnover_source_paths(root, "2026-06-22"),
                        partition_key="2026-06-22",
                        staging_path=root / "staging/retry.parquet",
                        target_path=target_path,
                    )
                current_total = connection.execute(
                    f"SELECT sum(total_vol) FROM read_parquet('{target_path.as_posix()}', hive_partitioning=false)"
                ).fetchone()[0]

            self.assertEqual(current_total, stale_total)

    def _write_all_silver_files(self, root: Path, partition_key: str) -> None:
        for freq in STK_MINS_FREQS:
            self._write_silver_file(root, partition_key, freq)
        self._write_stock_daily_file(root, partition_key)

    def _write_silver_file(
        self,
        root: Path,
        partition_key: str,
        freq: int,
        *,
        trade_date: str | None = None,
        duplicate_first_row: bool = False,
        omit_bse_close: bool = False,
    ) -> None:
        path = silver_stk_mins_path(root, freq, partition_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        data_trade_date = trade_date or partition_key
        rows = [
            ("000001.SZ", freq, data_trade_date, f"{partition_key} 09:30:00", 100, 1000.0),
            ("920001.BJ", freq, data_trade_date, f"{partition_key} 09:30:00", 100 + freq, 1000.0 + freq * 10),
            ("000001.SZ", freq, data_trade_date, f"{partition_key} 15:00:00", 200, 2000.0),
            ("920001.BJ", freq, data_trade_date, f"{partition_key} 15:00:00", 0, 0.0),
        ]
        if omit_bse_close:
            rows = [
                row
                for row in rows
                if not (row[0].endswith(".BJ") and str(row[3]).endswith("15:00:00"))
            ]
        if duplicate_first_row:
            rows.append(rows[0])
        values_sql = ", ".join(
            "(" + ", ".join(self._sql_literal(value) for value in row) + ")"
            for row in rows
        )
        with duckdb.connect(database=":memory:") as connection:
            connection.execute(
                f"""
                COPY (
                  SELECT
                    CAST(ts_code AS VARCHAR) AS ts_code,
                    CAST(freq AS INTEGER) AS freq,
                    CAST(trade_date AS DATE) AS trade_date,
                    CAST(trade_time AS TIMESTAMP) AS trade_time,
                    CAST(vol AS DOUBLE) AS vol,
                    CAST(amount AS DOUBLE) AS amount
                  FROM (
                    VALUES {values_sql}
                  ) AS rows(ts_code, freq, trade_date, trade_time, vol, amount)
                ) TO '{path.as_posix()}' (FORMAT PARQUET)
                """
            )

    def _write_stock_daily_file(
        self,
        root: Path,
        partition_key: str,
        *,
        trade_date: str | None = None,
        duplicate_bse: bool = False,
        extra_bse: bool = False,
        bse_vol: float = 10.0,
        bse_amount: float = 10.0,
        empty: bool = False,
    ) -> None:
        path = silver_stock_daily_path(root, partition_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        observed_trade_date = trade_date or partition_key
        rows = [
            ("000001.SZ", observed_trade_date, 3.0, 3.0),
            ("920001.BJ", observed_trade_date, bse_vol, bse_amount),
        ]
        if duplicate_bse:
            rows.append(("920001.BJ", observed_trade_date, bse_vol, bse_amount))
        if extra_bse:
            rows.append(("920002.BJ", observed_trade_date, 1.0, 1.0))
        values_sql = ", ".join(
            "(" + ", ".join(self._sql_literal(value) for value in row) + ")"
            for row in rows
        )
        with duckdb.connect(database=":memory:") as connection:
            if empty:
                connection.execute(
                    f"""
                    COPY (
                      SELECT
                        CAST(NULL AS VARCHAR) AS ts_code,
                        CAST(NULL AS DATE) AS trade_date,
                        CAST(NULL AS DOUBLE) AS vol,
                        CAST(NULL AS DOUBLE) AS amount
                      WHERE false
                    ) TO '{path.as_posix()}' (FORMAT PARQUET)
                    """
                )
                return
            connection.execute(
                f"""
                COPY (
                  SELECT
                    CAST(ts_code AS VARCHAR) AS ts_code,
                    CAST(trade_date AS DATE) AS trade_date,
                    CAST(vol AS DOUBLE) AS vol,
                    CAST(amount AS DOUBLE) AS amount
                  FROM (VALUES {values_sql})
                    rows(ts_code, trade_date, vol, amount)
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
