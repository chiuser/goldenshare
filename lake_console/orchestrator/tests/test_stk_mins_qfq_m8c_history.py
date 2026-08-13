from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import duckdb

from orchestrator.defs.bootstrap import stk_mins_migration_cli
from orchestrator.defs.bootstrap.stk_mins_qfq_history import (
    generate_stk_mins_qfq_history,
    plan_stk_mins_qfq_history,
    rebuild_stk_mins_qfq_canonical_history,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
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
from orchestrator.defs.stk_mins_qfq import gold_stk_mins_qfq_source_freq

DATE_1 = "2014-06-03"
DATE_2 = "2014-06-04"
DATE_3 = "2014-06-05"
STOCK_A = "600000.SH"
STOCK_B = "000001.SZ"


def _column_types(schema) -> dict[str, str]:
    return {column.name: column.type for column in schema}


def _write_rows(
    path: Path,
    *,
    column_types: dict[str, str],
    rows: list[dict[str, object]],
    order_by: str = "1",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(column_types)
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


def _write_silver_partition(
    lake_root: Path,
    *,
    target_freq: int,
    trade_date: str,
) -> None:
    source_freq = gold_stk_mins_qfq_source_freq(target_freq)
    source_times = expected_canonical_gold_source_times(target_freq)
    _write_rows(
        silver_stk_mins_path(lake_root, source_freq, trade_date),
        column_types=_column_types(SILVER_STK_MINS_SCHEMA),
        rows=[
            _silver_row(
                ts_code=stock_code,
                freq=source_freq,
                trade_date=trade_date,
                trade_time=f"{trade_date} {trade_time}",
                open_=open_base,
            )
            for stock_code, open_base in (
                (STOCK_A, 10.0 if trade_date == DATE_1 else 20.0),
                (STOCK_B, 20.0 if trade_date == DATE_1 else 30.0),
            )
            for trade_time in source_times
        ],
        order_by="ts_code, trade_time",
    )


def _write_adj_factor_partition(lake_root: Path, *, trade_date: str) -> None:
    _write_rows(
        silver_adj_factor_path(lake_root, trade_date),
        column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
        rows=[
            _adj_row(STOCK_A, trade_date, 2.0 if trade_date == DATE_1 else 4.0),
            _adj_row(STOCK_B, trade_date, 3.0 if trade_date == DATE_1 else 6.0),
        ],
        order_by="ts_code",
    )


def _write_valid_inputs(lake_root: Path, *, freqs: tuple[int, ...] = (5,)) -> None:
    for target_freq in freqs:
        _write_silver_partition(
            lake_root,
            target_freq=target_freq,
            trade_date=DATE_1,
        )
        _write_silver_partition(
            lake_root,
            target_freq=target_freq,
            trade_date=DATE_2,
        )
    _write_adj_factor_partition(lake_root, trade_date=DATE_1)
    _write_adj_factor_partition(lake_root, trade_date=DATE_2)


def _read_gold_rows(path: Path) -> list[dict[str, object]]:
    with duckdb.connect(database=":memory:") as connection:
        columns = [
            row[0]
            for row in connection.execute(
                f"DESCRIBE SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
            ).fetchall()
        ]
        rows = connection.execute(
            f"""
            SELECT *
            FROM {read_parquet(path, hive_partitioning=False)}
            ORDER BY trade_date, trade_time
            """
        ).fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


class StkMinsQfqM8CHistoryTests(unittest.TestCase):
    def test_rebuild_clis_require_explicit_confirmation_before_discovery(self) -> None:
        commands = (
            "rebuild-gold-qfq-canonical-history",
            "rebuild-gold-stk-mins-qfq-macd-kdj-history",
        )
        for command in commands:
            with (
                self.subTest(command=command),
                TemporaryDirectory() as temp_dir,
                patch.object(
                    stk_mins_migration_cli,
                    "_registered_stock_mins_silver_partition_keys",
                    side_effect=AssertionError("partition discovery must not run"),
                ),
                self.assertRaisesRegex(ValueError, "--confirm-rebuild"),
            ):
                stk_mins_migration_cli.main(
                    [
                        command,
                        "--checkpoint",
                        str(Path(temp_dir) / "checkpoint.json"),
                    ]
                )

    def test_canonical_rebuild_resumes_verified_freq_year_checkpoint(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            checkpoint_path = lake_root / "checkpoint.json"
            _write_valid_inputs(lake_root)

            first = rebuild_stk_mins_qfq_canonical_history(
                checkpoint_path=checkpoint_path,
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                registered_partition_keys=[DATE_1, DATE_2],
                freqs=[5],
            )
            resumed = rebuild_stk_mins_qfq_canonical_history(
                checkpoint_path=checkpoint_path,
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                registered_partition_keys=[DATE_1, DATE_2],
                freqs=[5],
            )

        self.assertEqual(first.executed_batch_count, 1)
        self.assertEqual(first.resumed_batch_count, 0)
        self.assertEqual(resumed.executed_batch_count, 0)
        self.assertEqual(resumed.resumed_batch_count, 1)

    def test_m8c_helper_does_not_define_active_dagster_components(self) -> None:
        helper_path = Path("src/orchestrator/defs/bootstrap/stk_mins_qfq_history.py")
        text = helper_path.read_text()
        for token in ("@dg.asset", "@dg.asset_check", "@dg.sensor", "define_asset_job"):
            self.assertNotIn(token, text)

    def test_generate_writes_qfq_by_stock_year_with_contract_schema(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_inputs(lake_root)
            _write_rows(
                silver_adj_factor_path(lake_root, DATE_3),
                column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
                rows=[
                    _adj_row(STOCK_A, DATE_3, 8.0),
                    _adj_row(STOCK_B, DATE_3, 12.0),
                ],
                order_by="ts_code",
            )

            report = generate_stk_mins_qfq_history(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                registered_partition_keys=[DATE_1, DATE_2],
                freqs=[5],
            )

            self.assertEqual(report.written_file_count, 2)
            stock_a_path = gold_stk_mins_qfq_path(lake_root, 5, STOCK_A, 2014)
            stock_b_path = gold_stk_mins_qfq_path(lake_root, 5, STOCK_B, 2014)
            self.assertTrue(stock_a_path.exists())
            self.assertTrue(stock_b_path.exists())
            rows = _read_gold_rows(stock_a_path)
            self.assertEqual([column.name for column in GOLD_STK_MINS_QFQ_SCHEMA], list(rows[0]))
            self.assertEqual(len(rows), 96)
            self.assertAlmostEqual(rows[0]["open"], 5.25)
            self.assertAlmostEqual(rows[48]["open"], 20.5)
            self.assertEqual(report.plan.planned_event_count, 2 * 1 * 5)

    def test_plan_counts_targets_and_does_not_write_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_inputs(lake_root)

            plan = plan_stk_mins_qfq_history(
                lake_root=lake_root,
                registered_partition_keys=[DATE_1, DATE_2],
                freqs=[5],
            )

            self.assertEqual(plan.selected_partition_keys, (DATE_1, DATE_2))
            self.assertEqual(plan.planned_target_file_count, 2)
            self.assertEqual(plan.existing_target_file_count, 0)
            self.assertEqual(len(plan.batches), 1)
            self.assertFalse((lake_root / "gold").exists())

    def test_generate_fails_when_target_exists(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_inputs(lake_root)
            _write_rows(
                gold_stk_mins_qfq_path(lake_root, 5, STOCK_A, 2014),
                column_types=_column_types(GOLD_STK_MINS_QFQ_SCHEMA),
                rows=[
                    {
                        **_silver_row(
                            ts_code=STOCK_A,
                            freq=5,
                            trade_date=DATE_1,
                            trade_time=f"{DATE_1} 09:35:00",
                            open_=1.0,
                        )
                    }
                ],
                order_by="trade_date, trade_time",
            )

            with self.assertRaisesRegex(FileExistsError, "already exist"):
                generate_stk_mins_qfq_history(
                    lake_root=lake_root,
                    duckdb_resource=DuckDBResource(),
                    registered_partition_keys=[DATE_1, DATE_2],
                    freqs=[5],
                )

    def test_generate_fails_for_missing_silver_or_adj_factor_inputs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_silver_partition(lake_root, target_freq=5, trade_date=DATE_1)

            with self.assertRaisesRegex(FileNotFoundError, "inputs are missing"):
                generate_stk_mins_qfq_history(
                    lake_root=lake_root,
                    duckdb_resource=DuckDBResource(),
                    registered_partition_keys=[DATE_1],
                    freqs=[5],
                )

    def test_generate_fails_when_factor_coverage_is_incomplete(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_silver_partition(lake_root, target_freq=5, trade_date=DATE_1)
            _write_rows(
                silver_adj_factor_path(lake_root, DATE_1),
                column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
                rows=[_adj_row(STOCK_A, DATE_1, 2.0)],
                order_by="ts_code",
            )

            with self.assertRaisesRegex(RuntimeError, "factor coverage failed"):
                generate_stk_mins_qfq_history(
                    lake_root=lake_root,
                    duckdb_resource=DuckDBResource(),
                    registered_partition_keys=[DATE_1],
                    freqs=[5],
                )

    def test_cli_plan_reads_registered_partitions_but_does_not_write(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_inputs(lake_root)
            buffer = io.StringIO()

            with patch.object(
                stk_mins_migration_cli,
                "_registered_stock_mins_silver_partition_keys",
                return_value=(DATE_1, DATE_2),
            ), contextlib.redirect_stdout(buffer):
                stk_mins_migration_cli.main(
                    [
                        "plan-gold-qfq-history",
                        "--lake-root",
                        str(lake_root),
                        "--freqs",
                        "5",
                    ]
                )

            self.assertIn("'planned_target_file_count': 2", buffer.getvalue())
            self.assertFalse((lake_root / "gold").exists())

    def test_cli_generate_writes_only_gold_targets_under_lake_root(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_inputs(lake_root)

            with patch.object(
                stk_mins_migration_cli,
                "_registered_stock_mins_silver_partition_keys",
                return_value=(DATE_1, DATE_2),
            ), contextlib.redirect_stdout(io.StringIO()):
                stk_mins_migration_cli.main(
                    [
                        "generate-gold-qfq-history",
                        "--lake-root",
                        str(lake_root),
                        "--freqs",
                        "5",
                    ]
                )

            self.assertTrue(gold_stk_mins_qfq_path(lake_root, 5, STOCK_A, 2014).exists())
            self.assertTrue(gold_stk_mins_qfq_path(lake_root, 5, STOCK_B, 2014).exists())


if __name__ == "__main__":
    unittest.main()
