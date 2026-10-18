import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.duckdb_connection import DuckDBConnectionSettings
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
    def test_seven_frequencies_keep_literal_values_and_state_across_years(self) -> None:
        # Retains the old 25-stock tests' six literal values without their planner.
        # MACD 12/26/9: seed=5, next close=7.5 gives DIF=70/351, DEA=14/351.
        # KDJ 9/3/3: high=8.25, prior low=4.5 => RSV=80; initial K/D=50.
        # A second 7.5 close gives EMA=965/169,3905/729, independently calculated.
        dates = ("2023-12-29", "2024-01-02", "2025-01-02", "2026-01-05")
        fields = ("macd_dif_qfq", "macd_dea_qfq", "macd_qfq", "kdj_k_qfq", "kdj_d_qfq", "kdj_qfq")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = DuckDBConnectionSettings(temp_directory=root / "duckdb")
            for freq, first_time in (
                (1, "09:30:00"), (5, "09:35:00"), (15, "09:45:00"),
                (30, "10:00:00"), (60, "10:30:00"), (90, "11:00:00"), (120, "11:30:00"),
            ):
                with self.subTest(freq=freq):
                    sources = []
                    for day, close, high, low in (
                        (dates[0], 5.0, 5.5, 4.5),
                        (dates[1], 7.5, 8.25, 6.75),
                        (dates[3], 7.5, 8.25, 6.75),
                    ):
                        path = gold_stk_mins_qfq_path(root, freq, STOCK_A, day[:4])
                        row = _qfq_row(ts_code=STOCK_A, trade_date=day, close=close)
                        row.update(freq=freq, trade_time=f"{day} {first_time}",
                                   open=close, high=high, low=low)
                        _write_rows(path, schema=GOLD_STK_MINS_QFQ_SCHEMA,
                                    rows=[row], order_by="trade_time")
                        sources.append(path)
                    previous = ()
                    for target_dates in ([dates[0]], [dates[1], dates[2]], [dates[3]]):
                        write_gold_stk_mins_qfq_macd_kdj_rows(
                            lake_root=root, freq=freq, source_qfq_paths=sources,
                            target_trade_dates=target_dates, previous_state_paths=previous,
                            duckdb_settings=settings)
                        previous = (gold_stk_mins_qfq_macd_kdj_state_path(root, freq, target_dates[-1]),)
                    second = _read_rows(gold_stk_mins_qfq_macd_kdj_path(root, freq, STOCK_A, 2024),
                                        GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA)
                    self.assertEqual(len(second), 1)
                    for field, expected in zip(fields, (
                        0.19943019943019943, 0.039886039886039886, 0.3190883190883191,
                        60.0, 53.33333333333333, 73.33333333333333,
                    ), strict=True):
                        self.assertAlmostEqual(second[0][field], expected, places=12)
                    state_2024, state_2025 = [
                        _read_rows(gold_stk_mins_qfq_macd_kdj_state_path(root, freq, day),
                                   GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA)[0]
                        for day in dates[1:3]
                    ]
                    self.assertEqual(state_2025, {**state_2024, "trade_date": state_2025["trade_date"]})
                    self.assertEqual(state_2025["trade_date"].isoformat(), "2025-01-02")
                    self.assertEqual(state_2025["last_trade_time"].isoformat(sep=" "), f"2024-01-02 {first_time}")
                    self.assertAlmostEqual(state_2025["macd_ema_fast"], 5.384615384615385, places=12)
                    self.assertAlmostEqual(state_2025["macd_ema_slow"], 5.185185185185185, places=12)
                    self.assertFalse(gold_stk_mins_qfq_macd_kdj_path(root, freq, STOCK_A, 2025).exists())
                    third = _read_rows(gold_stk_mins_qfq_macd_kdj_path(root, freq, STOCK_A, 2026),
                                       GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA)
                    self.assertEqual(len(third), 1)
                    for field, expected in zip(fields, (
                        0.3534062223520913, 0.10259007637925018, 0.5016322919456823,
                        66.66666666666667, 57.77777777777778, 84.44444444444444,
                    ), strict=True):
                        self.assertAlmostEqual(third[0][field], expected, places=12)

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
                duckdb_settings=DuckDBConnectionSettings(temp_directory=lake_root / "duckdb"),
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
                duckdb_settings=DuckDBConnectionSettings(temp_directory=lake_root / "duckdb"),
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
                duckdb_settings=DuckDBConnectionSettings(temp_directory=lake_root / "duckdb"),
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
                duckdb_settings=DuckDBConnectionSettings(temp_directory=lake_root / "duckdb"),
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
                duckdb_settings=DuckDBConnectionSettings(temp_directory=lake_root / "duckdb"),
            )
            after = _read_rows(state_path, GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA)

        before_b = next(row for row in before if row["ts_code"] == STOCK_B)
        after_b = next(row for row in after if row["ts_code"] == STOCK_B)
        self.assertEqual(after_b, before_b)


if __name__ == "__main__":
    unittest.main()
