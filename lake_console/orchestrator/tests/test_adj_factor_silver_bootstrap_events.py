import tempfile
import unittest
from pathlib import Path

import dagster as dg
import duckdb

from orchestrator.defs.bootstrap.adj_factor_raw_bootstrap_events import (
    report_adj_factor_raw_bootstrap_events,
)
from orchestrator.defs.bootstrap.adj_factor_silver_bootstrap_events import (
    plan_adj_factor_silver_bootstrap_events,
    report_adj_factor_silver_bootstrap_events,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.paths import (
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_stock_basic_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.sensors.readiness import (
    SILVER_ADJ_FACTOR_ASSET_KEY,
    SILVER_ADJ_FACTOR_BLOCKING_CHECKS,
    AssetReadinessSpec,
    adj_factor_ready_for_trade_date,
    asset_readiness_status,
)


TARGET_TRADE_DATE = "2026-05-29"


def _sql_string(value: str) -> str:
    return f"{duckdb_string(value)}::VARCHAR"


def _write_raw_adj_factor_file(
    root: Path,
    trade_date: str,
    rows: tuple[tuple[str, str, float], ...],
) -> Path:
    path = raw_adj_factor_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(
        f"({_sql_string(ts_code)}, {_sql_string(row_trade_date)}, {factor}::DOUBLE)"
        for ts_code, row_trade_date, factor in rows
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT *
              FROM (VALUES {values_sql}) rows(ts_code, trade_date, adj_factor)
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )
    return path


def _write_silver_stock_basic_file(
    root: Path,
    rows: tuple[tuple[str, str, str], ...],
) -> Path:
    path = silver_stock_basic_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(
        f"({_sql_string(ts_code)}, {_sql_string(list_status)}, DATE {duckdb_string(list_date)})"
        for ts_code, list_status, list_date in rows
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT *
              FROM (VALUES {values_sql}) rows(ts_code, list_status, list_date)
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )
    return path


def _write_silver_adj_factor_file(
    root: Path,
    trade_date: str,
    rows: tuple[tuple[str, str, float], ...],
) -> Path:
    path = silver_adj_factor_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(
        f"({_sql_string(ts_code)}, DATE {duckdb_string(row_trade_date)}, {factor}::DOUBLE)"
        for ts_code, row_trade_date, factor in rows
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT *
              FROM (VALUES {values_sql}) rows(ts_code, trade_date, adj_factor)
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )
    return path


class AdjFactorSilverBootstrapEventTests(unittest.TestCase):
    def test_reports_runless_silver_materialization_and_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_raw_adj_factor_file(
                root,
                TARGET_TRADE_DATE,
                (("000001.SZ", "20260529", 1.1),),
            )
            _write_silver_stock_basic_file(
                root,
                (("000001.SZ", "L", "2020-01-01"),),
            )
            _write_silver_adj_factor_file(
                root,
                TARGET_TRADE_DATE,
                (("000001.SZ", TARGET_TRADE_DATE, 1.1),),
            )
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_current_trade_days.name,
                [TARGET_TRADE_DATE],
            )
            report_adj_factor_raw_bootstrap_events(
                instance=instance,
                lake_root=root,
                duckdb=DuckDBResource(),
                partition_keys=[TARGET_TRADE_DATE],
                dry_run=False,
                today=TARGET_TRADE_DATE,
            )

            report = report_adj_factor_silver_bootstrap_events(
                instance=instance,
                lake_root=root,
                duckdb=DuckDBResource(),
                partition_keys=[TARGET_TRADE_DATE],
                dry_run=False,
                today=TARGET_TRADE_DATE,
            )
            silver_readiness = asset_readiness_status(
                instance,
                AssetReadinessSpec(
                    SILVER_ADJ_FACTOR_ASSET_KEY,
                    SILVER_ADJ_FACTOR_BLOCKING_CHECKS,
                ),
                partition_key=TARGET_TRADE_DATE,
            )
            dataset_readiness = adj_factor_ready_for_trade_date(
                instance,
                TARGET_TRADE_DATE,
            )

        self.assertEqual(report.reported_partition_keys, (TARGET_TRADE_DATE,))
        self.assertEqual(
            report.reported_event_count,
            1 + len(SILVER_ADJ_FACTOR_BLOCKING_CHECKS),
        )
        self.assertTrue(silver_readiness.ready)
        self.assertTrue(dataset_readiness.ready)

    def test_dry_run_does_not_write_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_silver_stock_basic_file(
                root,
                (("000001.SZ", "L", "2020-01-01"),),
            )
            _write_silver_adj_factor_file(
                root,
                TARGET_TRADE_DATE,
                (("000001.SZ", TARGET_TRADE_DATE, 1.1),),
            )
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_current_trade_days.name,
                [TARGET_TRADE_DATE],
            )

            report = report_adj_factor_silver_bootstrap_events(
                instance=instance,
                lake_root=root,
                duckdb=DuckDBResource(),
                partition_keys=[TARGET_TRADE_DATE],
                dry_run=True,
                today=TARGET_TRADE_DATE,
            )
            materializations = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=SILVER_ADJ_FACTOR_ASSET_KEY,
                    asset_partitions=[TARGET_TRADE_DATE],
                ),
                limit=1,
            ).records

        self.assertTrue(report.dry_run)
        self.assertEqual(report.reported_event_count, 0)
        self.assertEqual(materializations, [])

    def test_failed_silver_audit_blocks_event_reporting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_silver_stock_basic_file(
                root,
                (
                    ("000001.SZ", "L", "2020-01-01"),
                    ("000002.SZ", "L", "2020-01-01"),
                ),
            )
            _write_silver_adj_factor_file(
                root,
                TARGET_TRADE_DATE,
                (("000001.SZ", TARGET_TRADE_DATE, -1.0),),
            )
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_current_trade_days.name,
                [TARGET_TRADE_DATE],
            )

            plan = plan_adj_factor_silver_bootstrap_events(
                instance=instance,
                lake_root=root,
                duckdb=DuckDBResource(),
                partition_keys=[TARGET_TRADE_DATE],
                today=TARGET_TRADE_DATE,
            )
            with self.assertRaisesRegex(ValueError, "bootstrap audit failed"):
                report_adj_factor_silver_bootstrap_events(
                    instance=instance,
                    lake_root=root,
                    duckdb=DuckDBResource(),
                    partition_keys=[TARGET_TRADE_DATE],
                    dry_run=False,
                    today=TARGET_TRADE_DATE,
                )

        self.assertEqual(plan.failed_partition_count, 1)
        self.assertIn(
            "silver_adj_factor_positive_factor",
            plan.partition_audits[0].failed_check_names,
        )
        self.assertIn(
            "silver_adj_factor_coverage_complete",
            plan.partition_audits[0].failed_check_names,
        )

    def test_partition_alignment_mismatch_fails_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_silver_stock_basic_file(
                root,
                (("000001.SZ", "L", "2020-01-01"),),
            )
            _write_silver_adj_factor_file(
                root,
                "2026-05-28",
                (("000001.SZ", "2026-05-28", 1.1),),
            )
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_current_trade_days.name,
                [TARGET_TRADE_DATE],
            )

            with self.assertRaisesRegex(ValueError, "not aligned"):
                plan_adj_factor_silver_bootstrap_events(
                    instance=instance,
                    lake_root=root,
                    duckdb=DuckDBResource(),
                    today=TARGET_TRADE_DATE,
                )

    def test_existing_ready_partition_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_silver_stock_basic_file(
                root,
                (("000001.SZ", "L", "2020-01-01"),),
            )
            _write_silver_adj_factor_file(
                root,
                TARGET_TRADE_DATE,
                (("000001.SZ", TARGET_TRADE_DATE, 1.1),),
            )
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_current_trade_days.name,
                [TARGET_TRADE_DATE],
            )

            first_report = report_adj_factor_silver_bootstrap_events(
                instance=instance,
                lake_root=root,
                duckdb=DuckDBResource(),
                partition_keys=[TARGET_TRADE_DATE],
                dry_run=False,
                today=TARGET_TRADE_DATE,
            )
            second_report = report_adj_factor_silver_bootstrap_events(
                instance=instance,
                lake_root=root,
                duckdb=DuckDBResource(),
                partition_keys=[TARGET_TRADE_DATE],
                dry_run=False,
                today=TARGET_TRADE_DATE,
            )

        self.assertEqual(first_report.reported_partition_keys, (TARGET_TRADE_DATE,))
        self.assertEqual(second_report.reported_partition_keys, ())
        self.assertEqual(second_report.skipped_ready_partition_keys, (TARGET_TRADE_DATE,))

    def test_helper_file_does_not_define_dagster_components(self) -> None:
        helper_path = (
            Path(__file__).parents[1]
            / "src"
            / "orchestrator"
            / "defs"
            / "bootstrap"
            / "adj_factor_silver_bootstrap_events.py"
        )
        source = helper_path.read_text()

        self.assertNotIn("@dg.asset", source)
        self.assertNotIn("@dg.sensor", source)
        self.assertNotIn("define_asset_job", source)
        self.assertNotIn("@dg.asset_check", source)


if __name__ == "__main__":
    unittest.main()
