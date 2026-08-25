import os
import tempfile
import unittest
from pathlib import Path

import duckdb

from orchestrator.defs.checks.wealth_market_turnover_checks import (
    _check_result_from_audit,
)
from orchestrator.defs.paths import (
    gold_wealth_market_turnover_path,
    silver_stk_mins_path,
    silver_stock_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS
from orchestrator.defs.wealth_market_turnover_contract import (
    WealthMarketTurnoverIntegrityAudit,
    audit_gold_wealth_market_turnover_file_contract,
    audit_gold_wealth_market_turnover_recomputed_from_sources,
    wealth_market_turnover_source_paths,
    write_gold_wealth_market_turnover_partition,
)


def _metadata_value(value):  # noqa: ANN001
    return getattr(value, "value", value)


class GoldWealthMarketTurnoverCheckTests(unittest.TestCase):
    def test_check_result_metadata_is_human_readable(self) -> None:
        audit = WealthMarketTurnoverIntegrityAudit(
            passed=False,
            failure_stage="file_contract",
            reason_code="missing_file",
            checked_row_count=0,
            failed_row_count=1,
            missing_file_paths=("/tmp/missing.parquet",),
            sample_rows=(),
            metadata={"expected_row_count": 5},
        )

        result = _check_result_from_audit(audit, file_path=Path("/tmp/missing.parquet"))

        self.assertFalse(result.passed)
        self.assertIn("失败", _metadata_value(result.metadata["goldenshare/summary"]))
        self.assertIn(
            "silver_stk_mins",
            _metadata_value(result.metadata["goldenshare/next_action"]),
        )
        rule_summary = _metadata_value(result.metadata["goldenshare/rule_summary"])
        self.assertEqual(rule_summary["failure_stage"], "file_contract")
        self.assertEqual(rule_summary["reason_code"], "missing_file")

    def test_integrity_audits_pass_for_valid_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self._write_all_silver_files(root, "2026-06-22")
            target_path = gold_wealth_market_turnover_path(root, "2026-06-22")

            with duckdb.connect(database=":memory:") as connection:
                source_paths = wealth_market_turnover_source_paths(root, "2026-06-22")
                write_gold_wealth_market_turnover_partition(
                    duckdb_resource=DuckDBResource(),
                    source_paths=source_paths,
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
                recompute_audit = audit_gold_wealth_market_turnover_recomputed_from_sources(
                    connection=connection,
                    target_path=target_path,
                    source_paths=source_paths,
                    partition_key="2026-06-22",
                )

            self.assertTrue(file_audit.passed)
            self.assertTrue(recompute_audit.passed)

    def test_file_contract_reports_file_contract_failure_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            with duckdb.connect(database=":memory:") as connection:
                audit = audit_gold_wealth_market_turnover_file_contract(
                    connection=connection,
                    target_path=Path(temporary_dir) / "missing.parquet",
                    partition_key="2026-06-22",
                )

            self.assertFalse(audit.passed)
            self.assertEqual(audit.failure_stage, "file_contract")
            self.assertEqual(audit.reason_code, "missing_file")

    def test_file_contract_rejects_empty_points_json(self) -> None:
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
                bad_path = target_path.with_name("bad.parquet")
                connection.execute(
                    f"""
                    COPY (
                      SELECT
                        type,
                        market,
                        trade_date,
                        freq,
                        build_status,
                        latest_trade_time,
                        total_amount,
                        total_vol,
                        security_count,
                        source_row_count,
                        CASE WHEN freq = 1 THEN '[]'::JSON ELSE points_json END
                          AS points_json,
                        build_version,
                        built_at,
                        build_note
                      FROM read_parquet('{target_path.as_posix()}', hive_partitioning=false)
                    ) TO '{bad_path.as_posix()}' (FORMAT PARQUET)
                    """
                )
                audit = audit_gold_wealth_market_turnover_file_contract(
                    connection=connection,
                    target_path=bad_path,
                    partition_key="2026-06-22",
                )

            self.assertFalse(audit.passed)
            self.assertEqual(audit.failure_stage, "file_contract")
            self.assertEqual(audit.reason_code, "points_json_empty_or_not_array")

    def test_recompute_audit_reports_silver_mismatch_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self._write_all_silver_files(root, "2026-06-22")
            target_path = gold_wealth_market_turnover_path(root, "2026-06-22")

            with duckdb.connect(database=":memory:") as connection:
                source_paths = wealth_market_turnover_source_paths(root, "2026-06-22")
                write_gold_wealth_market_turnover_partition(
                    duckdb_resource=DuckDBResource(),
                    source_paths=source_paths,
                    partition_key="2026-06-22",
                    staging_path=root / "staging/part-000.parquet",
                    target_path=target_path,
                    built_at_sql="TIMESTAMP '2026-06-22 20:00:00'",
                )
                bad_path = target_path.with_name("bad.parquet")
                connection.execute(
                    f"""
                    COPY (
                      SELECT
                        type,
                        market,
                        trade_date,
                        freq,
                        build_status,
                        latest_trade_time,
                        CASE
                          WHEN freq = 1 THEN CAST(999 AS DECIMAL(20,2))
                          ELSE total_amount
                        END AS total_amount,
                        total_vol,
                        security_count,
                        source_row_count,
                        points_json,
                        build_version,
                        built_at,
                        build_note
                      FROM read_parquet('{target_path.as_posix()}', hive_partitioning=false)
                    ) TO '{bad_path.as_posix()}' (FORMAT PARQUET)
                    """
                )
                audit = audit_gold_wealth_market_turnover_recomputed_from_sources(
                    connection=connection,
                    target_path=bad_path,
                    source_paths=source_paths,
                    partition_key="2026-06-22",
                )

            self.assertFalse(audit.passed)
            self.assertEqual(audit.failure_stage, "recomputed_from_sources")
            self.assertEqual(audit.reason_code, "gold_source_recompute_mismatch")

    def _write_all_silver_files(self, root: Path, partition_key: str) -> None:
        for freq in STK_MINS_FREQS:
            self._write_silver_file(root, partition_key, freq)
        self._write_stock_daily_file(root, partition_key)

    def _write_silver_file(self, root: Path, partition_key: str, freq: int) -> None:
        path = silver_stk_mins_path(root, freq, partition_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            ("000001.SZ", freq, f"{partition_key} 09:30:00", 100, 1000.0),
            ("920001.BJ", freq, f"{partition_key} 09:30:00", 100 + freq, 1000.0 + freq * 10),
            ("000001.SZ", freq, f"{partition_key} 15:00:00", 200, 2000.0),
            ("920001.BJ", freq, f"{partition_key} 15:00:00", 0, 0.0),
        ]
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

    def _write_stock_daily_file(self, root: Path, partition_key: str) -> None:
        path = silver_stock_daily_path(root, partition_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(database=":memory:") as connection:
            connection.execute(
                f"""
                COPY (
                  SELECT *
                  FROM (
                    VALUES
                      ('000001.SZ', DATE '{partition_key}', 3.0, 3.0),
                      ('920001.BJ', DATE '{partition_key}', 10.0, 10.0)
                  ) rows(ts_code, trade_date, vol, amount)
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
