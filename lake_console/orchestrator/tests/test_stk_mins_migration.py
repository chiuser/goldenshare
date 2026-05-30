import tempfile
import unittest
from pathlib import Path

import dagster as dg
import duckdb

from orchestrator.defs.bootstrap.stk_mins_migration import (
    RAW_STK_MINS_ASSET_KEYS,
    RAW_STK_MINS_CHECKS,
    SILVER_STOCK_IDENTITY_MAP_ASSET_KEY,
    SILVER_STOCK_IDENTITY_MAP_CHECKS,
    audit_stk_mins_raw_partition,
    migrate_stk_mins_raw_history,
    migrate_stock_identity_map_snapshot,
    plan_stk_mins_migration,
    register_stock_mins_partitions,
    report_stk_mins_raw_bootstrap_events,
    report_stock_identity_map_bootstrap_events,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.partitions import cn_a_stock_mins_trade_days
from orchestrator.defs.paths import raw_stk_mins_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    asset_readiness_status,
)


PARTITION_KEY = "2026-05-07"


def _sql_string(value: str) -> str:
    return f"{duckdb_string(value)}::VARCHAR"


def _write_backup_stk_mins_file(
    backup_root: Path,
    *,
    freq: int,
    partition_key: str = PARTITION_KEY,
    file_name: str = "part-00000.parquet",
    include_rows: bool = True,
) -> Path:
    path = backup_root / f"freq={freq}" / f"trade_date={partition_key}" / file_name
    path.parent.mkdir(parents=True, exist_ok=True)
    where_clause = "" if include_rows else "WHERE false"
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                '000001.SZ'::VARCHAR AS ts_code,
                {freq}::BIGINT AS freq,
                TIMESTAMP '2026-05-07 09:30:00' AS trade_time,
                10.0::DOUBLE AS open,
                10.1::DOUBLE AS close,
                10.2::DOUBLE AS high,
                9.9::DOUBLE AS low,
                100::BIGINT AS vol,
                1000.0::DOUBLE AS amount,
                NULL AS exchange,
                10.05::DOUBLE AS vwap
              {where_clause}
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )
    return path


def _write_all_freq_backup(
    backup_root: Path,
    partition_key: str = PARTITION_KEY,
) -> None:
    for freq in STK_MINS_FREQS:
        _write_backup_stk_mins_file(
            backup_root,
            freq=freq,
            partition_key=partition_key,
        )


def _write_stock_identity_source(old_lake_root: Path) -> Path:
    path = (
        old_lake_root
        / "manifest"
        / "security_identity"
        / "security_identity_map.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                '001872.SZ'::VARCHAR AS latest_ts_code,
                '000022.SZ'::VARCHAR AS source_ts_code,
                DATE '1993-04-30' AS valid_from,
                NULL::DATE AS valid_to,
                DATE '1993-04-30' AS effective_list_date,
                NULL::DATE AS effective_delist_date,
                'namechange'::VARCHAR AS identity_source,
                'inferred'::VARCHAR AS confidence,
                '代码变更映射'::VARCHAR AS reason,
                TIMESTAMPTZ '2026-05-12 10:00:00+08' AS created_at
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )
    return path


class StkMinsMigrationTests(unittest.TestCase):
    def test_plan_is_read_only_and_reports_expected_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = root / "data_lake"
            backup_root = root / "backup"
            old_lake_root = root / "old_lake"
            _write_all_freq_backup(backup_root)
            _write_stock_identity_source(old_lake_root)

            plan = plan_stk_mins_migration(
                lake_root=lake_root,
                backup_root=backup_root,
                old_lake_root=old_lake_root,
            )

        self.assertEqual(plan.partition_keys, (PARTITION_KEY,))
        self.assertEqual(dict(plan.backup_partition_counts), {freq: 1 for freq in STK_MINS_FREQS})
        self.assertEqual(dict(plan.target_existing_counts), {freq: 0 for freq in STK_MINS_FREQS})
        self.assertEqual(plan.planned_raw_file_count, len(STK_MINS_FREQS))
        self.assertGreater(plan.backup_file_size_bytes, 0)
        self.assertGreater(plan.target_filesystem_free_bytes, 0)
        self.assertEqual(
            plan.planned_raw_event_count,
            len(STK_MINS_FREQS) * (1 + len(RAW_STK_MINS_CHECKS)),
        )
        self.assertTrue(plan.identity_map_source_exists)
        self.assertFalse(plan.identity_map_target_exists)

    def test_migrates_raw_history_and_skips_existing_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = root / "data_lake"
            backup_root = root / "backup"
            _write_all_freq_backup(backup_root)

            first = migrate_stk_mins_raw_history(
                lake_root=lake_root,
                backup_root=backup_root,
                partition_keys=[PARTITION_KEY],
                duckdb=DuckDBResource(),
            )
            second = migrate_stk_mins_raw_history(
                lake_root=lake_root,
                backup_root=backup_root,
                partition_keys=[PARTITION_KEY],
                duckdb=DuckDBResource(),
                skip_existing=True,
            )

        self.assertEqual(len(first.written_files), len(STK_MINS_FREQS))
        self.assertTrue(all(path.name == "part-000.parquet" for path in first.written_files))
        self.assertEqual(second.written_files, ())
        self.assertEqual(len(second.skipped_existing_files), len(STK_MINS_FREQS))

    def test_migration_requires_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(FileNotFoundError, "No stk_mins backup parquet"):
                migrate_stk_mins_raw_history(
                    lake_root=root / "data_lake",
                    backup_root=root / "backup",
                    partition_keys=[PARTITION_KEY],
                    duckdb=DuckDBResource(),
                )

    def test_registers_only_missing_stock_mins_partitions(self) -> None:
        instance = dg.DagsterInstance.ephemeral()
        instance.add_dynamic_partitions(cn_a_stock_mins_trade_days.name, ["2026-05-06"])

        report = register_stock_mins_partitions(
            instance=instance,
            partition_keys=["2026-05-06", PARTITION_KEY, PARTITION_KEY],
        )

        self.assertEqual(report.requested_partition_keys, ("2026-05-06", PARTITION_KEY))
        self.assertEqual(report.existing_partition_keys, ("2026-05-06",))
        self.assertEqual(report.registered_partition_keys, (PARTITION_KEY,))
        self.assertEqual(
            set(instance.get_dynamic_partitions(cn_a_stock_mins_trade_days.name)),
            {"2026-05-06", PARTITION_KEY},
        )

    def test_reports_runless_raw_events_and_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = root / "data_lake"
            backup_root = root / "backup"
            _write_all_freq_backup(backup_root)
            migrate_stk_mins_raw_history(
                lake_root=lake_root,
                backup_root=backup_root,
                partition_keys=[PARTITION_KEY],
                duckdb=DuckDBResource(),
            )
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_trade_days.name,
                [PARTITION_KEY],
            )

            report = report_stk_mins_raw_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                partition_keys=[PARTITION_KEY],
                dry_run=False,
            )
            readiness_by_freq = {
                freq: asset_readiness_status(
                    instance,
                    AssetReadinessSpec(RAW_STK_MINS_ASSET_KEYS[freq], RAW_STK_MINS_CHECKS),
                    partition_key=PARTITION_KEY,
                )
                for freq in STK_MINS_FREQS
            }

        self.assertEqual(report.failed_audit_count, 0)
        self.assertEqual(
            report.reported_event_count,
            len(STK_MINS_FREQS) * (1 + len(RAW_STK_MINS_CHECKS)),
        )
        self.assertTrue(all(status.ready for status in readiness_by_freq.values()))

    def test_raw_event_dry_run_does_not_write_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = root / "data_lake"
            backup_root = root / "backup"
            _write_all_freq_backup(backup_root)
            migrate_stk_mins_raw_history(
                lake_root=lake_root,
                backup_root=backup_root,
                partition_keys=[PARTITION_KEY],
                duckdb=DuckDBResource(),
            )
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_trade_days.name,
                [PARTITION_KEY],
            )

            report = report_stk_mins_raw_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                partition_keys=[PARTITION_KEY],
                dry_run=True,
            )
            materializations = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=RAW_STK_MINS_ASSET_KEYS[1],
                    asset_partitions=[PARTITION_KEY],
                ),
                limit=1,
            ).records

        self.assertTrue(report.dry_run)
        self.assertEqual(report.reported_event_count, 0)
        self.assertEqual(materializations, [])

    def test_failed_raw_audit_blocks_event_reporting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = root / "data_lake"
            for freq in STK_MINS_FREQS:
                raw_path = raw_stk_mins_path(lake_root, freq, PARTITION_KEY)
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                with duckdb.connect(database=":memory:") as connection:
                    connection.execute(
                        f"""
                        COPY (
                          SELECT *
                          FROM (
                            VALUES
                              (
                                '000001.SZ'::VARCHAR,
                                {freq}::INTEGER,
                                TIMESTAMP '2026-05-07 09:30:00',
                                10.0::DOUBLE,
                                10.1::DOUBLE,
                                10.2::DOUBLE,
                                9.9::DOUBLE,
                                100::BIGINT,
                                1000.0::DOUBLE,
                                NULL::VARCHAR,
                                10.05::DOUBLE
                              )
                          ) rows(
                            ts_code, freq, trade_time, open, close, high, low,
                            vol, amount, exchange, vwap
                          )
                        ) TO {duckdb_string(raw_path)} (FORMAT PARQUET)
                        """
                    )
            instance = dg.DagsterInstance.ephemeral()

            with self.assertRaisesRegex(ValueError, "bootstrap audit failed"):
                report_stk_mins_raw_bootstrap_events(
                    instance=instance,
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    partition_keys=[PARTITION_KEY],
                    dry_run=False,
                )

    def test_raw_price_sanity_allows_legacy_zero_low(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = root / "data_lake"
            raw_path = raw_stk_mins_path(lake_root, 1, PARTITION_KEY)
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(database=":memory:") as connection:
                connection.execute(
                    f"""
                    COPY (
                      SELECT
                        '600515.SH'::VARCHAR AS ts_code,
                        1::INTEGER AS freq,
                        TIMESTAMP '2026-05-07 09:32:00' AS trade_time,
                        5.83::DOUBLE AS open,
                        5.83::DOUBLE AS close,
                        5.83::DOUBLE AS high,
                        0.0::DOUBLE AS low,
                        10000::BIGINT AS vol,
                        58300.0::DOUBLE AS amount,
                        NULL::VARCHAR AS exchange,
                        5.83::DOUBLE AS vwap
                    ) TO {duckdb_string(raw_path)} (FORMAT PARQUET)
                    """
                )

            audit = audit_stk_mins_raw_partition(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                freq=1,
                partition_key=PARTITION_KEY,
                registered_partition_keys={PARTITION_KEY},
            )

        self.assertTrue(audit.passed)

    def test_raw_price_sanity_allows_legacy_zero_quote_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = root / "data_lake"
            raw_path = raw_stk_mins_path(lake_root, 5, PARTITION_KEY)
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(database=":memory:") as connection:
                connection.execute(
                    f"""
                    COPY (
                      SELECT
                        '000007.SZ'::VARCHAR AS ts_code,
                        5::INTEGER AS freq,
                        TIMESTAMP '2026-05-07 09:35:00' AS trade_time,
                        0.0::DOUBLE AS open,
                        0.0::DOUBLE AS close,
                        0.0::DOUBLE AS high,
                        0.0::DOUBLE AS low,
                        0::BIGINT AS vol,
                        0.0::DOUBLE AS amount,
                        NULL::VARCHAR AS exchange,
                        0.0::DOUBLE AS vwap
                    ) TO {duckdb_string(raw_path)} (FORMAT PARQUET)
                    """
                )

            audit = audit_stk_mins_raw_partition(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                freq=5,
                partition_key=PARTITION_KEY,
                registered_partition_keys={PARTITION_KEY},
            )

        self.assertTrue(audit.passed)

    def test_reports_identity_map_events_and_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = root / "data_lake"
            old_lake_root = root / "old_lake"
            _write_stock_identity_source(old_lake_root)
            migrate_stock_identity_map_snapshot(
                lake_root=lake_root,
                old_lake_root=old_lake_root,
                duckdb=DuckDBResource(),
            )
            instance = dg.DagsterInstance.ephemeral()

            report = report_stock_identity_map_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                dry_run=False,
            )
            readiness = asset_readiness_status(
                instance,
                AssetReadinessSpec(
                    SILVER_STOCK_IDENTITY_MAP_ASSET_KEY,
                    SILVER_STOCK_IDENTITY_MAP_CHECKS,
                ),
            )

        self.assertEqual(report.reported_event_count, 1 + len(SILVER_STOCK_IDENTITY_MAP_CHECKS))
        self.assertFalse(report.skipped_ready)
        self.assertTrue(readiness.ready)


if __name__ == "__main__":
    unittest.main()
