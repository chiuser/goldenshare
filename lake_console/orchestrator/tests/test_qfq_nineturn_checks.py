import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.qfq_nineturn_integrity import (
    QFQ_NINETURN_INTEGRITY_RULE_NAMES,
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

    def test_rule_set_is_fixed_and_formula_free(self) -> None:
        self.assertEqual(
            QFQ_NINETURN_INTEGRITY_RULE_NAMES,
            (
                "file_contract",
                "partition_alignment",
                "key_integrity",
                "value_domain",
                "source_key_coverage",
                "source_value_consistency",
            ),
        )


if __name__ == "__main__":
    unittest.main()
