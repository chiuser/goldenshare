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
    write_gold_stk_mins_qfq_macd_kdj_rows,
)


STOCK_A = "600000.SH"
STOCK_B = "000001.SZ"
DAY_1 = "2026-06-15"
DAY_2 = "2026-06-16"


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
        definitions = ", ".join(
            f'"{column}" {column_types[column]}' for column in columns
        )
        connection.execute(f"CREATE TEMP TABLE rows_to_write ({definitions})")
        placeholders = ", ".join("?" for _column in columns)
        connection.executemany(
            f"INSERT INTO rows_to_write VALUES ({placeholders})",
            [[row.get(column) for column in columns] for row in rows],
        )
        select_columns = ", ".join(
            f'CAST("{column}" AS {column_types[column]}) AS "{column}"'
            for column in columns
        )
        connection.execute(
            copy_query_to_parquet(
                f"SELECT {select_columns} FROM rows_to_write ORDER BY {order_by}",
                path,
            )
        )


def _qfq_row(
    *,
    ts_code: str,
    trade_date: str,
    close: float,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": 1,
        "trade_date": trade_date,
        "trade_time": f"{trade_date} 09:31:00",
        "open": close - 0.1,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "vol": 100.0,
        "amount": 1000.0,
        "exchange": "SSE",
    }


def _read_rows(path: Path, schema) -> list[dict[str, object]]:
    columns = tuple(column.name for column in schema)
    with duckdb.connect(database=":memory:") as connection:
        rows = connection.execute(
            f"SELECT {', '.join(columns)} FROM {read_parquet(path, hive_partitioning=False)} "
            "ORDER BY trade_date, ts_code"
        ).fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


class StkMinsQfqMacdKdjFormulaGoldenContractsTests(unittest.TestCase):
    def test_initial_and_incremental_state_have_literal_indicator_values(self) -> None:
        # These expected values are manually derived from MACD 12/26/9 and KDJ 9/3/3:
        # day 1 initializes EMA with close=10 and K/D with 50; day 2 uses close=13,
        # prior high/low 11/9, and therefore RSV=80.
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            source_path = gold_stk_mins_qfq_path(lake_root, 1, STOCK_A, 2026)
            _write_rows(
                source_path,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=[
                    _qfq_row(ts_code=STOCK_A, trade_date=DAY_1, close=10.0),
                    _qfq_row(ts_code=STOCK_A, trade_date=DAY_2, close=13.0),
                ],
                order_by="trade_time",
            )

            write_gold_stk_mins_qfq_macd_kdj_rows(
                lake_root=lake_root,
                freq=1,
                source_qfq_paths=[source_path],
                target_trade_dates=[DAY_1],
            )
            previous_state_path = gold_stk_mins_qfq_macd_kdj_state_path(
                lake_root, 1, DAY_1
            )
            write_gold_stk_mins_qfq_macd_kdj_rows(
                lake_root=lake_root,
                freq=1,
                source_qfq_paths=[source_path],
                target_trade_dates=[DAY_2],
                previous_state_paths=[previous_state_path],
            )
            indicator_rows = _read_rows(
                gold_stk_mins_qfq_macd_kdj_path(lake_root, 1, STOCK_A, 2026),
                GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA,
            )
            state_rows = _read_rows(
                gold_stk_mins_qfq_macd_kdj_state_path(lake_root, 1, DAY_2),
                GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
            )

        first, second = indicator_rows
        self.assertAlmostEqual(first["macd_dif_qfq"], 0.0, places=12)
        self.assertAlmostEqual(first["macd_dea_qfq"], 0.0, places=12)
        self.assertAlmostEqual(first["macd_qfq"], 0.0, places=12)
        self.assertAlmostEqual(first["kdj_k_qfq"], 50.0, places=12)
        self.assertAlmostEqual(first["kdj_d_qfq"], 50.0, places=12)
        self.assertAlmostEqual(first["kdj_qfq"], 50.0, places=12)

        self.assertAlmostEqual(second["macd_dif_qfq"], 0.23931623931623935, places=12)
        self.assertAlmostEqual(second["macd_dea_qfq"], 0.04786324786324787, places=12)
        self.assertAlmostEqual(second["macd_qfq"], 0.38290598290598296, places=12)
        self.assertAlmostEqual(second["kdj_k_qfq"], 60.0, places=12)
        self.assertAlmostEqual(second["kdj_d_qfq"], 53.333333333333336, places=12)
        self.assertAlmostEqual(second["kdj_qfq"], 73.33333333333333, places=12)

        self.assertEqual(len(state_rows), 1)
        state = state_rows[0]
        self.assertAlmostEqual(state["macd_ema_fast"], 10.461538461538462, places=12)
        self.assertAlmostEqual(state["macd_ema_slow"], 10.222222222222221, places=12)
        self.assertAlmostEqual(state["macd_dea"], 0.04786324786324787, places=12)
        self.assertAlmostEqual(state["kdj_k"], 60.0, places=12)
        self.assertAlmostEqual(state["kdj_d"], 53.333333333333336, places=12)

    def test_scoped_repair_preserves_unselected_state_rows(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            source_a = gold_stk_mins_qfq_path(lake_root, 1, STOCK_A, 2026)
            source_b = gold_stk_mins_qfq_path(lake_root, 1, STOCK_B, 2026)
            _write_rows(
                source_a,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=[
                    _qfq_row(ts_code=STOCK_A, trade_date=DAY_1, close=10.0),
                    _qfq_row(ts_code=STOCK_A, trade_date=DAY_2, close=13.0),
                ],
                order_by="trade_time",
            )
            _write_rows(
                source_b,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=[
                    _qfq_row(ts_code=STOCK_B, trade_date=DAY_1, close=20.0),
                    _qfq_row(ts_code=STOCK_B, trade_date=DAY_2, close=23.0),
                ],
                order_by="trade_time",
            )
            write_gold_stk_mins_qfq_macd_kdj_rows(
                lake_root=lake_root,
                freq=1,
                source_qfq_paths=[source_a, source_b],
                target_trade_dates=[DAY_1],
            )
            previous_state_path = gold_stk_mins_qfq_macd_kdj_state_path(
                lake_root, 1, DAY_1
            )
            write_gold_stk_mins_qfq_macd_kdj_rows(
                lake_root=lake_root,
                freq=1,
                source_qfq_paths=[source_a, source_b],
                target_trade_dates=[DAY_2],
                previous_state_paths=[previous_state_path],
            )
            state_path = gold_stk_mins_qfq_macd_kdj_state_path(lake_root, 1, DAY_2)
            before = _read_rows(state_path, GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA)

            _write_rows(
                source_a,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=[
                    _qfq_row(ts_code=STOCK_A, trade_date=DAY_1, close=10.0),
                    _qfq_row(ts_code=STOCK_A, trade_date=DAY_2, close=15.0),
                ],
                order_by="trade_time",
            )
            write_gold_stk_mins_qfq_macd_kdj_rows(
                lake_root=lake_root,
                freq=1,
                source_qfq_paths=[source_a, source_b],
                target_trade_dates=[DAY_2],
                previous_state_paths=[previous_state_path],
                stock_codes=[STOCK_A],
            )
            after = _read_rows(state_path, GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA)

        before_b = next(row for row in before if row["ts_code"] == STOCK_B)
        after_b = next(row for row in after if row["ts_code"] == STOCK_B)
        self.assertEqual(after_b, before_b)


if __name__ == "__main__":
    unittest.main()
