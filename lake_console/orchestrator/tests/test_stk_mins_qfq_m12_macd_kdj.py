import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import dagster as dg
import duckdb

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.assets.stk_mins_qfq_macd_kdj import (
    gold_stk_mins_qfq_macd_kdj_1m,
)
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_macd_kdj_path,
    gold_stk_mins_qfq_macd_kdj_state_path,
    gold_stk_mins_qfq_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
    GOLD_STK_MINS_QFQ_SCHEMA,
)
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    SEGMENT_BAR_COUNT,
    write_gold_stk_mins_qfq_macd_kdj_asset_partition,
    write_gold_stk_mins_qfq_macd_kdj_rows,
)


STOCK_A = "600000.SH"
STOCK_B = "000001.SZ"
FIRST_EXPECTED_TRADE_DATE = "2014-01-02"


def _column_types(schema) -> dict[str, str]:
    return {column.name: column.type for column in schema}


def _write_rows(
    path: Path,
    *,
    schema,
    rows: list[dict[str, object]],
    order_by: str = "trade_date, trade_time",
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


def _qfq_row(
    trade_date: str,
    trade_time: str,
    close: float,
    *,
    stock_code: str = STOCK_A,
) -> dict[str, object]:
    return {
        "ts_code": stock_code,
        "freq": 1,
        "trade_date": trade_date,
        "trade_time": f"{trade_date} {trade_time}",
        "open": close - 0.1,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "vol": 100.0,
        "amount": 1000.0,
        "exchange": "SSE",
    }


def _source_rows_for_day(
    trade_date: str,
    *,
    start_close: float,
    stock_code: str = STOCK_A,
) -> list[dict[str, object]]:
    return [
        _qfq_row(
            trade_date,
            f"09:{31 + index:02d}:00",
            start_close + index,
            stock_code=stock_code,
        )
        for index in range(10)
    ]


def _read_rows(path: Path) -> list[dict[str, object]]:
    with duckdb.connect(database=":memory:") as connection:
        columns = [
            row[0]
            for row in connection.execute(
                f"DESCRIBE SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
            ).fetchall()
        ]
        order_column = "trade_time" if "trade_time" in columns else "last_trade_time"
        rows = connection.execute(
            f"""
            SELECT *
            FROM {read_parquet(path, hive_partitioning=False)}
            ORDER BY trade_date, {order_column}, ts_code
            """
        ).fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


def _ensure_test_lake_root_ready(lake_root: Path) -> None:
    for part in ("raw", "silver", "gold", "_tmp"):
        (lake_root / part).mkdir(parents=True, exist_ok=True)


def _write_calendar_rows(lake_root: Path, trade_dates: tuple[str, ...]) -> None:
    calendar_path = silver_trade_calendar_path(lake_root)
    calendar_path.parent.mkdir(parents=True, exist_ok=True)
    if trade_dates:
        values = ", ".join(
            f"(DATE '{trade_date}', 'SSE', true)" for trade_date in trade_dates
        )
        query = f"""
            SELECT trade_date, exchange, is_open
            FROM (VALUES {values}) AS rows(trade_date, exchange, is_open)
            ORDER BY trade_date
        """
    else:
        query = """
            SELECT
              CAST(NULL AS DATE) AS trade_date,
              CAST(NULL AS VARCHAR) AS exchange,
              CAST(NULL AS BOOLEAN) AS is_open
            WHERE false
        """
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(copy_query_to_parquet(query, calendar_path))


class StkMinsQfqM12MacdKdjTests(unittest.TestCase):
    def test_macd_kdj_writes_indicator_and_state_with_expected_formulas(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            source_path = gold_stk_mins_qfq_path(lake_root, 1, STOCK_A, 2026)
            _write_rows(
                source_path,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=_source_rows_for_day("2026-06-01", start_close=10.0),
            )

            indicator_results, state_results, initialized = (
                write_gold_stk_mins_qfq_macd_kdj_rows(
                    lake_root=lake_root,
                    freq=1,
                    source_qfq_paths=(source_path,),
                    target_trade_dates=("2026-06-01",),
                )
            )

            indicator_path = gold_stk_mins_qfq_macd_kdj_path(
                lake_root,
                1,
                STOCK_A,
                2026,
            )
            state_path = gold_stk_mins_qfq_macd_kdj_state_path(
                lake_root,
                1,
                "2026-06-01",
            )
            indicator_rows = _read_rows(indicator_path)
            state_rows = _read_rows(state_path)

        self.assertTrue(initialized)
        self.assertEqual(len(indicator_results), 1)
        self.assertEqual(len(state_results), 1)
        self.assertEqual(len(indicator_rows), 10)
        self.assertEqual(len(state_rows), 1)
        self.assertEqual(
            tuple(indicator_rows[0]),
            tuple(column.name for column in GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA),
        )
        self.assertEqual(
            tuple(state_rows[0]),
            tuple(column.name for column in GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA),
        )
        for row in indicator_rows:
            self.assertAlmostEqual(
                row["macd_qfq"],
                2.0 * (row["macd_dif_qfq"] - row["macd_dea_qfq"]),
                places=10,
            )
            self.assertAlmostEqual(
                row["kdj_qfq"],
                3.0 * row["kdj_k_qfq"] - 2.0 * row["kdj_d_qfq"],
                places=10,
            )
        self.assertEqual(state_rows[0]["last_trade_time"], indicator_rows[-1]["trade_time"])

    def test_old_stock_without_previous_state_fails_closed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            source_path = gold_stk_mins_qfq_path(lake_root, 1, STOCK_A, 2026)
            _write_rows(
                source_path,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=(
                    _source_rows_for_day("2026-06-01", start_close=10.0)
                    + _source_rows_for_day("2026-06-02", start_close=20.0)
                ),
            )

            with self.assertRaisesRegex(RuntimeError, "previous state is missing"):
                write_gold_stk_mins_qfq_macd_kdj_rows(
                    lake_root=lake_root,
                    freq=1,
                    source_qfq_paths=(source_path,),
                    target_trade_dates=("2026-06-02",),
                )

    def test_previous_state_allows_incremental_next_day(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            source_path = gold_stk_mins_qfq_path(lake_root, 1, STOCK_A, 2026)
            _write_rows(
                source_path,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=(
                    _source_rows_for_day("2026-06-01", start_close=10.0)
                    + _source_rows_for_day("2026-06-02", start_close=20.0)
                ),
            )
            write_gold_stk_mins_qfq_macd_kdj_rows(
                lake_root=lake_root,
                freq=1,
                source_qfq_paths=(source_path,),
                target_trade_dates=("2026-06-01",),
            )
            previous_state = gold_stk_mins_qfq_macd_kdj_state_path(
                lake_root,
                1,
                "2026-06-01",
            )

            indicator_results, state_results, initialized = (
                write_gold_stk_mins_qfq_macd_kdj_rows(
                    lake_root=lake_root,
                    freq=1,
                    source_qfq_paths=(source_path,),
                    target_trade_dates=("2026-06-02",),
                    previous_state_paths=(previous_state,),
                )
            )

            indicator_path = gold_stk_mins_qfq_macd_kdj_path(
                lake_root,
                1,
                STOCK_A,
                2026,
            )
            indicator_rows = _read_rows(indicator_path)

        self.assertFalse(initialized)
        self.assertEqual(len(indicator_results), 1)
        self.assertEqual(len(state_results), 1)
        self.assertEqual(
            [row["trade_date"].isoformat() for row in indicator_rows],
            ["2026-06-01"] * 10 + ["2026-06-02"] * 10,
        )
        self.assertEqual(SEGMENT_BAR_COUNT, 1024)

    def test_scoped_repair_state_merge_preserves_unaffected_stock_state(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            source_a_path = gold_stk_mins_qfq_path(lake_root, 1, STOCK_A, 2026)
            source_b_path = gold_stk_mins_qfq_path(lake_root, 1, STOCK_B, 2026)
            _write_rows(
                source_a_path,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=(
                    _source_rows_for_day("2026-06-01", start_close=10.0)
                    + _source_rows_for_day("2026-06-02", start_close=20.0)
                ),
            )
            _write_rows(
                source_b_path,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=(
                    _source_rows_for_day(
                        "2026-06-01",
                        start_close=100.0,
                        stock_code=STOCK_B,
                    )
                    + _source_rows_for_day(
                        "2026-06-02",
                        start_close=110.0,
                        stock_code=STOCK_B,
                    )
                ),
            )
            write_gold_stk_mins_qfq_macd_kdj_rows(
                lake_root=lake_root,
                freq=1,
                source_qfq_paths=(source_a_path, source_b_path),
                target_trade_dates=("2026-06-01",),
            )
            previous_state = gold_stk_mins_qfq_macd_kdj_state_path(
                lake_root,
                1,
                "2026-06-01",
            )
            write_gold_stk_mins_qfq_macd_kdj_rows(
                lake_root=lake_root,
                freq=1,
                source_qfq_paths=(source_a_path, source_b_path),
                target_trade_dates=("2026-06-02",),
                previous_state_paths=(previous_state,),
            )
            state_path = gold_stk_mins_qfq_macd_kdj_state_path(
                lake_root,
                1,
                "2026-06-02",
            )
            before_rows = _read_rows(state_path)
            unaffected_before = next(
                row for row in before_rows if row["ts_code"] == STOCK_B
            )

            write_gold_stk_mins_qfq_macd_kdj_rows(
                lake_root=lake_root,
                freq=1,
                source_qfq_paths=(source_a_path, source_b_path),
                target_trade_dates=("2026-06-02",),
                previous_state_paths=(previous_state,),
                stock_codes=(STOCK_A,),
            )
            after_rows = _read_rows(state_path)
            unaffected_after = next(row for row in after_rows if row["ts_code"] == STOCK_B)

        self.assertEqual({row["ts_code"] for row in after_rows}, {STOCK_A, STOCK_B})
        self.assertEqual(unaffected_after, unaffected_before)

    def test_daily_asset_partition_uses_exact_previous_expected_state(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            source_path = gold_stk_mins_qfq_path(lake_root, 1, STOCK_A, 2026)
            _write_rows(
                source_path,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=(
                    _source_rows_for_day("2026-06-15", start_close=10.0)
                    + _source_rows_for_day("2026-06-16", start_close=20.0)
                ),
            )
            write_gold_stk_mins_qfq_macd_kdj_rows(
                lake_root=lake_root,
                freq=1,
                source_qfq_paths=(source_path,),
                target_trade_dates=("2026-06-15",),
            )
            previous_state = gold_stk_mins_qfq_macd_kdj_state_path(
                lake_root,
                1,
                "2026-06-15",
            )

            write_result = write_gold_stk_mins_qfq_macd_kdj_asset_partition(
                lake_root=lake_root,
                freq=1,
                partition_key="2026-06-16",
                previous_expected_trade_date="2026-06-15",
                allow_without_previous_state=False,
            )

        self.assertFalse(write_result.initialized_without_previous_state)
        self.assertEqual(write_result.previous_state_file_path, previous_state)
        self.assertEqual(write_result.trade_date, "2026-06-16")

    def test_daily_asset_partition_fails_without_exact_previous_expected_state(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            source_path = gold_stk_mins_qfq_path(lake_root, 1, STOCK_A, 2026)
            _write_rows(
                source_path,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=(
                    _source_rows_for_day("2026-06-13", start_close=10.0)
                    + _source_rows_for_day("2026-06-16", start_close=20.0)
                ),
            )
            write_gold_stk_mins_qfq_macd_kdj_rows(
                lake_root=lake_root,
                freq=1,
                source_qfq_paths=(source_path,),
                target_trade_dates=("2026-06-13",),
            )
            older_state = gold_stk_mins_qfq_macd_kdj_state_path(
                lake_root,
                1,
                "2026-06-13",
            )
            target_state = gold_stk_mins_qfq_macd_kdj_state_path(
                lake_root,
                1,
                "2026-06-16",
            )

            with self.assertRaises(dg.Failure) as failure:
                write_gold_stk_mins_qfq_macd_kdj_asset_partition(
                    lake_root=lake_root,
                    freq=1,
                    partition_key="2026-06-16",
                    previous_expected_trade_date="2026-06-15",
                    allow_without_previous_state=False,
                )

            self.assertTrue(older_state.exists())
            self.assertFalse(target_state.exists())
        self.assertIn(
            "previous expected state is missing",
            failure.exception.description,
        )

    def test_daily_asset_partition_allows_baseline_without_previous_state(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            source_path = gold_stk_mins_qfq_path(lake_root, 1, STOCK_A, 2014)
            _write_rows(
                source_path,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=_source_rows_for_day(
                    FIRST_EXPECTED_TRADE_DATE,
                    start_close=10.0,
                ),
            )

            write_result = write_gold_stk_mins_qfq_macd_kdj_asset_partition(
                lake_root=lake_root,
                freq=1,
                partition_key=FIRST_EXPECTED_TRADE_DATE,
                previous_expected_trade_date=None,
                allow_without_previous_state=True,
            )

        self.assertTrue(write_result.initialized_without_previous_state)
        self.assertIsNone(write_result.previous_state_file_path)
        self.assertEqual(
            write_result.trade_date,
            FIRST_EXPECTED_TRADE_DATE,
        )

    def test_daily_asset_wrapper_allows_first_expected_without_previous_state(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _ensure_test_lake_root_ready(lake_root)
            _write_calendar_rows(lake_root, (FIRST_EXPECTED_TRADE_DATE,))
            source_path = gold_stk_mins_qfq_path(lake_root, 1, STOCK_A, 2014)
            _write_rows(
                source_path,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=_source_rows_for_day(
                    FIRST_EXPECTED_TRADE_DATE,
                    start_close=10.0,
                ),
            )
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                "cn_a_stock_mins_silver_trade_days",
                [FIRST_EXPECTED_TRADE_DATE],
            )

            with patch(
                "orchestrator.defs.assets.stk_mins_qfq_macd_kdj."
                "assert_gold_stk_mins_qfq_macd_kdj_daily_repair_gate",
            ) as repair_gate:
                result = dg.materialize(
                    [gold_stk_mins_qfq_macd_kdj_1m],
                    partition_key=FIRST_EXPECTED_TRADE_DATE,
                    resources={
                        "lake_root": LakeRootResource(root_path=str(lake_root)),
                        "duckdb": DuckDBResource(),
                    },
                    instance=instance,
                    raise_on_error=True,
                )

            self.assertTrue(result.success)
            repair_gate.assert_called_once_with(instance, FIRST_EXPECTED_TRADE_DATE)
            state_path = gold_stk_mins_qfq_macd_kdj_state_path(
                lake_root,
                1,
                FIRST_EXPECTED_TRADE_DATE,
            )
            self.assertTrue(state_path.exists())

    def test_daily_asset_wrapper_rejects_target_outside_expected_calendar(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _ensure_test_lake_root_ready(lake_root)
            _write_calendar_rows(lake_root, ("2026-06-15",))
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                "cn_a_stock_mins_silver_trade_days",
                ["2026-06-16"],
            )

            with self.assertRaisesRegex(
                (dg.Failure, dg.DagsterExecutionStepExecutionError),
                "not an expected stock minutes trade date",
            ):
                dg.materialize(
                    [gold_stk_mins_qfq_macd_kdj_1m],
                    partition_key="2026-06-16",
                    resources={
                        "lake_root": LakeRootResource(root_path=str(lake_root)),
                        "duckdb": DuckDBResource(),
                    },
                    instance=instance,
                    raise_on_error=True,
                )


if __name__ == "__main__":
    unittest.main()
