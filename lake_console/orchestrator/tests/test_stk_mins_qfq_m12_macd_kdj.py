import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_macd_kdj_path,
    gold_stk_mins_qfq_macd_kdj_state_path,
    gold_stk_mins_qfq_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
    GOLD_STK_MINS_QFQ_SCHEMA,
)
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    SEGMENT_BAR_COUNT,
    write_gold_stk_mins_qfq_macd_kdj_rows,
)


STOCK_A = "600000.SH"
STOCK_B = "000001.SZ"


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


if __name__ == "__main__":
    unittest.main()
