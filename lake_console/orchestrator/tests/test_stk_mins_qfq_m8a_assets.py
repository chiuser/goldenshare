import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.assets.stk_mins import (
    write_gold_stk_mins_qfq_asset_partition,
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


TRADE_DATE = "2014-06-03"
LATEST_DATE = "2014-06-04"


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


def _silver_rows(ts_code: str, *, open_: float) -> list[dict[str, object]]:
    session_minutes = (
        tuple(range(9 * 60 + 30, 11 * 60 + 31))
        + tuple(range(13 * 60 + 1, 15 * 60 + 1))
    )
    return [
        {
            "ts_code": ts_code,
            "freq": 1,
            "trade_date": TRADE_DATE,
            "trade_time": (
                f"{TRADE_DATE} {minute // 60:02d}:{minute % 60:02d}:00"
            ),
            "open": open_,
            "high": open_ + 1.0,
            "low": open_ - 1.0,
            "close": open_ + 0.5,
            "vol": 100.0,
            "amount": 1000.0,
            "exchange": "SSE" if ts_code.endswith(".SH") else "SZSE",
        }
        for minute in session_minutes
    ]


def _adj_row(ts_code: str, trade_date: str, adj_factor: float) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "adj_factor": adj_factor,
    }


def _gold_row(
    *,
    ts_code: str = "600000.SH",
    trade_date: str = "2014-06-02",
    open_: float = 8.0,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": 5,
        "trade_date": trade_date,
        "trade_time": f"{trade_date} 09:35:00",
        "open": open_,
        "high": open_ + 1.0,
        "low": open_ - 1.0,
        "close": open_ + 0.5,
        "vol": 100.0,
        "amount": 1000.0,
        "exchange": "SSE",
    }


def _read_rows(path: Path) -> list[dict[str, object]]:
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


class StkMinsQfqM8AAssetTests(unittest.TestCase):
    def test_write_gold_qfq_asset_partition_writes_stock_year_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "lake"
            _write_rows(
                silver_stk_mins_path(lake_root, 1, TRADE_DATE),
                schema=SILVER_STK_MINS_SCHEMA,
                rows=[
                    *_silver_rows("600000.SH", open_=10.0),
                    *_silver_rows("000001.SZ", open_=30.0),
                ],
                order_by="ts_code, trade_time",
            )
            _write_rows(
                silver_adj_factor_path(lake_root, TRADE_DATE),
                schema=SILVER_ADJ_FACTOR_SCHEMA,
                rows=[
                    _adj_row("600000.SH", TRADE_DATE, 2.0),
                    _adj_row("000001.SZ", TRADE_DATE, 3.0),
                ],
                order_by="ts_code",
            )
            _write_rows(
                silver_adj_factor_path(lake_root, LATEST_DATE),
                schema=SILVER_ADJ_FACTOR_SCHEMA,
                rows=[
                    _adj_row("600000.SH", LATEST_DATE, 4.0),
                    _adj_row("000001.SZ", LATEST_DATE, 6.0),
                ],
                order_by="ts_code",
            )

            result = write_gold_stk_mins_qfq_asset_partition(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                freq=5,
                partition_key=TRADE_DATE,
            )

            sh_path = gold_stk_mins_qfq_path(lake_root, 5, "600000.SH", 2014)
            sz_path = gold_stk_mins_qfq_path(lake_root, 5, "000001.SZ", 2014)
            self.assertTrue(sh_path.exists())
            self.assertTrue(sz_path.exists())
            self.assertEqual(result.row_count, 96)
            self.assertEqual(result.output_file_count, 2)
            self.assertEqual(result.replacement_row_count, 96)
            self.assertEqual(result.output_root_path.name, "freq=5")
            self.assertEqual(result.observed_columns, tuple(column.name for column in GOLD_STK_MINS_QFQ_SCHEMA))
            metadata = result.materialization_extra_metadata(
                partition_key=TRADE_DATE,
                freq=5,
            )
            self.assertEqual(metadata["as_of_trade_date"], TRADE_DATE)
            self.assertEqual(
                metadata["as_of_adj_factor_file_path"],
                str(silver_adj_factor_path(lake_root, TRADE_DATE)),
            )
            self.assertNotIn("latest_adj_factor_file_count", metadata)
            self.assertNotIn("latest_adj_factor_date", metadata)

            sh_rows = _read_rows(sh_path)
            sz_rows = _read_rows(sz_path)
            self.assertAlmostEqual(sh_rows[0]["open"], 10.5)
            self.assertAlmostEqual(sz_rows[0]["open"], 30.5)
            self.assertEqual(sh_rows[0]["vol"], 600.0)
            self.assertEqual(sz_rows[0]["exchange"], "SZSE")

    def test_write_preserves_other_dates_in_existing_stock_year_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "lake"
            target_path = gold_stk_mins_qfq_path(lake_root, 5, "600000.SH", 2014)
            _write_rows(
                target_path,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=[_gold_row(trade_date="2014-06-02", open_=8.0)],
                order_by="trade_date, trade_time",
            )
            _write_rows(
                silver_stk_mins_path(lake_root, 1, TRADE_DATE),
                schema=SILVER_STK_MINS_SCHEMA,
                rows=_silver_rows("600000.SH", open_=10.0),
                order_by="ts_code, trade_time",
            )
            _write_rows(
                silver_adj_factor_path(lake_root, TRADE_DATE),
                schema=SILVER_ADJ_FACTOR_SCHEMA,
                rows=[_adj_row("600000.SH", TRADE_DATE, 2.0)],
                order_by="ts_code",
            )
            _write_rows(
                silver_adj_factor_path(lake_root, LATEST_DATE),
                schema=SILVER_ADJ_FACTOR_SCHEMA,
                rows=[_adj_row("600000.SH", LATEST_DATE, 4.0)],
                order_by="ts_code",
            )

            write_gold_stk_mins_qfq_asset_partition(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                freq=5,
                partition_key=TRADE_DATE,
            )

            rows = _read_rows(target_path)
            self.assertEqual(len(rows), 49)
            self.assertEqual(rows[0]["trade_date"].isoformat(), "2014-06-02")
            self.assertAlmostEqual(rows[0]["open"], 8.0)
            self.assertEqual(rows[1]["trade_date"].isoformat(), TRADE_DATE)
            self.assertAlmostEqual(rows[1]["open"], 10.5)

    def test_write_fails_when_trade_adj_factor_partition_is_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "lake"
            _write_rows(
                silver_stk_mins_path(lake_root, 1, TRADE_DATE),
                schema=SILVER_STK_MINS_SCHEMA,
                rows=_silver_rows("600000.SH", open_=10.0),
                order_by="ts_code, trade_time",
            )
            _write_rows(
                silver_adj_factor_path(lake_root, LATEST_DATE),
                schema=SILVER_ADJ_FACTOR_SCHEMA,
                rows=[_adj_row("600000.SH", LATEST_DATE, 4.0)],
                order_by="ts_code",
            )

            with self.assertRaisesRegex(FileNotFoundError, "trade_adj_factor"):
                write_gold_stk_mins_qfq_asset_partition(
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    freq=5,
                    partition_key=TRADE_DATE,
                )

    def test_write_fails_when_factor_coverage_is_incomplete(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "lake"
            _write_rows(
                silver_stk_mins_path(lake_root, 1, TRADE_DATE),
                schema=SILVER_STK_MINS_SCHEMA,
                rows=[
                    *_silver_rows("600000.SH", open_=10.0),
                    *_silver_rows("000001.SZ", open_=30.0),
                ],
                order_by="ts_code, trade_time",
            )
            _write_rows(
                silver_adj_factor_path(lake_root, TRADE_DATE),
                schema=SILVER_ADJ_FACTOR_SCHEMA,
                rows=[_adj_row("600000.SH", TRADE_DATE, 2.0)],
                order_by="ts_code",
            )

            with self.assertRaisesRegex(RuntimeError, "factor coverage failed"):
                write_gold_stk_mins_qfq_asset_partition(
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    freq=5,
                    partition_key=TRADE_DATE,
                )


if __name__ == "__main__":
    unittest.main()
