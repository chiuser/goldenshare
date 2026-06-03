import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import dagster as dg
import duckdb

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.jobs.stock_mins_qfq_factor_repair import (
    STOCK_MINS_QFQ_FACTOR_REPAIR_JOB_NAME,
    stock_mins_qfq_factor_repair_job,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
    silver_stock_basic_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_STK_MINS_SCHEMA,
    SILVER_STOCK_BASIC_SCHEMA,
)
from orchestrator.defs.stk_mins_qfq import (
    GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
    QFQ_FACTOR_REPAIR_REASON_FACTOR_CHANGED,
    QFQ_FACTOR_REPAIR_REASON_NO_FACTOR_CHANGED,
)
from orchestrator.defs.stk_mins_qfq_factor_repair import (
    execute_gold_stk_mins_qfq_factor_repair,
)


PREVIOUS_DATE = "2026-05-28"
TRADE_DATE = "2026-05-29"
STOCK_A = "600000.SH"
STOCK_B = "000001.SZ"
STOCK_C = "300001.SZ"


def _column_types(schema) -> dict[str, str]:
    return {column.name: column.type for column in schema}


def _write_rows(
    path: Path,
    *,
    schema,
    rows: list[dict[str, object]],
    order_by: str,
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


def _adj_row(ts_code: str, trade_date: str, adj_factor: float) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "adj_factor": adj_factor,
    }


def _silver_row(
    ts_code: str,
    trade_date: str,
    trade_time: str,
    *,
    open_: float,
    freq: int = 1,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": freq,
        "trade_date": trade_date,
        "trade_time": f"{trade_date} {trade_time}",
        "open": open_,
        "high": open_ + 1,
        "low": open_ - 1,
        "close": open_ + 0.5,
        "vol": 1000.0,
        "amount": 10000.0,
        "exchange": "SSE" if ts_code.endswith(".SH") else "SZSE",
    }


def _gold_row(
    ts_code: str,
    trade_date: str,
    trade_time: str,
    *,
    open_: float,
    freq: int = 1,
) -> dict[str, object]:
    return _silver_row(ts_code, trade_date, trade_time, open_=open_, freq=freq)


def _stock_basic_row(ts_code: str, list_date: str) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "symbol": ts_code.split(".", maxsplit=1)[0],
        "name": f"stock-{ts_code}",
        "area": "CN",
        "industry": "test",
        "market": "主板",
        "exchange": ts_code.rsplit(".", maxsplit=1)[-1],
        "list_status": "L",
        "list_date": list_date,
        "delist_date": None,
        "is_hs": "",
    }


def _write_stock_basic(path: Path, rows: list[dict[str, object]]) -> None:
    _write_rows(
        path,
        schema=SILVER_STOCK_BASIC_SCHEMA,
        rows=rows,
        order_by="ts_code",
    )


def _write_adj_factor(path: Path, rows: list[dict[str, object]]) -> None:
    _write_rows(
        path,
        schema=SILVER_ADJ_FACTOR_SCHEMA,
        rows=rows,
        order_by="ts_code",
    )


def _write_silver_mins(path: Path, rows: list[dict[str, object]]) -> None:
    _write_rows(
        path,
        schema=SILVER_STK_MINS_SCHEMA,
        rows=rows,
        order_by="ts_code, trade_time",
    )


def _write_gold_qfq(path: Path, rows: list[dict[str, object]]) -> None:
    _write_rows(
        path,
        schema=GOLD_STK_MINS_QFQ_SCHEMA,
        rows=rows,
        order_by="trade_date, trade_time",
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


def _write_repair_inputs(
    lake_root: Path,
    *,
    changed: bool,
    write_silver_rows: bool = True,
) -> None:
    previous_factor = 2.0
    current_factor = 4.0 if changed else 2.0
    _write_stock_basic(
        silver_stock_basic_path(lake_root),
        [_stock_basic_row(STOCK_A, "1999-11-10")],
    )
    _write_adj_factor(
        silver_adj_factor_path(lake_root, PREVIOUS_DATE),
        [_adj_row(STOCK_A, PREVIOUS_DATE, previous_factor)],
    )
    _write_adj_factor(
        silver_adj_factor_path(lake_root, TRADE_DATE),
        [_adj_row(STOCK_A, TRADE_DATE, current_factor)],
    )
    if write_silver_rows:
        _write_silver_mins(
            silver_stk_mins_path(lake_root, 1, PREVIOUS_DATE),
            [_silver_row(STOCK_A, PREVIOUS_DATE, "09:30:00", open_=10.0)],
        )
        _write_silver_mins(
            silver_stk_mins_path(lake_root, 1, TRADE_DATE),
            [_silver_row(STOCK_A, TRADE_DATE, "09:30:00", open_=20.0)],
        )


def _write_multi_code_repair_inputs(
    lake_root: Path,
    *,
    stock_codes: tuple[str, ...],
    freqs: tuple[int, ...],
    partition_keys: tuple[str, ...],
    missing_silver_codes: tuple[str, ...] = (),
) -> None:
    _write_stock_basic(
        silver_stock_basic_path(lake_root),
        [_stock_basic_row(stock_code, "1999-11-10") for stock_code in stock_codes],
    )
    for partition_key in partition_keys:
        _write_adj_factor(
            silver_adj_factor_path(lake_root, partition_key),
            [
                _adj_row(
                    stock_code,
                    partition_key,
                    4.0 if partition_key == TRADE_DATE else 2.0,
                )
                for stock_code in stock_codes
            ],
        )
        for freq in freqs:
            rows = [
                _silver_row(
                    stock_code,
                    partition_key,
                    "09:30:00",
                    open_=10.0 + index,
                    freq=freq,
                )
                for index, stock_code in enumerate(stock_codes)
                if stock_code not in missing_silver_codes
            ]
            _write_silver_mins(
                silver_stk_mins_path(lake_root, freq, partition_key),
                rows,
            )


class StkMinsQfqM9CFactorRepairTests(unittest.TestCase):
    def test_no_factor_change_returns_successful_noop_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_repair_inputs(lake_root, changed=False, write_silver_rows=False)

            report = execute_gold_stk_mins_qfq_factor_repair(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                trade_date=TRADE_DATE,
                registered_partition_keys=[PREVIOUS_DATE, TRADE_DATE],
                freqs=[1],
            )

        self.assertEqual(report.plan.reason, QFQ_FACTOR_REPAIR_REASON_NO_FACTOR_CHANGED)
        self.assertFalse(report.plan.repair_required)
        self.assertEqual(report.repaired_code_count, 0)
        self.assertEqual(report.rewritten_file_count, 0)

    def test_factor_change_rewrites_existing_stock_year_file_with_qfq_rows(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_repair_inputs(lake_root, changed=True)
            target_path = gold_stk_mins_qfq_path(lake_root, 1, STOCK_A, 2026)
            _write_gold_qfq(
                target_path,
                [
                    _gold_row(STOCK_A, PREVIOUS_DATE, "09:30:00", open_=999.0),
                    _gold_row(STOCK_A, TRADE_DATE, "09:30:00", open_=999.0),
                ],
            )

            report = execute_gold_stk_mins_qfq_factor_repair(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                trade_date=TRADE_DATE,
                registered_partition_keys=[PREVIOUS_DATE, TRADE_DATE],
                freqs=[1],
            )
            rows = _read_gold_rows(target_path)

        self.assertEqual(report.plan.reason, QFQ_FACTOR_REPAIR_REASON_FACTOR_CHANGED)
        self.assertEqual(report.repaired_code_count, 1)
        self.assertEqual(report.rewritten_file_count, 1)
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0]["open"], 5.0)
        self.assertAlmostEqual(rows[1]["open"], 20.0)
        self.assertEqual(report.rewritten_row_count, 2)
        self.assertEqual(report.execution_model, "freq_year_batch")
        self.assertEqual(report.planned_batch_count, 1)
        self.assertEqual(report.executed_batch_count, 1)
        self.assertEqual(report.non_empty_batch_count, 1)

    def test_factor_change_batches_by_freq_and_year_not_by_stock_code(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            stock_codes = (STOCK_A, STOCK_B, STOCK_C)
            freqs = (1, 5)
            partition_keys = ("2025-05-29", PREVIOUS_DATE, TRADE_DATE)
            _write_multi_code_repair_inputs(
                lake_root,
                stock_codes=stock_codes,
                freqs=freqs,
                partition_keys=partition_keys,
            )

            report = execute_gold_stk_mins_qfq_factor_repair(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                trade_date=TRADE_DATE,
                registered_partition_keys=partition_keys,
                freqs=freqs,
            )

        self.assertEqual(report.plan.factor_changed_code_count, 3)
        self.assertEqual(report.repaired_code_count, 3)
        self.assertEqual(report.execution_model, "freq_year_batch")
        self.assertEqual(report.planned_batch_count, 4)
        self.assertEqual(report.executed_batch_count, 4)
        self.assertEqual(report.non_empty_batch_count, 4)
        self.assertEqual(report.rewritten_file_count, 12)
        self.assertEqual({result.ts_code for result in report.code_results}, set(stock_codes))
        for code_result in report.code_results:
            self.assertEqual(code_result.rewritten_file_count, 4)

    def test_factor_change_without_silver_rows_fails_instead_of_fake_success(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_repair_inputs(lake_root, changed=True, write_silver_rows=False)

            with self.assertRaisesRegex(FileNotFoundError, "silver_stk_mins"):
                execute_gold_stk_mins_qfq_factor_repair(
                    lake_root=lake_root,
                    duckdb_resource=DuckDBResource(),
                    trade_date=TRADE_DATE,
                    registered_partition_keys=[PREVIOUS_DATE, TRADE_DATE],
                    freqs=[1],
                )

    def test_changed_code_without_any_silver_rows_is_reported_as_unrepaired(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            stock_codes = (STOCK_A, STOCK_B)
            partition_keys = (PREVIOUS_DATE, TRADE_DATE)
            _write_multi_code_repair_inputs(
                lake_root,
                stock_codes=stock_codes,
                freqs=(1,),
                partition_keys=partition_keys,
                missing_silver_codes=(STOCK_B,),
            )

            report = execute_gold_stk_mins_qfq_factor_repair(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                trade_date=TRADE_DATE,
                registered_partition_keys=partition_keys,
                freqs=[1],
            )

        self.assertEqual(report.plan.repair_required_code_count, 2)
        self.assertEqual(report.repaired_code_count, 1)
        self.assertEqual(report.rewritten_file_count, 1)
        self.assertEqual(report.code_results[0].ts_code, STOCK_A)

    def test_non_partitioned_op_job_emits_repair_check_events_from_run_config(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_repair_inputs(lake_root, changed=False, write_silver_rows=False)
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name,
                [PREVIOUS_DATE, TRADE_DATE],
            )

            result = stock_mins_qfq_factor_repair_job.execute_in_process(
                run_config={
                    "ops": {
                        "stock_mins_qfq_factor_repair_op": {
                            "config": {"trade_date": TRADE_DATE}
                        }
                    }
                },
                instance=instance,
                resources={
                    "lake_root": LakeRootResource(root_path=str(lake_root)),
                    "duckdb": DuckDBResource(),
                },
            )
            records = instance.get_event_records(
                dg.EventRecordsFilter(
                    event_type=dg.DagsterEventType.ASSET_CHECK_EVALUATION
                ),
                limit=10,
            )

        self.assertTrue(result.success)
        self.assertEqual(stock_mins_qfq_factor_repair_job.name, STOCK_MINS_QFQ_FACTOR_REPAIR_JOB_NAME)
        self.assertEqual(len(records), 5)
        for record in records:
            evaluation = record.event_log_entry.dagster_event.event_specific_data
            self.assertEqual(
                evaluation.check_name,
                GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
            )
            self.assertTrue(evaluation.passed)
            self.assertEqual(evaluation.partition, TRADE_DATE)
            self.assertEqual(
                evaluation.metadata["goldenshare/reason"].text,
                "no_factor_changed",
            )

    def test_factor_repair_job_contract_is_non_partitioned_and_in_process(self) -> None:
        self.assertEqual(
            stock_mins_qfq_factor_repair_job.name,
            STOCK_MINS_QFQ_FACTOR_REPAIR_JOB_NAME,
        )
        self.assertIsNone(stock_mins_qfq_factor_repair_job.partitions_def)
        self.assertEqual(
            stock_mins_qfq_factor_repair_job.executor_def.name,
            "in_process",
        )

    def test_factor_repair_job_requires_trade_date_run_config(self) -> None:
        with self.assertRaises(dg.DagsterInvalidConfigError):
            dg.validate_run_config(stock_mins_qfq_factor_repair_job, {})

        dg.validate_run_config(
            stock_mins_qfq_factor_repair_job,
            {
                "ops": {
                    "stock_mins_qfq_factor_repair_op": {
                        "config": {"trade_date": TRADE_DATE}
                    }
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
