import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import dagster as dg
import duckdb

from orchestrator.defs import stk_mins_qfq_factor_repair as repair_module
from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    asset_check_record_event_storage_id,
    asset_check_record_storage_id,
    gold_stk_mins_qfq_factor_repair_status,
)
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.jobs.stock_mins_qfq_factor_repair import (
    STOCK_MINS_QFQ_FACTOR_REPAIR_JOB_NAME,
    stock_mins_qfq_factor_repair_job,
)
from orchestrator.defs.ops.stock_mins_qfq_factor_repair import (
    stock_mins_qfq_factor_repair_op,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
    silver_stock_basic_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_STK_MINS_SCHEMA,
    SILVER_STOCK_BASIC_SCHEMA,
)
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    expected_canonical_gold_source_times,
)
from orchestrator.defs.stk_mins_qfq import (
    GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
    GOLD_STK_MINS_QFQ_WRITER_POOL,
    QFQ_FACTOR_REPAIR_REASON_FACTOR_CHANGED,
    QFQ_FACTOR_REPAIR_REASON_NO_FACTOR_CHANGED,
    gold_stk_mins_qfq_source_freq,
)
from orchestrator.defs.stk_mins_qfq_factor_repair import (
    execute_gold_stk_mins_qfq_factor_repair,
)

PREVIOUS_DATE = "2026-05-28"
TRADE_DATE = "2026-05-29"
FUTURE_DATE = "2026-06-02"
EXPECTED_TRADE_DATES = (PREVIOUS_DATE, TRADE_DATE)
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


def _write_trade_calendar(
    lake_root: Path,
    trade_dates: tuple[str, ...] = EXPECTED_TRADE_DATES,
) -> None:
    calendar_path = silver_trade_calendar_path(lake_root)
    calendar_path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(
        f"('SSE', true, DATE '{trade_date}')" for trade_date in trade_dates
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT *
              FROM (VALUES {values_sql}) AS calendar(exchange, is_open, trade_date)
            ) TO {duckdb_string(calendar_path)} (FORMAT PARQUET)
            """
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
        source_times = expected_canonical_gold_source_times(1)
        _write_silver_mins(
            silver_stk_mins_path(lake_root, 1, PREVIOUS_DATE),
            _intraday_rows(
                STOCK_A,
                PREVIOUS_DATE,
                freq=1,
                trade_times=source_times,
                open_base=10.0,
            ),
        )
        _write_silver_mins(
            silver_stk_mins_path(lake_root, 1, TRADE_DATE),
            _intraday_rows(
                STOCK_A,
                TRADE_DATE,
                freq=1,
                trade_times=source_times,
                open_base=20.0,
            ),
        )


def _intraday_rows(
    ts_code: str,
    trade_date: str,
    *,
    freq: int,
    trade_times: tuple[str, ...],
    open_base: float,
) -> list[dict[str, object]]:
    return [
        _silver_row(
            ts_code,
            trade_date,
            trade_time,
            open_=open_base + index,
            freq=freq,
        )
        for index, trade_time in enumerate(trade_times)
    ]


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
        source_times_by_freq: dict[int, set[str]] = {}
        for target_freq in freqs:
            source_freq = gold_stk_mins_qfq_source_freq(target_freq)
            source_times_by_freq.setdefault(source_freq, set()).update(
                expected_canonical_gold_source_times(target_freq)
            )
        for source_freq, source_times in sorted(source_times_by_freq.items()):
            rows = [
                _silver_row(
                    stock_code,
                    partition_key,
                    trade_time,
                    open_=10.0 + stock_index + time_index,
                    freq=source_freq,
                )
                for stock_index, stock_code in enumerate(stock_codes)
                if stock_code not in missing_silver_codes
                for time_index, trade_time in enumerate(sorted(source_times))
            ]
            _write_silver_mins(
                silver_stk_mins_path(lake_root, source_freq, partition_key),
                rows,
            )


class StkMinsQfqM9CFactorRepairTests(unittest.TestCase):
    def test_qfq_factor_repair_status_uses_event_log_storage_id(self) -> None:
        record = SimpleNamespace(
            id=1316996,
            storage_id=1316996,
            event=SimpleNamespace(storage_id=5749865),
        )

        self.assertEqual(asset_check_record_storage_id(record), 5749865)

    def test_qfq_factor_repair_status_resolves_event_log_storage_id(self) -> None:
        check_key = dg.AssetCheckKey(dg.AssetKey("gold_stk_mins_qfq_1m"), "check")
        record = SimpleNamespace(
            id=1316996,
            event=SimpleNamespace(run_id="run-1", timestamp=100.0),
        )
        event_record = SimpleNamespace(
            storage_id=5749865,
            event_log_entry=SimpleNamespace(
                run_id="run-1",
                dagster_event=SimpleNamespace(
                    event_specific_data=SimpleNamespace(
                        asset_key=check_key.asset_key,
                        check_name="check",
                        partition=TRADE_DATE,
                    )
                ),
            ),
        )
        instance = SimpleNamespace(
            get_event_records=lambda *args, **kwargs: [event_record]
        )

        self.assertIsNone(asset_check_record_storage_id(record))
        self.assertEqual(
            asset_check_record_event_storage_id(
                instance,
                check_key,
                record,
                partition_key=TRADE_DATE,
            ),
            5749865,
        )

    def test_qfq_factor_repair_status_can_skip_event_storage_id_backfill(self) -> None:
        metadata = {
            "producer_run_id": "run-1",
            "upstream_batch_id": f"qfq_factor_repair:{TRADE_DATE}:digest",
            "repair_required": False,
            "repair_required_code_count": 0,
            "repair_required_codes": [],
            "repair_required_codes_hash": "empty",
            "repair_required_codes_truncated": False,
            "repair_start_trade_date": TRADE_DATE,
            "repair_end_trade_date": TRADE_DATE,
            "selected_partition_count": 1,
            "rewritten_file_count": 0,
            "rewritten_row_count": 0,
            "derived_rewrite_required": False,
            "derived_rewritten_file_count": 0,
            "derived_rewritten_row_count": 0,
        }
        evaluation = SimpleNamespace(
            passed=True,
            blocking=True,
            partition=TRADE_DATE,
            metadata=metadata,
        )
        record = SimpleNamespace(
            status="SUCCEEDED",
            partition=TRADE_DATE,
            event=SimpleNamespace(
                run_id="run-1",
                timestamp=100.0,
                dagster_event=SimpleNamespace(event_specific_data=evaluation),
            ),
        )

        class _FakeEventLogStorage:
            def get_latest_asset_check_execution_by_key(
                self,
                check_keys,
                *,
                partition_filter,
            ):
                return {check_key: record for check_key in check_keys}

        def fail_event_history(*_args, **_kwargs):
            raise AssertionError("event storage id backfill must not run")

        instance = SimpleNamespace(
            event_log_storage=_FakeEventLogStorage(),
            get_event_records=fail_event_history,
        )

        status = gold_stk_mins_qfq_factor_repair_status(
            instance,
            TRADE_DATE,
            include_event_storage_ids=False,
        )

        self.assertTrue(status.ready)
        self.assertEqual(status.qfq_factor_repair_event_storage_ids, ())
        self.assertEqual(status.upstream_batch_id, metadata["upstream_batch_id"])

    def test_no_factor_change_returns_successful_noop_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_repair_inputs(lake_root, changed=False, write_silver_rows=False)

            report = execute_gold_stk_mins_qfq_factor_repair(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                trade_date=TRADE_DATE,
                expected_trade_dates=EXPECTED_TRADE_DATES,
                registered_partition_keys=[PREVIOUS_DATE, TRADE_DATE],
                freqs=[1],
            )

        self.assertEqual(report.plan.reason, QFQ_FACTOR_REPAIR_REASON_NO_FACTOR_CHANGED)
        self.assertFalse(report.plan.repair_required)
        self.assertEqual(report.repaired_code_count, 0)
        self.assertEqual(report.rewritten_file_count, 0)

    def test_factor_repair_fails_when_expected_trade_date_is_not_registered(
        self,
    ) -> None:
        expected_trade_dates = ("2026-06-13", "2026-06-15", "2026-06-16")
        registered_trade_days = ("2026-06-13", "2026-06-16")
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            with self.assertRaises(dg.Failure) as failure:
                execute_gold_stk_mins_qfq_factor_repair(
                    lake_root=lake_root,
                    duckdb_resource=DuckDBResource(),
                    trade_date="2026-06-16",
                    expected_trade_dates=expected_trade_dates,
                    registered_partition_keys=registered_trade_days,
                    freqs=[1],
                )

            self.assertFalse((lake_root / "gold").exists())

        self.assertIn(
            "first_missing_registered_date=2026-06-15",
            failure.exception.description,
        )
        self.assertIn("first_missing_registered_date", failure.exception.metadata)

    def test_factor_repair_fails_when_target_is_not_expected_trade_date(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            with self.assertRaises(dg.Failure) as failure:
                execute_gold_stk_mins_qfq_factor_repair(
                    lake_root=lake_root,
                    duckdb_resource=DuckDBResource(),
                    trade_date="2026-06-16",
                    expected_trade_dates=("2026-06-13", "2026-06-15"),
                    registered_partition_keys=(
                        "2026-06-13",
                        "2026-06-15",
                        "2026-06-16",
                    ),
                    freqs=[1],
                )

        self.assertIn(
            "QFQ repair trade date is not in stock mins expected calendar",
            failure.exception.description,
        )

    def test_factor_change_rewrites_existing_stock_year_file_with_qfq_rows(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_repair_inputs(lake_root, changed=True)
            _write_adj_factor(
                silver_adj_factor_path(lake_root, FUTURE_DATE),
                [_adj_row(STOCK_A, FUTURE_DATE, 8.0)],
            )
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
                expected_trade_dates=EXPECTED_TRADE_DATES,
                registered_partition_keys=[PREVIOUS_DATE, TRADE_DATE],
                freqs=[1],
            )
            rows = _read_gold_rows(target_path)

        self.assertEqual(report.plan.reason, QFQ_FACTOR_REPAIR_REASON_FACTOR_CHANGED)
        self.assertEqual(report.repaired_code_count, 1)
        self.assertEqual(report.rewritten_file_count, 1)
        self.assertEqual(len(rows), 2 * len(expected_canonical_gold_source_times(1)))
        self.assertAlmostEqual(rows[0]["open"], 5.0)
        self.assertAlmostEqual(
            rows[len(expected_canonical_gold_source_times(1))]["open"],
            20.0,
        )
        self.assertEqual(
            report.rewritten_row_count,
            2 * len(expected_canonical_gold_source_times(1)),
        )
        self.assertEqual(report.execution_model, "freq_year_batch")
        self.assertEqual(report.planned_batch_count, 1)
        self.assertEqual(report.executed_batch_count, 1)
        self.assertEqual(report.non_empty_batch_count, 1)
        self.assertFalse(hasattr(repair_module, "_discover_silver_adj_factor_paths"))
        self.assertFalse(hasattr(repair_module, "_write_latest_adj_factor_snapshot"))

    def test_factor_repair_rejects_partial_canonical_source_before_rewrite(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_repair_inputs(lake_root, changed=True)
            _write_silver_mins(
                silver_stk_mins_path(lake_root, 1, PREVIOUS_DATE),
                [_silver_row(STOCK_A, PREVIOUS_DATE, "09:30:00", open_=10.0)],
            )
            target_path = gold_stk_mins_qfq_path(lake_root, 1, STOCK_A, 2026)
            original_rows = [
                _gold_row(STOCK_A, PREVIOUS_DATE, "09:30:00", open_=999.0),
                _gold_row(STOCK_A, TRADE_DATE, "09:30:00", open_=999.0),
            ]
            _write_gold_qfq(target_path, original_rows)

            with self.assertRaisesRegex(
                RuntimeError,
                "Canonical Gold qfq source windows are incomplete",
            ):
                execute_gold_stk_mins_qfq_factor_repair(
                    lake_root=lake_root,
                    duckdb_resource=DuckDBResource(),
                    trade_date=TRADE_DATE,
                    expected_trade_dates=EXPECTED_TRADE_DATES,
                    registered_partition_keys=[PREVIOUS_DATE, TRADE_DATE],
                    freqs=[1],
                )
            rows = _read_gold_rows(target_path)

        self.assertEqual([row["open"] for row in rows], [999.0, 999.0])

    def test_factor_repair_rebuilds_derived_90m_and_120m_after_30m_60m(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_stock_basic(
                silver_stock_basic_path(lake_root),
                [_stock_basic_row(STOCK_A, "1999-11-10")],
            )
            _write_adj_factor(
                silver_adj_factor_path(lake_root, PREVIOUS_DATE),
                [_adj_row(STOCK_A, PREVIOUS_DATE, 2.0)],
            )
            _write_adj_factor(
                silver_adj_factor_path(lake_root, TRADE_DATE),
                [_adj_row(STOCK_A, TRADE_DATE, 4.0)],
            )
            for partition_key, open_base in ((PREVIOUS_DATE, 10.0), (TRADE_DATE, 20.0)):
                _write_silver_mins(
                    silver_stk_mins_path(lake_root, 5, partition_key),
                    _intraday_rows(
                        STOCK_A,
                        partition_key,
                        freq=5,
                        trade_times=expected_canonical_gold_source_times(30),
                        open_base=open_base,
                    ),
                )
                _write_silver_mins(
                    silver_stk_mins_path(lake_root, 30, partition_key),
                    _intraday_rows(
                        STOCK_A,
                        partition_key,
                        freq=30,
                        trade_times=(
                            "09:30:00",
                            "10:00:00",
                            "10:30:00",
                            "11:00:00",
                            "11:30:00",
                            "13:30:00",
                            "14:00:00",
                            "14:30:00",
                            "15:00:00",
                        ),
                        open_base=open_base,
                    ),
                )
                _write_silver_mins(
                    silver_stk_mins_path(lake_root, 60, partition_key),
                    _intraday_rows(
                        STOCK_A,
                        partition_key,
                        freq=60,
                        trade_times=(
                            "09:30:00",
                            "10:30:00",
                            "11:30:00",
                            "14:00:00",
                            "15:00:00",
                        ),
                        open_base=open_base,
                    ),
                )

            report = execute_gold_stk_mins_qfq_factor_repair(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                trade_date=TRADE_DATE,
                expected_trade_dates=EXPECTED_TRADE_DATES,
                registered_partition_keys=[PREVIOUS_DATE, TRADE_DATE],
                freqs=[30, 60],
            )

            rows_90m = _read_gold_rows(
                gold_stk_mins_qfq_path(lake_root, 90, STOCK_A, 2026)
            )
            rows_120m = _read_gold_rows(
                gold_stk_mins_qfq_path(lake_root, 120, STOCK_A, 2026)
            )

        self.assertTrue(report.derived_rewrite_required)
        self.assertEqual(report.derived_planned_batch_count, 2)
        self.assertEqual(report.derived_executed_batch_count, 2)
        self.assertEqual(report.derived_rewritten_file_count, 2)
        self.assertEqual(report.derived_rewritten_row_count, 10)
        self.assertEqual(report.derived_repaired_code_count, 1)
        self.assertEqual(report.derived_failed_code_count, 0)
        self.assertEqual(len(rows_90m), 6)
        self.assertEqual(len(rows_120m), 4)

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
                expected_trade_dates=partition_keys,
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
                    expected_trade_dates=EXPECTED_TRADE_DATES,
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
                expected_trade_dates=partition_keys,
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
            _write_trade_calendar(lake_root)
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
        self.assertEqual(len(records), 7)
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
            self.assertEqual(
                evaluation.metadata["goldenshare/repair_start_trade_date"].text,
                PREVIOUS_DATE,
            )
            self.assertEqual(
                evaluation.metadata["goldenshare/repair_end_trade_date"].text,
                TRADE_DATE,
            )
            self.assertEqual(
                evaluation.metadata["goldenshare/selected_partition_count"].value,
                2,
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
        self.assertEqual(
            stock_mins_qfq_factor_repair_op.pool,
            GOLD_STK_MINS_QFQ_WRITER_POOL,
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
