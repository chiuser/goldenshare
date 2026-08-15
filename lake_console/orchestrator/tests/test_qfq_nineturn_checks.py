import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.qfq_nineturn_integrity import (
    QFQ_NINETURN_DAILY_INTEGRITY_RULE_NAMES,
    QFQ_NINETURN_MINUTE_INTEGRITY_RULE_NAMES,
    audit_qfq_nineturn_integrity,
)

TRADE_DATE = "2026-08-07"


def _write_daily_source(connection, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"""
        COPY (
          SELECT '000001.SZ'::VARCHAR AS ts_code,
            DATE '{TRADE_DATE}' AS trade_date,
            10.0::DOUBLE AS close
        ) TO '{path}' (FORMAT PARQUET)
        """
    )


def _write_daily_target(
    connection,
    path: Path,
    *,
    ts_code: str = "000001.SZ",
    up_count: int = 9,
    close_qfq: float = 10.0,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    signal = "'+9'::VARCHAR" if up_count >= 9 else "NULL::VARCHAR"
    connection.execute(
        f"""
        COPY (
          SELECT '{ts_code}'::VARCHAR AS ts_code,
            DATE '{TRADE_DATE}' AS trade_date,
            {close_qfq}::DOUBLE AS close_qfq,
            {up_count}::INTEGER AS up_count,
            0::INTEGER AS down_count,
            {signal} AS nine_up_turn,
            NULL::VARCHAR AS nine_down_turn
        ) TO '{path}' (FORMAT PARQUET)
        """
    )


def _write_minute_source(
    connection,
    path: Path,
    *,
    duplicate: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    duplicate_sql = "UNION ALL SELECT * FROM source_rows" if duplicate else ""
    connection.execute(
        f"""
        COPY (
          WITH source_rows AS (
            SELECT '000001.SZ'::VARCHAR AS ts_code,
              30::INTEGER AS freq,
              DATE '{TRADE_DATE}' AS trade_date,
              TIMESTAMP '{TRADE_DATE} 10:00:00' AS trade_time,
              10.0::DOUBLE AS close
          )
          SELECT * FROM source_rows
          {duplicate_sql}
        ) TO '{path}' (FORMAT PARQUET)
        """
    )


def _write_minute_target(
    connection,
    path: Path,
    *,
    include_legacy_close: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    close_projection = "10.0::DOUBLE AS close_qfq," if include_legacy_close else ""
    connection.execute(
        f"""
        COPY (
          SELECT '000001.SZ'::VARCHAR AS ts_code,
            30::INTEGER AS freq,
            DATE '{TRADE_DATE}' AS trade_date,
            TIMESTAMP '{TRADE_DATE} 10:00:00' AS trade_time,
            {close_projection}
            9::INTEGER AS up_count,
            0::INTEGER AS down_count,
            '+9'::VARCHAR AS nine_up_turn,
            NULL::VARCHAR AS nine_down_turn
        ) TO '{path}' (FORMAT PARQUET)
        """
    )


class QfqNineturnIntegrityTests(unittest.TestCase):
    def test_daily_integrity_passes_without_recalculating_formula(self) -> None:
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:") as connection,
        ):
            root = Path(directory)
            source = root / "source.parquet"
            target = root / "target.parquet"
            _write_daily_source(connection, source)
            _write_daily_target(connection, target, up_count=11)

            diagnostics = audit_qfq_nineturn_integrity(
                connection,
                target_path=target,
                source_paths=(source,),
                partition_key=TRADE_DATE,
                freq=None,
            )

        self.assertTrue(diagnostics.passed)
        self.assertEqual(diagnostics.failed_rule_names, ())
        self.assertEqual(diagnostics.checked_row_count, 1)
        self.assertEqual(diagnostics.source_row_count, 1)

    def test_source_key_gap_fails_the_single_aggregate_check(self) -> None:
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:") as connection,
        ):
            root = Path(directory)
            source = root / "source.parquet"
            target = root / "target.parquet"
            _write_daily_source(connection, source)
            _write_daily_target(connection, target, ts_code="000002.SZ")

            diagnostics = audit_qfq_nineturn_integrity(
                connection,
                target_path=target,
                source_paths=(source,),
                partition_key=TRADE_DATE,
                freq=None,
            )

        self.assertFalse(diagnostics.passed)
        self.assertEqual(diagnostics.missing_source_key_count, 1)
        self.assertEqual(diagnostics.extra_output_key_count, 1)
        self.assertIn("source_key_coverage", diagnostics.failed_rule_names)
        self.assertLessEqual(len(diagnostics.failure_samples), 20)

    def test_source_close_drift_fails_before_downstream_publication(self) -> None:
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:") as connection,
        ):
            root = Path(directory)
            source = root / "source.parquet"
            target = root / "target.parquet"
            _write_daily_source(connection, source)
            _write_daily_target(connection, target, close_qfq=9.5)

            diagnostics = audit_qfq_nineturn_integrity(
                connection,
                target_path=target,
                source_paths=(source,),
                partition_key=TRADE_DATE,
                freq=None,
            )

        self.assertFalse(diagnostics.passed)
        self.assertEqual(diagnostics.source_value_mismatch_count, 1)
        self.assertIn("source_value_consistency", diagnostics.failed_rule_names)
        self.assertEqual(
            diagnostics.failure_samples[0]["failure"],
            "source_value_mismatch",
        )

    def test_minute_integrity_uses_key_and_signal_contract_without_price(self) -> None:
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:") as connection,
        ):
            root = Path(directory)
            source = root / "source.parquet"
            target = root / "target.parquet"
            _write_minute_source(connection, source)
            _write_minute_target(connection, target)

            diagnostics = audit_qfq_nineturn_integrity(
                connection,
                target_path=target,
                source_paths=(source,),
                partition_key=TRADE_DATE,
                freq=30,
            )

        self.assertTrue(diagnostics.passed)
        self.assertEqual(diagnostics.source_value_mismatch_count, 0)
        self.assertNotIn("source_value_consistency", diagnostics.failed_rule_names)

    def test_minute_integrity_rejects_old_schema_with_close_qfq(self) -> None:
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:") as connection,
        ):
            root = Path(directory)
            source = root / "source.parquet"
            target = root / "target.parquet"
            _write_minute_source(connection, source)
            _write_minute_target(connection, target, include_legacy_close=True)

            diagnostics = audit_qfq_nineturn_integrity(
                connection,
                target_path=target,
                source_paths=(source,),
                partition_key=TRADE_DATE,
                freq=30,
            )

        self.assertFalse(diagnostics.passed)
        self.assertEqual(diagnostics.failed_rule_names, ("file_contract",))
        self.assertEqual(diagnostics.failure_samples[0]["failure"], "schema_mismatch")

    def test_minute_integrity_rejects_duplicate_source_keys(self) -> None:
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:") as connection,
        ):
            root = Path(directory)
            source = root / "source.parquet"
            target = root / "target.parquet"
            _write_minute_source(connection, source, duplicate=True)
            _write_minute_target(connection, target)

            diagnostics = audit_qfq_nineturn_integrity(
                connection,
                target_path=target,
                source_paths=(source,),
                partition_key=TRADE_DATE,
                freq=30,
            )

        self.assertFalse(diagnostics.passed)
        self.assertEqual(diagnostics.source_duplicate_key_count, 1)
        self.assertIn("source_key_coverage", diagnostics.failed_rule_names)
        self.assertEqual(
            diagnostics.failure_samples[0]["failure"], "duplicate_source_key"
        )

    def test_rule_set_is_fixed_and_formula_free(self) -> None:
        self.assertEqual(
            QFQ_NINETURN_DAILY_INTEGRITY_RULE_NAMES,
            (
                "file_contract",
                "partition_alignment",
                "key_integrity",
                "value_domain",
                "source_key_coverage",
                "source_value_consistency",
            ),
        )
        self.assertEqual(
            QFQ_NINETURN_MINUTE_INTEGRITY_RULE_NAMES,
            (
                "file_contract",
                "partition_alignment",
                "key_integrity",
                "value_domain",
                "source_key_coverage",
            ),
        )


if __name__ == "__main__":
    unittest.main()
