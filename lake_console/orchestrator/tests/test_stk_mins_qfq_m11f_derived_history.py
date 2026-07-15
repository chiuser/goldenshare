from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import dagster as dg
import duckdb

from orchestrator.defs.bootstrap import stk_mins_migration_cli
from orchestrator.defs.bootstrap import (
    stk_mins_qfq_derived_bootstrap_events as derived_events,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_derived_bootstrap_events import (
    GOLD_STK_MINS_QFQ_DERIVED_ASSET_KEYS,
    GOLD_STK_MINS_QFQ_DERIVED_CHECKS,
    audit_stk_mins_qfq_derived_final_state,
    plan_stk_mins_qfq_derived_bootstrap_events,
    report_stk_mins_qfq_derived_bootstrap_events,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_derived_history import (
    generate_stk_mins_qfq_derived_history,
    plan_stk_mins_qfq_derived_history,
)
from orchestrator.defs.checks import stk_mins_checks
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import gold_stk_mins_qfq_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_SCHEMA,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    asset_readiness_status,
)


DATE_1 = "2014-06-03"
DATE_2 = "2014-06-04"
DATE_3 = "2015-06-03"
STOCK_A = "600000.SH"
STOCK_B = "000001.SZ"


def _column_types(schema) -> dict[str, str]:
    return {column.name: column.type for column in schema}


def _write_rows(
    path: Path,
    *,
    rows: list[dict[str, object]],
    order_by: str = "trade_date, trade_time",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(column.name for column in GOLD_STK_MINS_QFQ_SCHEMA)
    column_types = _column_types(GOLD_STK_MINS_QFQ_SCHEMA)
    with duckdb.connect(database=":memory:") as connection:
        column_defs = ", ".join(
            f'"{column}" {column_types[column]}' for column in columns
        )
        connection.execute(f"CREATE TEMP TABLE rows_to_write ({column_defs})")
        if rows:
            placeholders = ", ".join("?" for _column in columns)
            values = [[row.get(column) for column in columns] for row in rows]
            connection.executemany(
                f"INSERT INTO rows_to_write VALUES ({placeholders})",
                values,
            )
        select_columns = ", ".join(
            f'CAST("{column}" AS {column_types[column]}) AS "{column}"'
            for column in columns
        )
        connection.execute(
            copy_query_to_parquet(
                f"""
                SELECT {select_columns}
                FROM rows_to_write
                ORDER BY {order_by}
                """,
                path,
            )
        )


def _gold_row(
    *,
    ts_code: str,
    freq: int,
    trade_date: str,
    trade_time: str,
    open_: float,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": freq,
        "trade_date": trade_date,
        "trade_time": f"{trade_date} {trade_time}",
        "open": open_,
        "high": open_ + 1.0,
        "low": open_ - 1.0,
        "close": open_ + 0.5,
        "vol": 100.0,
        "amount": 1000.0,
        "exchange": "SSE" if ts_code.endswith(".SH") else "SZSE",
    }


def _source_times(freq: int) -> tuple[str, ...]:
    if freq == 30:
        return (
            "09:30:00",
            "10:00:00",
            "10:30:00",
            "11:00:00",
            "11:30:00",
            "13:30:00",
            "14:00:00",
            "14:30:00",
            "15:00:00",
        )
    if freq == 60:
        return ("09:30:00", "10:30:00", "11:30:00", "14:00:00", "15:00:00")
    raise ValueError(f"Unsupported test source freq: {freq}")


def _source_rows_for_stock_year(
    *,
    ts_code: str,
    freq: int,
    trade_dates: tuple[str, ...],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    base = 10.0 if ts_code == STOCK_A else 30.0
    for date_index, trade_date in enumerate(trade_dates):
        for time_index, trade_time in enumerate(_source_times(freq)):
            rows.append(
                _gold_row(
                    ts_code=ts_code,
                    freq=freq,
                    trade_date=trade_date,
                    trade_time=trade_time,
                    open_=base + date_index * 10 + time_index,
                )
            )
    return rows


def _write_source_qfq_year(
    lake_root: Path,
    *,
    freq: int,
    year: int,
    trade_dates: tuple[str, ...],
) -> None:
    for stock_code in (STOCK_A, STOCK_B):
        _write_rows(
            gold_stk_mins_qfq_path(lake_root, freq, stock_code, year),
            rows=_source_rows_for_stock_year(
                ts_code=stock_code,
                freq=freq,
                trade_dates=trade_dates,
            ),
            order_by="trade_date, ts_code, trade_time",
        )


def _write_valid_derived_sources(lake_root: Path) -> None:
    _write_source_qfq_year(
        lake_root,
        freq=30,
        year=2014,
        trade_dates=(DATE_1, DATE_2),
    )
    _write_source_qfq_year(
        lake_root,
        freq=60,
        year=2014,
        trade_dates=(DATE_1, DATE_2),
    )


def _read_gold_rows(path: Path) -> list[dict[str, object]]:
    columns = tuple(column.name for column in GOLD_STK_MINS_QFQ_SCHEMA)
    with duckdb.connect(database=":memory:") as connection:
        rows = connection.execute(
            f"""
            SELECT {", ".join(columns)}
            FROM {read_parquet(path, hive_partitioning=False)}
            ORDER BY trade_date, trade_time
            """
        ).fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


class StkMinsQfqM11FDerivedHistoryTests(unittest.TestCase):
    def test_helpers_do_not_define_active_dagster_components(self) -> None:
        helper_paths = (
            Path("src/orchestrator/defs/bootstrap/stk_mins_qfq_derived_history.py"),
            Path(
                "src/orchestrator/defs/bootstrap/"
                "stk_mins_qfq_derived_bootstrap_events.py"
            ),
        )
        for helper_path in helper_paths:
            text = helper_path.read_text()
            for token in ("@dg.asset", "@dg.asset_check", "@dg.sensor", "define_asset_job"):
                self.assertNotIn(token, text)

    def test_helpers_do_not_use_per_stock_main_loop_or_summary_entities(self) -> None:
        helper_paths = (
            Path("src/orchestrator/defs/bootstrap/stk_mins_qfq_derived_history.py"),
            Path(
                "src/orchestrator/defs/bootstrap/"
                "stk_mins_qfq_derived_bootstrap_events.py"
            ),
        )
        for helper_path in helper_paths:
            text = helper_path.read_text()
            forbidden_fragments = (
                "for stock_code in",
                "gold_stk_mins_qfq_factor_repair_summary",
                "gold_stk_mins_qfq_daily_summary",
                "define_asset_job",
                "run_tags",
            )
            for fragment in forbidden_fragments:
                self.assertNotIn(fragment, text)

    def test_plan_batches_by_target_freq_and_year_not_stock(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_derived_sources(lake_root)
            _write_source_qfq_year(
                lake_root,
                freq=30,
                year=2015,
                trade_dates=(DATE_3,),
            )
            _write_source_qfq_year(
                lake_root,
                freq=60,
                year=2015,
                trade_dates=(DATE_3,),
            )

            plan = plan_stk_mins_qfq_derived_history(
                lake_root=lake_root,
                registered_partition_keys=[DATE_1, DATE_2, DATE_3],
                freqs=[90, 120],
                duckdb_resource=DuckDBResource(),
            )

        self.assertEqual(len(plan.batches), 4)
        self.assertEqual(
            [(batch.target_freq, batch.year) for batch in plan.batches],
            [(90, "2014"), (90, "2015"), (120, "2014"), (120, "2015")],
        )
        self.assertEqual(plan.planned_event_count, 3 * 2 * 5)
        self.assertGreater(plan.planned_target_row_count, 0)

    def test_generate_writes_derived_stock_year_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_derived_sources(lake_root)

            report = generate_stk_mins_qfq_derived_history(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                registered_partition_keys=[DATE_1, DATE_2],
                freqs=[90, 120],
            )

            stock_a_90_path = gold_stk_mins_qfq_path(lake_root, 90, STOCK_A, 2014)
            stock_a_120_path = gold_stk_mins_qfq_path(lake_root, 120, STOCK_A, 2014)
            rows_90 = _read_gold_rows(stock_a_90_path)
            rows_120 = _read_gold_rows(stock_a_120_path)

        self.assertEqual(len(report.batch_results), 2)
        self.assertEqual(report.written_file_count, 4)
        self.assertEqual(report.plan.planned_event_count, 2 * 2 * 5)
        self.assertEqual(len(rows_90), 6)
        self.assertEqual(len(rows_120), 4)
        self.assertEqual([row["freq"] for row in rows_90], [90] * 6)
        self.assertEqual([row["trade_time"].strftime("%H:%M:%S") for row in rows_90[:3]], [
            "11:00:00",
            "14:00:00",
            "15:00:00",
        ])
        self.assertEqual([row["trade_time"].strftime("%H:%M:%S") for row in rows_120[:2]], [
            "10:30:00",
            "14:00:00",
        ])

    def test_generate_rejects_native_freq_and_existing_targets(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_derived_sources(lake_root)

            with self.assertRaisesRegex(ValueError, "only supports derived freqs"):
                plan_stk_mins_qfq_derived_history(
                    lake_root=lake_root,
                    registered_partition_keys=[DATE_1],
                    freqs=[30],
                    duckdb_resource=DuckDBResource(),
                )

            generate_stk_mins_qfq_derived_history(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                registered_partition_keys=[DATE_1],
                freqs=[90],
            )
            with self.assertRaisesRegex(FileExistsError, "target files already exist"):
                generate_stk_mins_qfq_derived_history(
                    lake_root=lake_root,
                    duckdb_resource=DuckDBResource(),
                    registered_partition_keys=[DATE_1],
                    freqs=[90],
                )

    def test_event_plan_and_dry_run_do_not_write_events_or_deep_check_per_partition(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_derived_sources(lake_root)
            generate_stk_mins_qfq_derived_history(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                registered_partition_keys=[DATE_1, DATE_2],
                freqs=[90],
            )
            instance = dg.DagsterInstance.ephemeral()

            plan = plan_stk_mins_qfq_derived_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                registered_partition_keys=[DATE_1, DATE_2],
                freqs=[90],
                duckdb_resource=DuckDBResource(),
            )
            with patch.object(
                stk_mins_checks,
                "_gold_stk_mins_qfq_derived_check_results",
                side_effect=AssertionError("daily derived deep audit must not run"),
            ):
                report = report_stk_mins_qfq_derived_bootstrap_events(
                    instance=instance,
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    registered_partition_keys=[DATE_1, DATE_2],
                    freqs=[90],
                    dry_run=True,
                )
            materializations = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=GOLD_STK_MINS_QFQ_DERIVED_ASSET_KEYS[90],
                    asset_partitions=[DATE_1],
                ),
                limit=1,
            ).records

        self.assertEqual(plan.asset_partition_count, 2)
        self.assertEqual(plan.planned_event_count, 10)
        self.assertTrue(report.dry_run)
        self.assertEqual(report.failed_partition_count, 0)
        self.assertEqual(report.reported_event_count, 0)
        self.assertEqual(materializations, [])

    def test_report_events_make_derived_partition_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_derived_sources(lake_root)
            generate_stk_mins_qfq_derived_history(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                registered_partition_keys=[DATE_1],
                freqs=[90],
            )
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name,
                [DATE_1],
            )

            report = report_stk_mins_qfq_derived_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                registered_partition_keys=[DATE_1],
                freqs=[90],
            )
            readiness = asset_readiness_status(
                instance,
                AssetReadinessSpec(
                    GOLD_STK_MINS_QFQ_DERIVED_ASSET_KEYS[90],
                    GOLD_STK_MINS_QFQ_DERIVED_CHECKS,
                ),
                partition_key=DATE_1,
            )
            second = report_stk_mins_qfq_derived_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                registered_partition_keys=[DATE_1],
                freqs=[90],
                skip_existing_ready=True,
            )

        self.assertEqual(report.reported_event_count, 5)
        self.assertTrue(readiness.ready)
        self.assertEqual(second.reported_event_count, 0)
        self.assertEqual(second.skipped_ready_asset_partitions, ((90, DATE_1),))

    def test_report_events_skip_check_success_counts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_derived_sources(lake_root)
            generate_stk_mins_qfq_derived_history(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                registered_partition_keys=[DATE_1],
                freqs=[90],
            )
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name,
                [DATE_1],
            )

            with patch.object(
                derived_events,
                "_check_success_count",
                side_effect=AssertionError("report path must not scan check history"),
            ):
                dry_run = report_stk_mins_qfq_derived_bootstrap_events(
                    instance=instance,
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    registered_partition_keys=[DATE_1],
                    freqs=[90],
                    dry_run=True,
                )
                report = report_stk_mins_qfq_derived_bootstrap_events(
                    instance=instance,
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    registered_partition_keys=[DATE_1],
                    freqs=[90],
                )

        self.assertEqual(dry_run.reported_event_count, 0)
        self.assertEqual(report.reported_event_count, 5)

    def test_derived_bootstrap_audit_does_not_recalculate_qfq_prices(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_derived_sources(lake_root)
            generate_stk_mins_qfq_derived_history(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                registered_partition_keys=[DATE_1],
                freqs=[90],
            )
            target_path = gold_stk_mins_qfq_path(lake_root, 90, STOCK_A, 2014)
            rows = _read_gold_rows(target_path)
            rows[0].update(open=20.0, high=21.0, low=19.0, close=20.5)
            _write_rows(target_path, rows=rows)
            instance = dg.DagsterInstance.ephemeral()

            report = report_stk_mins_qfq_derived_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                registered_partition_keys=[DATE_1],
                freqs=[90],
            )
            materializations = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=GOLD_STK_MINS_QFQ_DERIVED_ASSET_KEYS[90],
                    asset_partitions=[DATE_1],
                ),
                limit=1,
            ).records

        self.assertEqual(report.reported_event_count, 5)
        self.assertEqual(len(materializations), 1)

    def test_final_audit_uses_counts_and_sample_readiness(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_derived_sources(lake_root)
            generate_stk_mins_qfq_derived_history(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                registered_partition_keys=[DATE_1],
                freqs=[90],
            )
            instance = dg.DagsterInstance.ephemeral()
            report_stk_mins_qfq_derived_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                registered_partition_keys=[DATE_1],
                freqs=[90],
            )

            final = audit_stk_mins_qfq_derived_final_state(
                instance=instance,
                lake_root=lake_root,
                registered_partition_keys=[DATE_1],
                freqs=[90],
                duckdb_resource=DuckDBResource(),
            )

        self.assertEqual(final.selected_partition_count, 1)
        self.assertEqual(final.materialized_partition_counts, {90: 1})
        self.assertFalse(final.check_success_counts_skipped)
        self.assertTrue(final.sample_readiness[f"90:{DATE_1}"])
        self.assertEqual(
            len(final.check_success_counts),
            len(GOLD_STK_MINS_QFQ_DERIVED_CHECKS),
        )

    def test_quick_final_audit_skips_check_success_counts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_derived_sources(lake_root)
            generate_stk_mins_qfq_derived_history(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                registered_partition_keys=[DATE_1],
                freqs=[90],
            )
            instance = dg.DagsterInstance.ephemeral()
            report_stk_mins_qfq_derived_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                registered_partition_keys=[DATE_1],
                freqs=[90],
            )

            with patch.object(
                derived_events,
                "_check_success_count",
                side_effect=AssertionError("quick audit must not scan check history"),
            ):
                final = audit_stk_mins_qfq_derived_final_state(
                    instance=instance,
                    lake_root=lake_root,
                    registered_partition_keys=[DATE_1],
                    freqs=[90],
                    duckdb_resource=DuckDBResource(),
                    include_check_success_counts=False,
                )

        self.assertEqual(final.selected_partition_count, 1)
        self.assertEqual(final.materialized_partition_counts, {90: 1})
        self.assertTrue(final.check_success_counts_skipped)
        self.assertEqual(final.check_success_counts, {})
        self.assertTrue(final.sample_readiness[f"90:{DATE_1}"])

    def test_cli_derived_plan_generate_report_and_audit_commands(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_derived_sources(lake_root)
            instance = dg.DagsterInstance.ephemeral()
            buffer = io.StringIO()

            with patch.object(
                dg.DagsterInstance,
                "get",
                return_value=instance,
            ), patch.object(
                stk_mins_migration_cli,
                "_registered_stock_mins_silver_partition_keys",
                return_value=(DATE_1,),
            ), contextlib.redirect_stdout(buffer):
                stk_mins_migration_cli.main(
                    [
                        "plan-gold-qfq-derived-history",
                        "--lake-root",
                        str(lake_root),
                        "--partition-keys",
                        DATE_1,
                        "--freqs",
                        "90",
                    ]
                )
                stk_mins_migration_cli.main(
                    [
                        "generate-gold-qfq-derived-history",
                        "--lake-root",
                        str(lake_root),
                        "--partition-keys",
                        DATE_1,
                        "--freqs",
                        "90",
                    ]
                )
                stk_mins_migration_cli.main(
                    [
                        "plan-gold-qfq-derived-events",
                        "--lake-root",
                        str(lake_root),
                        "--partition-keys",
                        DATE_1,
                        "--freqs",
                        "90",
                    ]
                )
                stk_mins_migration_cli.main(
                    [
                        "report-gold-qfq-derived-events",
                        "--lake-root",
                        str(lake_root),
                        "--partition-keys",
                        DATE_1,
                        "--freqs",
                        "90",
                    ]
                )
                stk_mins_migration_cli.main(
                    [
                        "audit-gold-qfq-derived-final",
                        "--lake-root",
                        str(lake_root),
                        "--partition-keys",
                        DATE_1,
                        "--freqs",
                        "90",
                    ]
                )
                stk_mins_migration_cli.main(
                    [
                        "audit-gold-qfq-derived-final",
                        "--lake-root",
                        str(lake_root),
                        "--partition-keys",
                        DATE_1,
                        "--freqs",
                        "90",
                        "--mode",
                        "quick",
                    ]
                )

        output = buffer.getvalue()
        self.assertIn("'selected_target_freqs': [90]", output)
        self.assertIn("'reported_event_count': 5", output)
        self.assertIn("'audit_mode': 'full'", output)
        self.assertIn("'check_success_counts_skipped': False", output)
        self.assertIn("'audit_mode': 'quick'", output)
        self.assertIn("'check_success_counts_skipped': True", output)
        self.assertIn("'check_success_counts': {}", output)
        self.assertIn("'sample_readiness': {'90:2014-06-03': True}", output)


if __name__ == "__main__":
    unittest.main()
