import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.assets.stk_mins import (
    write_gold_stk_mins_qfq_derived_asset_partition,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_path,
    raw_stk_mins_path,
    silver_stk_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_SCHEMA,
)


TRADE_DATE = "2026-06-03"
STOCK_A = "600000.SH"


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


def _gold_row(
    trade_time: str,
    *,
    freq: int,
    open_: float,
    high: float | None = None,
    low: float | None = None,
    close: float | None = None,
    vol: float = 100.0,
    amount: float = 1000.0,
    exchange: str = "SSE",
) -> dict[str, object]:
    return {
        "ts_code": STOCK_A,
        "freq": freq,
        "trade_date": TRADE_DATE,
        "trade_time": f"{TRADE_DATE} {trade_time}",
        "open": open_,
        "high": high if high is not None else open_ + 1.0,
        "low": low if low is not None else open_ - 1.0,
        "close": close if close is not None else open_ + 0.5,
        "vol": vol,
        "amount": amount,
        "exchange": exchange,
    }


def _read_gold_rows(path: Path) -> list[dict[str, object]]:
    columns = tuple(column.name for column in GOLD_STK_MINS_QFQ_SCHEMA)
    with duckdb.connect(database=":memory:") as connection:
        rows = connection.execute(
            f"""
            SELECT {", ".join(columns)}
            FROM {read_parquet(path, hive_partitioning=False)}
            ORDER BY trade_time
            """
        ).fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


class StkMinsQfqM11DerivedAssetTests(unittest.TestCase):
    def test_gold_qfq_path_accepts_derived_freqs_but_raw_silver_reject_them(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            self.assertIn(
                "freq=90",
                gold_stk_mins_qfq_path(lake_root, 90, STOCK_A, 2026).as_posix(),
            )
            self.assertIn(
                "freq=120",
                gold_stk_mins_qfq_path(lake_root, 120, STOCK_A, 2026).as_posix(),
            )
            with self.assertRaisesRegex(ValueError, "Unsupported stk_mins freq"):
                raw_stk_mins_path(lake_root, 90, TRADE_DATE)
            with self.assertRaisesRegex(ValueError, "Unsupported stk_mins freq"):
                silver_stk_mins_path(lake_root, 120, TRADE_DATE)

    def test_90m_is_derived_from_30m_qfq_windows(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_rows(
                gold_stk_mins_qfq_path(lake_root, 30, STOCK_A, 2026),
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=[
                    _gold_row("09:30:00", freq=30, open_=9, close=9.5),
                    _gold_row("10:00:00", freq=30, open_=10, close=10.5, vol=1),
                    _gold_row("10:30:00", freq=30, open_=11, close=11.5, vol=2),
                    _gold_row("11:00:00", freq=30, open_=12, high=20, low=8, close=12.5, vol=3),
                    _gold_row("11:30:00", freq=30, open_=13, close=13.5, vol=4),
                    _gold_row("13:30:00", freq=30, open_=14, close=14.5, vol=5),
                    _gold_row("14:00:00", freq=30, open_=15, close=15.5, vol=6),
                    _gold_row("14:30:00", freq=30, open_=16, close=16.5, vol=7),
                    _gold_row("15:00:00", freq=30, open_=17, close=17.5, vol=8),
                ],
            )

            result = write_gold_stk_mins_qfq_derived_asset_partition(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                freq=90,
                partition_key=TRADE_DATE,
            )

            rows = _read_gold_rows(gold_stk_mins_qfq_path(lake_root, 90, STOCK_A, 2026))
        self.assertEqual(result.source_freq, 30)
        self.assertEqual(result.row_count, 3)
        self.assertEqual([row["trade_time"].strftime("%H:%M:%S") for row in rows], [
            "11:00:00",
            "14:00:00",
            "15:00:00",
        ])
        self.assertEqual(rows[0]["open"], 10)
        self.assertEqual(rows[0]["close"], 12.5)
        self.assertEqual(rows[0]["high"], 20)
        self.assertEqual(rows[0]["low"], 8)
        self.assertEqual(rows[0]["vol"], 6)
        self.assertEqual(rows[2]["open"], 16)
        self.assertEqual(rows[2]["close"], 17.5)

    def test_120m_is_derived_from_60m_qfq_complete_windows(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_rows(
                gold_stk_mins_qfq_path(lake_root, 60, STOCK_A, 2026),
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=[
                    _gold_row("09:30:00", freq=60, open_=10, close=10.5, vol=1),
                    _gold_row("10:30:00", freq=60, open_=11, close=11.5, vol=2),
                    _gold_row("11:30:00", freq=60, open_=12, close=12.5, vol=3),
                    _gold_row("14:00:00", freq=60, open_=13, close=13.5, vol=4),
                    _gold_row("15:00:00", freq=60, open_=14, close=14.5, vol=5),
                ],
            )

            result = write_gold_stk_mins_qfq_derived_asset_partition(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                freq=120,
                partition_key=TRADE_DATE,
            )

            rows = _read_gold_rows(gold_stk_mins_qfq_path(lake_root, 120, STOCK_A, 2026))
        self.assertEqual(result.source_freq, 60)
        self.assertEqual(result.row_count, 2)
        self.assertEqual([row["trade_time"].strftime("%H:%M:%S") for row in rows], [
            "10:30:00",
            "14:00:00",
        ])
        self.assertEqual(rows[0]["open"], 10)
        self.assertEqual(rows[0]["close"], 11.5)
        self.assertEqual(rows[0]["vol"], 3)
        self.assertNotIn("15:00:00", [row["trade_time"].strftime("%H:%M:%S") for row in rows])

    def test_derived_generation_fails_when_window_exchange_is_inconsistent(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_rows(
                gold_stk_mins_qfq_path(lake_root, 60, STOCK_A, 2026),
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=[
                    _gold_row("09:30:00", freq=60, open_=10, exchange="SSE"),
                    _gold_row("10:30:00", freq=60, open_=11, exchange="SZSE"),
                ],
            )

            with self.assertRaisesRegex(RuntimeError, "mixed exchanges"):
                write_gold_stk_mins_qfq_derived_asset_partition(
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    freq=120,
                    partition_key=TRADE_DATE,
                )


if __name__ == "__main__":
    unittest.main()
