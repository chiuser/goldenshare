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
from orchestrator.defs.bootstrap.stk_mins_qfq_bootstrap_events import (
    GOLD_STK_MINS_QFQ_ASSET_KEYS,
    GOLD_STK_MINS_QFQ_CHECKS,
    audit_stk_mins_qfq_final_state,
    plan_stk_mins_qfq_bootstrap_events,
    report_stk_mins_qfq_bootstrap_events,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_history import (
    generate_stk_mins_qfq_history,
)
from orchestrator.defs.checks import stk_mins_checks
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_STK_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    expected_canonical_gold_source_times,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    asset_readiness_status,
)
from orchestrator.defs.stk_mins_qfq import gold_stk_mins_qfq_source_freq

DATE_1 = "2014-06-03"
DATE_2 = "2014-06-04"
DATE_3 = "2015-06-03"
STOCK_A = "600000.SH"
STOCK_B = "000001.SZ"
FREQ = 5


def _column_types(schema) -> dict[str, str]:
    return {column.name: column.type for column in schema}


def _write_rows(
    path: Path,
    *,
    schema,
    rows: list[dict[str, object]],
    order_by: str = "1",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(column.name for column in schema)
    column_types = _column_types(schema)
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


def _silver_row(
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
        "trade_time": trade_time,
        "open": open_,
        "high": open_ + 1.0,
        "low": open_ - 1.0,
        "close": open_ + 0.5,
        "vol": 100.0,
        "amount": 1000.0,
        "exchange": "SSE" if ts_code.endswith(".SH") else "SZSE",
    }


def _adj_row(ts_code: str, trade_date: str, adj_factor: float) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "adj_factor": adj_factor,
    }


def _write_silver_partition(lake_root: Path, trade_date: str) -> None:
    source_freq = gold_stk_mins_qfq_source_freq(FREQ)
    source_times = expected_canonical_gold_source_times(FREQ)
    _write_rows(
        silver_stk_mins_path(lake_root, source_freq, trade_date),
        schema=SILVER_STK_MINS_SCHEMA,
        rows=[
            _silver_row(
                ts_code=stock_code,
                freq=source_freq,
                trade_date=trade_date,
                trade_time=f"{trade_date} {trade_time}",
                open_=open_base,
            )
            for stock_code, open_base in ((STOCK_A, 10.0), (STOCK_B, 30.0))
            for trade_time in source_times
        ],
        order_by="ts_code, trade_time",
    )


def _write_adj_partition(lake_root: Path, trade_date: str) -> None:
    _write_rows(
        silver_adj_factor_path(lake_root, trade_date),
        schema=SILVER_ADJ_FACTOR_SCHEMA,
        rows=[
            _adj_row(STOCK_A, trade_date, 2.0 if trade_date == DATE_1 else 4.0),
            _adj_row(STOCK_B, trade_date, 3.0 if trade_date == DATE_1 else 6.0),
        ],
        order_by="ts_code",
    )


def _write_valid_gold_inputs(lake_root: Path) -> None:
    _write_silver_partition(lake_root, DATE_1)
    _write_silver_partition(lake_root, DATE_2)
    _write_adj_partition(lake_root, DATE_1)
    _write_adj_partition(lake_root, DATE_2)
    generate_stk_mins_qfq_history(
        lake_root=lake_root,
        duckdb_resource=DuckDBResource(),
        registered_partition_keys=[DATE_1, DATE_2],
        freqs=[FREQ],
    )


class StkMinsQfqM8DEventTests(unittest.TestCase):
    def test_m8d_helper_does_not_define_active_dagster_components(self) -> None:
        helper_path = Path(
            "src/orchestrator/defs/bootstrap/stk_mins_qfq_bootstrap_events.py"
        )
        text = helper_path.read_text()
        for token in ("@dg.asset", "@dg.asset_check", "@dg.sensor", "define_asset_job"):
            self.assertNotIn(token, text)

    def test_plan_is_aggregate_and_does_not_write_events(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_gold_inputs(lake_root)
            instance = dg.DagsterInstance.ephemeral()

            plan = plan_stk_mins_qfq_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                registered_partition_keys=[DATE_1, DATE_2],
                freqs=[FREQ],
                duckdb_resource=DuckDBResource(),
            )
            materializations = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=GOLD_STK_MINS_QFQ_ASSET_KEYS[FREQ],
                    asset_partitions=[DATE_1],
                ),
                limit=1,
            ).records

        self.assertEqual(plan.asset_partition_count, 2)
        self.assertEqual(plan.planned_event_count, 10)
        self.assertEqual(plan.missing_input_count, 0)
        self.assertEqual(plan.existing_target_file_count, plan.planned_target_file_count)
        self.assertEqual(materializations, [])

    def test_report_dry_run_audits_without_writing_events(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_gold_inputs(lake_root)
            instance = dg.DagsterInstance.ephemeral()

            report = report_stk_mins_qfq_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                registered_partition_keys=[DATE_1, DATE_2],
                partition_keys=[DATE_1],
                freqs=[FREQ],
                dry_run=True,
            )
            materializations = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=GOLD_STK_MINS_QFQ_ASSET_KEYS[FREQ],
                    asset_partitions=[DATE_1],
                ),
                limit=1,
            ).records

        self.assertTrue(report.dry_run)
        self.assertEqual(report.failed_partition_count, 0)
        self.assertEqual(len(report.partition_audits), 1)
        self.assertEqual(report.reported_event_count, 0)
        self.assertEqual(materializations, [])

    def test_report_uses_year_batch_audit_not_daily_check_loop(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_gold_inputs(lake_root)
            instance = dg.DagsterInstance.ephemeral()

            with patch.object(
                stk_mins_checks,
                "_gold_stk_mins_qfq_check_results",
                side_effect=AssertionError("daily deep audit must not be called"),
            ):
                report = report_stk_mins_qfq_bootstrap_events(
                    instance=instance,
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    registered_partition_keys=[DATE_1, DATE_2],
                    freqs=[FREQ],
                    dry_run=True,
                )

        self.assertEqual(len(report.partition_audits), 2)
        self.assertEqual(report.failed_partition_count, 0)

    def test_report_events_make_gold_qfq_partition_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_gold_inputs(lake_root)
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name,
                [DATE_1],
            )

            report = report_stk_mins_qfq_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                registered_partition_keys=[DATE_1, DATE_2],
                partition_keys=[DATE_1],
                freqs=[FREQ],
            )
            readiness = asset_readiness_status(
                instance,
                AssetReadinessSpec(
                    GOLD_STK_MINS_QFQ_ASSET_KEYS[FREQ],
                    GOLD_STK_MINS_QFQ_CHECKS,
                ),
                partition_key=DATE_1,
            )
            second = report_stk_mins_qfq_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                registered_partition_keys=[DATE_1, DATE_2],
                partition_keys=[DATE_1],
                freqs=[FREQ],
                skip_existing_ready=True,
            )

        self.assertEqual(report.reported_event_count, 5)
        self.assertTrue(readiness.ready)
        self.assertEqual(second.reported_event_count, 0)
        self.assertEqual(second.skipped_ready_asset_partitions, ((FREQ, DATE_1),))

    def test_bootstrap_audit_does_not_recalculate_qfq_prices(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_gold_inputs(lake_root)
            stock_a_path = gold_stk_mins_qfq_path(lake_root, FREQ, STOCK_A, 2014)
            with duckdb.connect(database=":memory:") as connection:
                rows = [
                    dict(
                        zip(
                            [column.name for column in GOLD_STK_MINS_QFQ_SCHEMA],
                            row,
                            strict=True,
                        )
                    )
                    for row in connection.execute(
                        f"""
                        SELECT *
                        FROM {read_parquet(stock_a_path, hive_partitioning=False)}
                        """
                    ).fetchall()
                ]
            rows[0].update(open=20.0, high=21.0, low=19.0, close=20.5)
            _write_rows(
                stock_a_path,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=rows,
                order_by="trade_date, trade_time",
            )
            instance = dg.DagsterInstance.ephemeral()

            report = report_stk_mins_qfq_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                registered_partition_keys=[DATE_1, DATE_2],
                partition_keys=[DATE_1],
                freqs=[FREQ],
            )
            materializations = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=GOLD_STK_MINS_QFQ_ASSET_KEYS[FREQ],
                    asset_partitions=[DATE_1],
                ),
                limit=1,
            ).records

        self.assertEqual(report.reported_event_count, 5)
        self.assertEqual(len(materializations), 1)

    def test_report_writes_each_year_after_that_year_audit_passes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_gold_inputs(lake_root)
            _write_silver_partition(lake_root, DATE_3)
            _write_adj_partition(lake_root, DATE_3)
            generate_stk_mins_qfq_history(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                registered_partition_keys=[DATE_3],
                freqs=[FREQ],
            )
            stock_a_2015_path = gold_stk_mins_qfq_path(lake_root, FREQ, STOCK_A, 2015)
            with duckdb.connect(database=":memory:") as connection:
                rows = [
                    dict(
                        zip(
                            [column.name for column in GOLD_STK_MINS_QFQ_SCHEMA],
                            row,
                            strict=True,
                        )
                    )
                    for row in connection.execute(
                        f"""
                        SELECT *
                        FROM {read_parquet(stock_a_2015_path, hive_partitioning=False)}
                        """
                    ).fetchall()
                ]
            rows[0]["open"] = 999.0
            _write_rows(
                stock_a_2015_path,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=rows,
                order_by="trade_date, trade_time",
            )
            instance = dg.DagsterInstance.ephemeral()

            with self.assertRaisesRegex(ValueError, "bootstrap audit failed"):
                report_stk_mins_qfq_bootstrap_events(
                    instance=instance,
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    registered_partition_keys=[DATE_1, DATE_2, DATE_3],
                    freqs=[FREQ],
                )
            materialized_2014 = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=GOLD_STK_MINS_QFQ_ASSET_KEYS[FREQ],
                    asset_partitions=[DATE_1],
                ),
                limit=1,
            ).records
            materialized_2015 = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=GOLD_STK_MINS_QFQ_ASSET_KEYS[FREQ],
                    asset_partitions=[DATE_3],
                ),
                limit=1,
            ).records

        self.assertEqual(len(materialized_2014), 1)
        self.assertEqual(materialized_2015, [])

    def test_final_audit_uses_counts_and_sample_readiness(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_gold_inputs(lake_root)
            instance = dg.DagsterInstance.ephemeral()
            report_stk_mins_qfq_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                registered_partition_keys=[DATE_1, DATE_2],
                partition_keys=[DATE_1],
                freqs=[FREQ],
            )

            final = audit_stk_mins_qfq_final_state(
                instance=instance,
                lake_root=lake_root,
                registered_partition_keys=[DATE_1, DATE_2],
                partition_keys=[DATE_1],
                freqs=[FREQ],
                duckdb_resource=DuckDBResource(),
            )

        self.assertEqual(final.selected_partition_count, 1)
        self.assertEqual(final.materialized_partition_counts, {FREQ: 1})
        self.assertTrue(final.sample_readiness[f"{FREQ}:{DATE_1}"])
        self.assertEqual(len(final.check_success_counts), len(GOLD_STK_MINS_QFQ_CHECKS))

    def test_cli_plan_and_report_commands(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_gold_inputs(lake_root)
            instance = dg.DagsterInstance.ephemeral()
            buffer = io.StringIO()

            with patch.object(
                dg.DagsterInstance,
                "get",
                return_value=instance,
            ), patch.object(
                stk_mins_migration_cli,
                "_registered_stock_mins_silver_partition_keys",
                return_value=(DATE_1, DATE_2),
            ), contextlib.redirect_stdout(buffer):
                stk_mins_migration_cli.main(
                    [
                        "plan-gold-qfq-events",
                        "--lake-root",
                        str(lake_root),
                        "--partition-keys",
                        DATE_1,
                        "--freqs",
                        str(FREQ),
                    ]
                )
                stk_mins_migration_cli.main(
                    [
                        "report-gold-qfq-events",
                        "--lake-root",
                        str(lake_root),
                        "--partition-keys",
                        DATE_1,
                        "--freqs",
                        str(FREQ),
                    ]
                )
                stk_mins_migration_cli.main(
                    [
                        "audit-gold-qfq-final",
                        "--lake-root",
                        str(lake_root),
                        "--partition-keys",
                        DATE_1,
                        "--freqs",
                        str(FREQ),
                    ]
                )

        output = buffer.getvalue()
        self.assertIn("'asset_partition_count': 1", output)
        self.assertIn("'reported_event_count': 5", output)
        self.assertIn("'sample_readiness': {'5:2014-06-03': True}", output)


if __name__ == "__main__":
    unittest.main()
