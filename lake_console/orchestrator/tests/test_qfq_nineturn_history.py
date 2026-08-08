from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import duckdb

from orchestrator.defs.bootstrap.qfq_nineturn_history import (
    QfqNineturnHistoryError,
    build_qfq_nineturn_history,
    load_qfq_nineturn_history_plan,
    plan_qfq_nineturn_history,
    plan_qfq_nineturn_scoped_rebuild,
    rebuild_qfq_nineturn_scope,
)
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_nineturn_path,
    gold_stock_daily_qfq_nineturn_path,
)
from orchestrator.defs.qfq_nineturn import (
    build_gold_stk_mins_qfq_nineturn_select_sql,
    build_gold_stock_daily_qfq_nineturn_select_sql,
)
from orchestrator.defs.resources import DuckDBResource
from tests.qfq_nineturn_history_fixture import (
    build_qfq_nineturn_history_fixture,
)


class QfqNineturnHistoryTests(unittest.TestCase):
    def test_plan_is_read_only_and_freezes_expected_scale(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dates = build_qfq_nineturn_history_fixture(root)
            output_dir = root / "reports"

            plan = plan_qfq_nineturn_history(
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=output_dir,
            )

            self.assertFalse(plan.should_stop)
            self.assertEqual(len(plan.batches), 10)
            self.assertEqual(plan.report["expected_target_file_count"], len(dates) * 5)
            self.assertEqual(plan.report["source_row_count"], len(dates) * 2 * 5)
            self.assertEqual(plan.report["existing_target_file_count"], 0)
            self.assertEqual(plan.report["performance"]["historical_rescan_multiplier"], 1)
            self.assertFalse(
                gold_stock_daily_qfq_nineturn_path(root, dates[0]).exists()
            )

            loaded = load_qfq_nineturn_history_plan(plan.report_path)
            self.assertEqual(loaded.plan_fingerprint, plan.plan_fingerprint)
            self.assertEqual(
                tuple(batch.to_dict() for batch in loaded.batches),
                tuple(batch.to_dict() for batch in plan.batches),
            )

    def test_build_preserves_cross_year_count_and_is_idempotent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dates = build_qfq_nineturn_history_fixture(root)
            resource = DuckDBResource()
            plan = plan_qfq_nineturn_history(
                lake_root=root,
                duckdb_resource=resource,
                output_dir=root / "reports",
            )

            report = build_qfq_nineturn_history(
                plan=plan,
                expected_plan_fingerprint=plan.plan_fingerprint,
                duckdb_resource=resource,
                output_dir=root / "reports",
            )

            self.assertEqual(report.promoted_file_count, len(dates) * 5)
            first_new_year_date = next(value for value in dates if value.startswith("2026-"))
            with duckdb.connect() as connection:
                daily_count = connection.execute(
                    f"""
                    SELECT up_count
                    FROM read_parquet(
                      '{gold_stock_daily_qfq_nineturn_path(root, first_new_year_date)}',
                      hive_partitioning=false
                    )
                    WHERE ts_code = '000001.SZ'
                    """
                ).fetchone()[0]
                minute_count = connection.execute(
                    f"""
                    SELECT up_count
                    FROM read_parquet(
                      '{gold_stk_mins_qfq_nineturn_path(root, 30, first_new_year_date)}',
                      hive_partitioning=false
                    )
                    WHERE ts_code = '000001.SZ'
                    """
                ).fetchone()[0]
                daily_source_paths = tuple(
                    sorted(
                        (
                            root / "gold" / "quote" / "stock_daily_qfq"
                        ).glob("trade_date=*/part-000.parquet")
                    )
                )
                daily_target_paths = tuple(
                    gold_stock_daily_qfq_nineturn_path(root, value)
                    for value in dates
                )
                minute_source_paths = tuple(
                    sorted(
                        (
                            root
                            / "gold"
                            / "quote"
                            / "stk_mins_qfq"
                            / "freq=30"
                        ).glob("ts_code=*/year=*/part-000.parquet")
                    )
                )
                minute_target_paths = tuple(
                    gold_stk_mins_qfq_nineturn_path(root, 30, value)
                    for value in dates
                )
                daily_diff = _full_history_difference_count(
                    connection,
                    expected_sql=build_gold_stock_daily_qfq_nineturn_select_sql(
                        source_paths=daily_source_paths,
                    ),
                    target_paths=daily_target_paths,
                )
                minute_diff = _full_history_difference_count(
                    connection,
                    expected_sql=build_gold_stk_mins_qfq_nineturn_select_sql(
                        source_paths=minute_source_paths,
                        freq=30,
                    ),
                    target_paths=minute_target_paths,
                )
            self.assertGreater(daily_count, 1)
            self.assertEqual(daily_count, minute_count)
            self.assertEqual(daily_diff, 0)
            self.assertEqual(minute_diff, 0)

            second_plan = plan_qfq_nineturn_history(
                lake_root=root,
                duckdb_resource=resource,
                output_dir=root / "reports",
            )
            second_report = build_qfq_nineturn_history(
                plan=second_plan,
                expected_plan_fingerprint=second_plan.plan_fingerprint,
                duckdb_resource=resource,
                output_dir=root / "reports",
            )
            self.assertEqual(second_report.promoted_file_count, 0)
            self.assertTrue(
                all(result.reused_file_count for result in second_report.batch_results)
            )

    def test_stale_plan_is_rejected_before_lake_write(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dates = build_qfq_nineturn_history_fixture(root)
            resource = DuckDBResource()
            plan = plan_qfq_nineturn_history(
                lake_root=root,
                duckdb_resource=resource,
                output_dir=root / "reports",
            )
            source = (
                root
                / "gold"
                / "quote"
                / "stock_daily_qfq"
                / f"trade_date={dates[0]}"
                / "part-000.parquet"
            )
            stat = source.stat()
            os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))

            with self.assertRaisesRegex(QfqNineturnHistoryError, "stale"):
                build_qfq_nineturn_history(
                    plan=plan,
                    expected_plan_fingerprint=plan.plan_fingerprint,
                    duckdb_resource=resource,
                    output_dir=root / "reports",
                )
            self.assertFalse(
                gold_stock_daily_qfq_nineturn_path(root, dates[0]).exists()
            )

    def test_scoped_rebuild_replaces_only_approved_code_and_dates(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dates = build_qfq_nineturn_history_fixture(root)
            resource = DuckDBResource()
            plan = plan_qfq_nineturn_history(
                lake_root=root,
                duckdb_resource=resource,
                output_dir=root / "reports",
            )
            build_qfq_nineturn_history(
                plan=plan,
                expected_plan_fingerprint=plan.plan_fingerprint,
                duckdb_resource=resource,
                output_dir=root / "reports",
            )
            target_date = dates[-1]
            target = gold_stock_daily_qfq_nineturn_path(root, target_date)
            with duckdb.connect() as connection:
                before_other = connection.execute(
                    f"""
                    SELECT * FROM read_parquet('{target}', hive_partitioning=false)
                    WHERE ts_code = '000002.SZ'
                    """
                ).fetchone()
                damaged = root / "damaged.parquet"
                connection.execute(
                    f"""
                    COPY (
                      SELECT ts_code, trade_date,
                             CASE WHEN ts_code = '000001.SZ' THEN 999.0 ELSE close_qfq END
                               AS close_qfq,
                             up_count, down_count, nine_up_turn, nine_down_turn
                      FROM read_parquet('{target}', hive_partitioning=false)
                      ORDER BY ts_code
                    ) TO '{damaged}' (FORMAT PARQUET)
                    """
                )
            os.replace(damaged, target)

            scoped_plan = plan_qfq_nineturn_scoped_rebuild(
                lake_root=root,
                duckdb_resource=resource,
                asset_family="daily",
                stock_codes=("000001.SZ",),
                start_date=target_date,
                end_date=target_date,
                output_dir=root / "reports",
            )
            report = rebuild_qfq_nineturn_scope(
                plan=scoped_plan,
                expected_plan_fingerprint=scoped_plan.plan_fingerprint,
                duckdb_resource=resource,
                output_dir=root / "reports",
            )

            self.assertEqual(report.replaced_partition_count, 1)
            self.assertTrue(report.backup_manifest_path.is_file())
            with duckdb.connect() as connection:
                selected_close = connection.execute(
                    f"""
                    SELECT close_qfq
                    FROM read_parquet('{target}', hive_partitioning=false)
                    WHERE ts_code = '000001.SZ'
                    """
                ).fetchone()[0]
                after_other = connection.execute(
                    f"""
                    SELECT * FROM read_parquet('{target}', hive_partitioning=false)
                    WHERE ts_code = '000002.SZ'
                    """
                ).fetchone()
            self.assertNotEqual(selected_close, 999.0)
            self.assertEqual(after_other, before_other)

    def test_duplicate_source_stops_plan(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dates = build_qfq_nineturn_history_fixture(root)
            source = (
                root
                / "gold"
                / "quote"
                / "stock_daily_qfq"
                / f"trade_date={dates[0]}"
                / "part-000.parquet"
            )
            replacement = root / "duplicate.parquet"
            with duckdb.connect() as connection:
                connection.execute(
                    f"""
                    COPY (
                      SELECT * FROM read_parquet('{source}', hive_partitioning=false)
                      UNION ALL
                      SELECT * FROM read_parquet('{source}', hive_partitioning=false)
                    ) TO '{replacement}' (FORMAT PARQUET)
                    """
                )
            os.replace(replacement, source)

            plan = plan_qfq_nineturn_history(
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                output_dir=root / "reports",
            )
            self.assertTrue(plan.should_stop)
            self.assertTrue(
                any("source_contract_failed" in reason for reason in plan.stop_reasons)
            )

    def test_scoped_rebuild_requires_fresh_scope_fingerprint(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dates = build_qfq_nineturn_history_fixture(root)
            resource = DuckDBResource()
            history_plan = plan_qfq_nineturn_history(
                lake_root=root,
                duckdb_resource=resource,
                output_dir=root / "reports",
            )
            build_qfq_nineturn_history(
                plan=history_plan,
                expected_plan_fingerprint=history_plan.plan_fingerprint,
                duckdb_resource=resource,
                output_dir=root / "reports",
            )
            scoped_plan = plan_qfq_nineturn_scoped_rebuild(
                lake_root=root,
                duckdb_resource=resource,
                asset_family="daily",
                stock_codes=("000001.SZ",),
                start_date=dates[-1],
                end_date=dates[-1],
                output_dir=root / "reports",
            )
            target = gold_stock_daily_qfq_nineturn_path(root, dates[-1])
            stat = target.stat()
            os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))

            with self.assertRaisesRegex(QfqNineturnHistoryError, "stale"):
                rebuild_qfq_nineturn_scope(
                    plan=scoped_plan,
                    expected_plan_fingerprint=scoped_plan.plan_fingerprint,
                    duckdb_resource=resource,
                    output_dir=root / "reports",
                )


def _full_history_difference_count(
    connection,
    *,
    expected_sql: str,
    target_paths: tuple[Path, ...],
) -> int:
    paths = ", ".join(f"'{path}'" for path in target_paths)
    actual_sql = (
        f"SELECT * FROM read_parquet([{paths}], "
        "hive_partitioning=false, union_by_name=true)"
    )
    expected_relation = f"SELECT * FROM ({expected_sql})"
    return int(
        connection.execute(
            f"""
            SELECT count(*) FROM (
              ({expected_relation} EXCEPT ALL {actual_sql})
              UNION ALL
              ({actual_sql} EXCEPT ALL {expected_relation})
            )
            """
        ).fetchone()[0]
    )


if __name__ == "__main__":
    unittest.main()
