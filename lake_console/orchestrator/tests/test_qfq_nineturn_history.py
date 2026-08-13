from __future__ import annotations

import json
import os
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.bootstrap.qfq_nineturn_history import (
    QfqNineturnHistoryError,
    _normalize_partitioned_batch,
    _spec_for_asset,
    _validated_staging_root,
    _write_compact_history_state,
    build_qfq_nineturn_history,
    load_qfq_nineturn_history_plan,
    plan_qfq_nineturn_history,
    plan_qfq_nineturn_scoped_rebuild,
    rebuild_qfq_nineturn_scope,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
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
    def test_formal_lake_rejects_staging_below_lake_root(self) -> None:
        with self.assertRaisesRegex(
            QfqNineturnHistoryError,
            "fixed data_lake_staging root",
        ):
            _validated_staging_root(
                lake_root=Path(DEFAULT_LAKE_ROOT),
                staging_root=Path(DEFAULT_LAKE_ROOT) / "_staging",
            )

    def test_scoped_rebuild_batch_limit_cannot_exceed_twenty(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(
                QfqNineturnHistoryError,
                "between 1 and 20",
            ):
                plan_qfq_nineturn_scoped_rebuild(
                    lake_root=root,
                    staging_root=root / "staging",
                    duckdb_resource=DuckDBResource(),
                    asset_family="daily",
                    stock_codes=("000001.SZ",),
                    start_date="2026-08-11",
                    end_date="2026-08-12",
                    batch_partition_limit=21,
                    output_dir=root / "reports",
                )

    def test_compact_history_state_carries_seed_for_code_absent_in_current_year(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            context_path = root / "previous_context.parquet"
            seed_path = root / "previous_seed.parquet"
            source_path = root / "current_source.parquet"
            with duckdb.connect() as connection:
                connection.execute(
                    f"""
                    COPY (
                      SELECT * FROM (VALUES
                        ('000001.SZ', NULL::INTEGER, DATE '2024-12-26', NULL::TIMESTAMP,
                         TIMESTAMP '2024-12-26', 6.0),
                        ('000001.SZ', NULL::INTEGER, DATE '2024-12-27', NULL::TIMESTAMP,
                         TIMESTAMP '2024-12-27', 7.0),
                        ('000001.SZ', NULL::INTEGER, DATE '2024-12-30', NULL::TIMESTAMP,
                         TIMESTAMP '2024-12-30', 8.0),
                        ('000001.SZ', NULL::INTEGER, DATE '2024-12-31', NULL::TIMESTAMP,
                         TIMESTAMP '2024-12-31', 9.0),
                        ('000002.SZ', NULL::INTEGER, DATE '2024-12-31', NULL::TIMESTAMP,
                         TIMESTAMP '2024-12-31', 20.0)
                      ) rows(ts_code, freq, trade_date, trade_time, bar_time, close_qfq)
                    ) TO '{context_path}' (FORMAT PARQUET)
                    """
                )
                connection.execute(
                    f"""
                    COPY (
                      SELECT * FROM (VALUES
                        ('000001.SZ', 1, 8),
                        ('000002.SZ', -1, 3)
                      ) rows(ts_code, seed_direction, seed_count)
                    ) TO '{seed_path}' (FORMAT PARQUET)
                    """
                )
                connection.execute(
                    f"""
                    COPY (
                      SELECT '000002.SZ'::VARCHAR AS ts_code,
                             DATE '2025-01-02' AS trade_date,
                             19.0::DOUBLE AS close
                    ) TO '{source_path}' (FORMAT PARQUET)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE current_output AS
                    SELECT '000002.SZ'::VARCHAR AS ts_code,
                           DATE '2025-01-02' AS trade_date,
                           19.0::DOUBLE AS close_qfq,
                           0::INTEGER AS up_count,
                           4::INTEGER AS down_count,
                           NULL::VARCHAR AS nine_up_turn,
                           NULL::VARCHAR AS nine_down_turn
                    """
                )

                next_context, next_seed, context_rows, seed_rows = (
                    _write_compact_history_state(
                        connection,
                        table_name="current_output",
                        source_paths=(source_path,),
                        context_path=context_path,
                        seed_path=seed_path,
                        spec=_spec_for_asset("gold_stock_daily_qfq_nineturn"),
                        state_root=root / "state",
                        year=2025,
                    )
                )
                seeds = connection.execute(
                    f"""
                    SELECT ts_code, seed_direction, seed_count
                    FROM read_parquet('{next_seed}')
                    ORDER BY ts_code
                    """
                ).fetchall()
                context_codes = connection.execute(
                    f"SELECT DISTINCT ts_code FROM read_parquet('{next_context}') ORDER BY ts_code"
                ).fetchall()

            self.assertEqual(context_rows, 6)
            self.assertEqual(seed_rows, 2)
            self.assertEqual(seeds, [("000001.SZ", 1, 8), ("000002.SZ", -1, 4)])
            self.assertEqual(context_codes, [("000001.SZ",), ("000002.SZ",)])

    def test_normalize_partitioned_batch_merges_multiple_shards(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            trade_date = "2026-08-07"
            source_dir = root / "partitioned" / f"partition_trade_date={trade_date}"
            source_dir.mkdir(parents=True)
            normalized_root = root / "normalized"
            with duckdb.connect() as connection:
                for shard, ts_code in enumerate(("000002.SZ", "000001.SZ")):
                    connection.execute(
                        f"""
                        COPY (
                          SELECT
                            CAST('{ts_code}' AS VARCHAR) AS ts_code,
                            DATE '{trade_date}' AS trade_date,
                            CAST(10.0 + {shard} AS DOUBLE) AS close_qfq,
                            CAST({shard + 1} AS INTEGER) AS up_count,
                            CAST(0 AS INTEGER) AS down_count,
                            CAST(NULL AS VARCHAR) AS nine_up_turn,
                            CAST(NULL AS VARCHAR) AS nine_down_turn
                        ) TO '{source_dir / f"shard-{shard}.parquet"}' (FORMAT PARQUET)
                        """
                    )

                normalized = _normalize_partitioned_batch(
                    connection=connection,
                    partitioned_root=root / "partitioned",
                    normalized_root=normalized_root,
                    expected_dates=(trade_date,),
                    spec=_spec_for_asset("gold_stock_daily_qfq_nineturn"),
                )
                target = normalized[trade_date]
                rows = connection.execute(
                    f"SELECT ts_code, trade_date FROM read_parquet('{target}')"
                ).fetchall()
                columns = tuple(
                    row[0]
                    for row in connection.execute(
                        f"DESCRIBE SELECT * FROM read_parquet('{target}')"
                    ).fetchall()
                )

            self.assertEqual(tuple(target.parent.glob("*.parquet")), (target,))
            self.assertEqual(
                rows,
                [("000001.SZ", date(2026, 8, 7)), ("000002.SZ", date(2026, 8, 7))],
            )
            self.assertEqual(
                columns,
                tuple(
                    column.name
                    for column in _spec_for_asset(
                        "gold_stock_daily_qfq_nineturn"
                    ).schema
                ),
            )

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
            self.assertEqual(
                plan.report["performance"]["historical_rescan_multiplier"], 1
            )
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
                staging_root=root / "staging",
                output_dir=root / "reports",
            )

            self.assertEqual(report.promoted_file_count, len(dates) * 5)
            first_new_year_date = next(
                value for value in dates if value.startswith("2026-")
            )
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
                        (root / "gold" / "quote" / "stock_daily_qfq").glob(
                            "trade_date=*/part-000.parquet"
                        )
                    )
                )
                daily_target_paths = tuple(
                    gold_stock_daily_qfq_nineturn_path(root, value) for value in dates
                )
                minute_source_paths = tuple(
                    sorted(
                        (root / "gold" / "quote" / "stk_mins_qfq" / "freq=30").glob(
                            "ts_code=*/year=*/part-000.parquet"
                        )
                    )
                )
                minute_target_paths = tuple(
                    gold_stk_mins_qfq_nineturn_path(root, 30, value) for value in dates
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
                staging_root=root / "staging",
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
                    staging_root=root / "staging",
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
                staging_root=root / "staging",
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
                staging_root=root / "staging",
                duckdb_resource=resource,
                asset_family="daily",
                stock_codes=("000001.SZ",),
                start_date=target_date,
                end_date=target_date,
                output_dir=root / "reports",
            )
            scoped_history_plan = load_qfq_nineturn_history_plan(
                scoped_plan.history_plan_path
            )
            self.assertEqual(
                {batch.asset_key for batch in scoped_history_plan.batches},
                {"gold_stock_daily_qfq_nineturn"},
            )
            report = rebuild_qfq_nineturn_scope(
                plan=scoped_plan,
                expected_plan_fingerprint=scoped_plan.plan_fingerprint,
                duckdb_resource=resource,
                checkpoint_path=root / "staging" / "scoped-checkpoint.json",
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

    def test_scoped_rebuild_batches_checkpoint_and_resumes(self) -> None:
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
                staging_root=root / "staging",
                output_dir=root / "reports",
            )
            repair_dates = dates[-2:]
            for trade_date in repair_dates:
                _damage_daily_close(root, trade_date, "000001.SZ")
            scoped_plan = plan_qfq_nineturn_scoped_rebuild(
                lake_root=root,
                staging_root=root / "staging",
                duckdb_resource=resource,
                asset_family="daily",
                stock_codes=("000001.SZ",),
                start_date=repair_dates[0],
                end_date=repair_dates[-1],
                batch_partition_limit=1,
                output_dir=root / "reports",
            )
            checkpoint_path = root / "staging" / "scoped-checkpoint.json"

            first = rebuild_qfq_nineturn_scope(
                plan=scoped_plan,
                expected_plan_fingerprint=scoped_plan.plan_fingerprint,
                duckdb_resource=resource,
                checkpoint_path=checkpoint_path,
                output_dir=root / "reports",
            )
            second = rebuild_qfq_nineturn_scope(
                plan=scoped_plan,
                expected_plan_fingerprint=scoped_plan.plan_fingerprint,
                duckdb_resource=resource,
                checkpoint_path=checkpoint_path,
                output_dir=root / "reports",
            )

            self.assertEqual(first.replaced_partition_count, 1)
            self.assertEqual(first.remaining_partition_count, 1)
            self.assertEqual(second.replaced_partition_count, 1)
            self.assertEqual(second.remaining_partition_count, 0)
            self.assertEqual(len(second.resumed_partition_keys), 1)
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["completed_partition_count"], 2)

    def test_scoped_rebuild_sample_rejects_more_than_three_partitions(self) -> None:
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
                staging_root=root / "staging",
                output_dir=root / "reports",
            )
            scoped_plan = plan_qfq_nineturn_scoped_rebuild(
                lake_root=root,
                staging_root=root / "staging",
                duckdb_resource=resource,
                asset_family="daily",
                stock_codes=("000001.SZ",),
                start_date=dates[-4],
                end_date=dates[-1],
                output_dir=root / "reports",
            )
            sample_keys = tuple(
                f"gold_stock_daily_qfq_nineturn@{trade_date}"
                for trade_date in dates[-4:]
            )

            with self.assertRaisesRegex(
                QfqNineturnHistoryError,
                "one to three explicit partitions",
            ):
                rebuild_qfq_nineturn_scope(
                    plan=scoped_plan,
                    expected_plan_fingerprint=scoped_plan.plan_fingerprint,
                    duckdb_resource=resource,
                    checkpoint_path=root / "staging" / "scoped-checkpoint.json",
                    mode="sample",
                    sample_partition_keys=sample_keys,
                    output_dir=root / "reports",
                )

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
                staging_root=root / "staging",
                output_dir=root / "reports",
            )
            scoped_plan = plan_qfq_nineturn_scoped_rebuild(
                lake_root=root,
                staging_root=root / "staging",
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
                    checkpoint_path=root / "staging" / "scoped-checkpoint.json",
                    output_dir=root / "reports",
                )


def _damage_daily_close(lake_root: Path, trade_date: str, ts_code: str) -> None:
    target = gold_stock_daily_qfq_nineturn_path(lake_root, trade_date)
    damaged = lake_root / f"damaged-{trade_date}.parquet"
    with duckdb.connect() as connection:
        connection.execute(
            f"""
            COPY (
              SELECT ts_code, trade_date,
                CASE WHEN ts_code = '{ts_code}' THEN 999.0 ELSE close_qfq END
                  AS close_qfq,
                up_count, down_count, nine_up_turn, nine_down_turn
              FROM read_parquet('{target}', hive_partitioning=false)
              ORDER BY ts_code
            ) TO '{damaged}' (FORMAT PARQUET)
            """
        )
    os.replace(damaged, target)


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
