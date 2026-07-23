import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.asset_guards.adj_factor_lake_readiness import (
    SILVER_ADJ_FACTOR_COVERAGE_COMPLETE_CHECK,
    SILVER_ADJ_FACTOR_LISTED_STOCK_ONLY_CHECK,
    assess_silver_adj_factor_lifecycle_rebuildability,
)
from orchestrator.defs.asset_guards.bounded_continuity import ContinuityDateReadiness
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_stock_lifecycle_path,
)


TRADE_DATE = "2026-06-05"


def _readiness_status(
    *,
    ready: bool,
    materialized: bool = True,
    failed_check_names: tuple[str, ...] = (),
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=TRADE_DATE,
        ready=ready,
        materialized=materialized,
        checks_passed=ready,
        reason="ready" if ready else "not_ready",
        failed_check_names=failed_check_names,
        missing_file_paths=(),
    )


def _write_fixture_files(*, lake_root: Path, raw_codes: tuple[str, ...]) -> None:
    raw_path = raw_adj_factor_path(lake_root, TRADE_DATE)
    silver_path = silver_adj_factor_path(lake_root, TRADE_DATE)
    lifecycle_path = silver_stock_lifecycle_path(lake_root)
    for path in (raw_path, silver_path, lifecycle_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    raw_values = ", ".join(
        f"({duckdb_string(ts_code)}, '20260605', 1.0)" for ts_code in raw_codes
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (VALUES {raw_values})
                AS raw(ts_code, trade_date, adj_factor)
            ) TO {duckdb_string(raw_path)} (FORMAT PARQUET)
            """
        )
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (VALUES
                ('000001.SZ', DATE '2020-01-01', NULL::DATE, true),
                ('000002.SZ', DATE '2020-01-01', NULL::DATE, true)
              ) AS lifecycle(ts_code, list_date, delist_date, is_cny_stock)
            ) TO {duckdb_string(lifecycle_path)} (FORMAT PARQUET)
            """
        )
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (VALUES ('000001.SZ', DATE '2026-06-05', 1.0))
                AS silver(ts_code, trade_date, adj_factor)
            ) TO {duckdb_string(silver_path)} (FORMAT PARQUET)
            """
        )


class AdjFactorLifecycleRebuildabilityTests(unittest.TestCase):
    def test_eligible_when_only_lifecycle_coverage_failed_and_raw_covers_lifecycle(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            _write_fixture_files(
                lake_root=lake_root,
                raw_codes=("000001.SZ", "000002.SZ"),
            )
            with duckdb.connect(database=":memory:") as connection:
                assessment = assess_silver_adj_factor_lifecycle_rebuildability(
                    connection=connection,
                    lake_root=lake_root,
                    trade_date=TRADE_DATE,
                    raw_status=_readiness_status(ready=True),
                    silver_status=_readiness_status(
                        ready=False,
                        failed_check_names=(
                            SILVER_ADJ_FACTOR_COVERAGE_COMPLETE_CHECK,
                        ),
                    ),
                )

        self.assertTrue(assessment.eligible)
        self.assertEqual(assessment.reason_code, "lifecycle_rebuild_eligible")
        self.assertEqual(assessment.expected_code_count, 2)
        self.assertEqual(assessment.raw_missing_code_count, 0)
        self.assertEqual(assessment.raw_missing_code_samples, ())

    def test_eligible_when_both_lifecycle_rules_failed(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            _write_fixture_files(
                lake_root=lake_root,
                raw_codes=("000001.SZ", "000002.SZ"),
            )
            with duckdb.connect(database=":memory:") as connection:
                assessment = assess_silver_adj_factor_lifecycle_rebuildability(
                    connection=connection,
                    lake_root=lake_root,
                    trade_date=TRADE_DATE,
                    raw_status=_readiness_status(ready=True),
                    silver_status=_readiness_status(
                        ready=False,
                        failed_check_names=(
                            SILVER_ADJ_FACTOR_LISTED_STOCK_ONLY_CHECK,
                            SILVER_ADJ_FACTOR_COVERAGE_COMPLETE_CHECK,
                        ),
                    ),
                )

        self.assertTrue(assessment.eligible)
        self.assertEqual(assessment.expected_code_count, 2)

    def test_rejects_when_raw_misses_current_lifecycle_code(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            _write_fixture_files(lake_root=lake_root, raw_codes=("000001.SZ",))
            with duckdb.connect(database=":memory:") as connection:
                assessment = assess_silver_adj_factor_lifecycle_rebuildability(
                    connection=connection,
                    lake_root=lake_root,
                    trade_date=TRADE_DATE,
                    raw_status=_readiness_status(ready=True),
                    silver_status=_readiness_status(
                        ready=False,
                        failed_check_names=(
                            SILVER_ADJ_FACTOR_COVERAGE_COMPLETE_CHECK,
                        ),
                    ),
                )

        self.assertFalse(assessment.eligible)
        self.assertEqual(assessment.reason_code, "raw_missing_lifecycle_coverage")
        self.assertEqual(assessment.raw_missing_code_count, 1)
        self.assertEqual(assessment.raw_missing_code_samples, ("000002.SZ",))

    def test_rejects_non_lifecycle_check_failure_without_scanning_files(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            with duckdb.connect(database=":memory:") as connection:
                assessment = assess_silver_adj_factor_lifecycle_rebuildability(
                    connection=connection,
                    lake_root=lake_root,
                    trade_date=TRADE_DATE,
                    raw_status=_readiness_status(ready=True),
                    silver_status=_readiness_status(
                        ready=False,
                        failed_check_names=("silver_adj_factor_positive_factor",),
                    ),
                )

        self.assertFalse(assessment.eligible)
        self.assertEqual(
            assessment.reason_code,
            "non_lifecycle_silver_check_failed",
        )

    def test_rejects_raw_not_ready_without_scanning_files(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            with duckdb.connect(database=":memory:") as connection:
                assessment = assess_silver_adj_factor_lifecycle_rebuildability(
                    connection=connection,
                    lake_root=lake_root,
                    trade_date=TRADE_DATE,
                    raw_status=_readiness_status(ready=False, materialized=False),
                    silver_status=_readiness_status(
                        ready=False,
                        failed_check_names=(
                            SILVER_ADJ_FACTOR_COVERAGE_COMPLETE_CHECK,
                        ),
                    ),
                )

        self.assertFalse(assessment.eligible)
        self.assertEqual(assessment.reason_code, "raw_not_ready")


if __name__ == "__main__":
    unittest.main()
