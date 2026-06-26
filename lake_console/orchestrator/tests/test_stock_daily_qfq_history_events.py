import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import dagster as dg
import duckdb

from orchestrator.defs.bootstrap.gold_stock_daily_qfq_history import (
    generate_gold_stock_daily_qfq_history,
)
from orchestrator.defs.bootstrap.gold_stock_daily_qfq_history_events import (
    GOLD_STOCK_DAILY_QFQ_RUNLESS_CHECK_WINDOW_SIZE,
    audit_gold_stock_daily_qfq_history_partition,
    plan_gold_stock_daily_qfq_runless_events,
    recent_gold_stock_daily_qfq_check_partitions,
    report_gold_stock_daily_qfq_runless_events,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import gold_stock_daily_qfq_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.sensors.readiness import (
    GOLD_STOCK_DAILY_QFQ_ASSET_KEY,
    GOLD_STOCK_DAILY_QFQ_CHECKS,
    GOLD_STOCK_DAILY_QFQ_READINESS_SPECS,
    asset_readiness_status,
)
from tests.test_stock_daily_qfq_contracts import EARLIER_DATE, PREVIOUS_DATE, TRADE_DATE
from tests.test_stock_daily_qfq_history import _prepare_history_lake


class StockDailyQfqHistoryEventTests(unittest.TestCase):
    def test_runless_plan_uses_full_materialization_and_recent_checks(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_history_lake(root)
            _generate_history(root, (EARLIER_DATE, PREVIOUS_DATE, TRADE_DATE))
            instance = dg.DagsterInstance.ephemeral()

            plan = plan_gold_stock_daily_qfq_runless_events(
                instance=instance,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                start_date=EARLIER_DATE,
                end_date=TRADE_DATE,
            )

        self.assertEqual(
            plan.materialization_partition_keys,
            (EARLIER_DATE, PREVIOUS_DATE, TRADE_DATE),
        )
        self.assertEqual(
            plan.check_partition_keys,
            (EARLIER_DATE, PREVIOUS_DATE, TRADE_DATE),
        )
        self.assertLessEqual(
            len(plan.check_partition_keys),
            GOLD_STOCK_DAILY_QFQ_RUNLESS_CHECK_WINDOW_SIZE + 1,
        )
        self.assertEqual(plan.failed_check_partition_count, 0)
        self.assertEqual(plan.planned_materialization_event_count, 3)
        self.assertEqual(plan.planned_check_event_count, 6)

    def test_default_recent_checks_ignore_calendar_after_latest_target(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_history_lake(root)
            _generate_history(root, (EARLIER_DATE, PREVIOUS_DATE))
            instance = dg.DagsterInstance.ephemeral()

            check_keys = recent_gold_stock_daily_qfq_check_partitions(
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                start_date=EARLIER_DATE,
                end_date=TRADE_DATE,
            )
            plan = plan_gold_stock_daily_qfq_runless_events(
                instance=instance,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                start_date=EARLIER_DATE,
                end_date=TRADE_DATE,
            )

        self.assertEqual(check_keys, (EARLIER_DATE, PREVIOUS_DATE))
        self.assertEqual(
            plan.materialization_partition_keys,
            (EARLIER_DATE, PREVIOUS_DATE),
        )
        self.assertEqual(plan.check_partition_keys, (EARLIER_DATE, PREVIOUS_DATE))
        self.assertNotIn(TRADE_DATE, plan.check_partition_keys)
        self.assertEqual(plan.failed_check_partition_count, 0)

    def test_runless_dry_run_does_not_write_events(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_history_lake(root)
            _generate_history(root, (TRADE_DATE,))
            instance = dg.DagsterInstance.ephemeral()

            report = report_gold_stock_daily_qfq_runless_events(
                instance=instance,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                materialization_partition_keys=(TRADE_DATE,),
                check_partition_keys=(TRADE_DATE,),
                dry_run=True,
            )
            materializations = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=GOLD_STOCK_DAILY_QFQ_ASSET_KEY,
                    asset_partitions=[TRADE_DATE],
                ),
                limit=1,
            ).records

        self.assertTrue(report.dry_run)
        self.assertEqual(report.reported_event_count, 0)
        self.assertEqual(materializations, [])

    def test_runless_apply_reports_materialization_and_two_checks(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_history_lake(root)
            _generate_history(root, (TRADE_DATE,))
            instance = dg.DagsterInstance.ephemeral()

            report = report_gold_stock_daily_qfq_runless_events(
                instance=instance,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                materialization_partition_keys=(TRADE_DATE,),
                check_partition_keys=(TRADE_DATE,),
                dry_run=False,
                history_audit_report_path="/private/tmp/example.json",
            )
            readiness = asset_readiness_status(
                instance,
                GOLD_STOCK_DAILY_QFQ_READINESS_SPECS[0],
                partition_key=TRADE_DATE,
            )

        self.assertEqual(report.reported_materialization_partition_keys, (TRADE_DATE,))
        self.assertEqual(report.reported_check_partition_keys, (TRADE_DATE,))
        self.assertEqual(report.reported_event_count, 1 + len(GOLD_STOCK_DAILY_QFQ_CHECKS))
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.failed_check_names, ())

    def test_failed_audit_blocks_apply(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_history_lake(root)
            _generate_history(root, (TRADE_DATE,))
            _corrupt_qfq_close(root, TRADE_DATE)
            instance = dg.DagsterInstance.ephemeral()

            audit = audit_gold_stock_daily_qfq_history_partition(
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_key=TRADE_DATE,
            )
            with self.assertRaisesRegex(ValueError, "runless audit failed"):
                report_gold_stock_daily_qfq_runless_events(
                    instance=instance,
                    lake_root=root,
                    duckdb_resource=DuckDBResource(),
                    materialization_partition_keys=(TRADE_DATE,),
                    check_partition_keys=(TRADE_DATE,),
                    dry_run=False,
                )

        self.assertFalse(audit.passed)
        self.assertIn(
            "gold_stock_daily_qfq_qfq_semantics_check",
            audit.failed_check_names,
        )


def _generate_history(root: Path, partition_keys: tuple[str, ...]) -> None:
    generate_gold_stock_daily_qfq_history(
        lake_root=root,
        duckdb_resource=DuckDBResource(),
        partition_keys=partition_keys,
    )


def _corrupt_qfq_close(root: Path, partition_key: str) -> None:
    path = gold_stock_daily_qfq_path(root, partition_key)
    tmp_path = path.with_suffix(".tmp.parquet")
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                ts_code,
                trade_date,
                open,
                high,
                low,
                close + 1 AS close,
                pre_close,
                change_amount,
                pct_chg,
                vol,
                amount
              FROM {read_parquet(path, hive_partitioning=False)}
            ) TO {duckdb_string(tmp_path)} (FORMAT PARQUET)
            """
        )
    os.replace(tmp_path, path)


if __name__ == "__main__":
    unittest.main()
