import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.paths import gold_stk_mins_qfq_path
from orchestrator.defs.run_contracts.asset_column_schemas import GOLD_STK_MINS_QFQ_SCHEMA
from orchestrator.defs.stk_mins_qfq import (
    rewrite_qfq_year_file_for_stock_code,
    write_gold_stk_mins_qfq_rows_to_year_files,
)


STOCK_CODE = "600000.SH"


def _column_types(schema) -> dict[str, str]:
    return {column.name: column.type for column in schema}


def _write_rows(
    path: Path,
    *,
    rows: list[dict[str, object]],
    order_by: str = "trade_date, trade_time",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(column.name for column in GOLD_STK_MINS_QFQ_SCHEMA)
    column_types = _column_types(GOLD_STK_MINS_QFQ_SCHEMA)
    with duckdb.connect(database=":memory:") as connection:
        column_defs = ", ".join(f'"{column}" {column_types[column]}' for column in columns)
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
    *,
    ts_code: str = STOCK_CODE,
    freq: int = 5,
    trade_date: str = "2014-06-03",
    trade_time: str | None = None,
    open_: float = 10.0,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": freq,
        "trade_date": trade_date,
        "trade_time": trade_time or f"{trade_date} 09:35:00",
        "open": open_,
        "high": open_ + 1.0,
        "low": open_ - 1.0,
        "close": open_ + 0.5,
        "vol": 100.0,
        "amount": 1000.0,
        "exchange": "SSE" if ts_code.endswith(".SH") else "SZSE",
    }


def _select_from_parquet(path: Path) -> str:
    return f"SELECT * FROM {read_parquet(path, hive_partitioning=False)}"


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


class StkMinsQfqPartitionRewriteTests(unittest.TestCase):
    def test_write_creates_stock_year_files_for_multiple_stocks_and_years(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "replacement.parquet"
            lake_root = root / "lake"
            _write_rows(
                source_path,
                rows=[
                    _qfq_row(ts_code=STOCK_CODE, trade_date="2014-06-03", open_=10.0),
                    _qfq_row(ts_code="000001.SZ", trade_date="2015-01-05", open_=20.0),
                ],
                order_by="ts_code, trade_time",
            )

            results = write_gold_stk_mins_qfq_rows_to_year_files(
                lake_root=lake_root,
                freq=5,
                qfq_select_sql=_select_from_parquet(source_path),
                replace_trade_dates=("2014-06-03", "2015-01-05"),
            )

            self.assertEqual(len(results), 2)
            self.assertTrue(gold_stk_mins_qfq_path(lake_root, 5, STOCK_CODE, 2014).exists())
            self.assertTrue(gold_stk_mins_qfq_path(lake_root, 5, "000001.SZ", 2015).exists())

    def test_write_replaces_only_target_trade_date_and_preserves_history(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = root / "lake"
            target_path = gold_stk_mins_qfq_path(lake_root, 5, STOCK_CODE, 2014)
            replacement_path = root / "replacement.parquet"
            _write_rows(
                target_path,
                rows=[
                    _qfq_row(trade_date="2014-06-02", open_=8.0),
                    _qfq_row(trade_date="2014-06-03", open_=9.0),
                ],
            )
            _write_rows(
                replacement_path,
                rows=[_qfq_row(trade_date="2014-06-03", open_=99.0)],
            )

            result = rewrite_qfq_year_file_for_stock_code(
                lake_root=lake_root,
                freq=5,
                stock_code=STOCK_CODE,
                year=2014,
                replacement_select_sql=_select_from_parquet(replacement_path),
                replace_trade_dates=("2014-06-03",),
            )

            self.assertEqual(result.path, target_path)
            rows = _read_rows(target_path)
            self.assertEqual(len(rows), 2)
            self.assertAlmostEqual(rows[0]["open"], 8.0)
            self.assertAlmostEqual(rows[1]["open"], 99.0)

    def test_write_rejects_empty_replacement_rows(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            replacement_path = root / "empty.parquet"
            _write_rows(replacement_path, rows=[])

            with self.assertRaisesRegex(ValueError, "replacement rows are empty"):
                write_gold_stk_mins_qfq_rows_to_year_files(
                    lake_root=root / "lake",
                    freq=5,
                    qfq_select_sql=_select_from_parquet(replacement_path),
                    replace_trade_dates=("2014-06-03",),
                )

    def test_write_rejects_duplicate_business_keys(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            replacement_path = root / "duplicate.parquet"
            _write_rows(
                replacement_path,
                rows=[
                    _qfq_row(open_=10.0),
                    _qfq_row(open_=11.0),
                ],
            )

            with self.assertRaisesRegex(ValueError, "duplicate ts_code \\+ trade_time"):
                write_gold_stk_mins_qfq_rows_to_year_files(
                    lake_root=root / "lake",
                    freq=5,
                    qfq_select_sql=_select_from_parquet(replacement_path),
                    replace_trade_dates=("2014-06-03",),
                )

    def test_write_rejects_wrong_freq(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            replacement_path = root / "wrong_freq.parquet"
            _write_rows(replacement_path, rows=[_qfq_row(freq=15)])

            with self.assertRaisesRegex(ValueError, "do not match the target freq"):
                write_gold_stk_mins_qfq_rows_to_year_files(
                    lake_root=root / "lake",
                    freq=5,
                    qfq_select_sql=_select_from_parquet(replacement_path),
                    replace_trade_dates=("2014-06-03",),
                )

    def test_repair_wrapper_rejects_wrong_stock_or_year_scope(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wrong_stock_path = root / "wrong_stock.parquet"
            wrong_year_path = root / "wrong_year.parquet"
            _write_rows(
                wrong_stock_path,
                rows=[_qfq_row(ts_code="000001.SZ", trade_date="2014-06-03")],
            )
            _write_rows(
                wrong_year_path,
                rows=[_qfq_row(ts_code=STOCK_CODE, trade_date="2015-01-05")],
            )

            with self.assertRaisesRegex(ValueError, "exactly one stock code and year"):
                rewrite_qfq_year_file_for_stock_code(
                    lake_root=root / "lake",
                    freq=5,
                    stock_code=STOCK_CODE,
                    year=2014,
                    replacement_select_sql=_select_from_parquet(wrong_stock_path),
                    replace_trade_dates=("2014-06-03",),
                )
            with self.assertRaisesRegex(ValueError, "exactly one stock code and year"):
                rewrite_qfq_year_file_for_stock_code(
                    lake_root=root / "lake",
                    freq=5,
                    stock_code=STOCK_CODE,
                    year=2014,
                    replacement_select_sql=_select_from_parquet(wrong_year_path),
                    replace_trade_dates=("2015-01-05",),
                )

    def test_write_rejects_existing_file_that_does_not_match_path_scope(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = root / "lake"
            target_path = gold_stk_mins_qfq_path(lake_root, 5, STOCK_CODE, 2014)
            replacement_path = root / "replacement.parquet"
            _write_rows(
                target_path,
                rows=[_qfq_row(ts_code="000001.SZ", trade_date="2014-06-02")],
            )
            _write_rows(
                replacement_path,
                rows=[_qfq_row(ts_code=STOCK_CODE, trade_date="2014-06-03")],
            )

            with self.assertRaisesRegex(ValueError, "do not match its freq/ts_code/year path"):
                write_gold_stk_mins_qfq_rows_to_year_files(
                    lake_root=lake_root,
                    freq=5,
                    qfq_select_sql=_select_from_parquet(replacement_path),
                    replace_trade_dates=("2014-06-03",),
                )

    def test_helper_module_does_not_define_dagster_components(self) -> None:
        text = Path("src/orchestrator/defs/stk_mins_qfq.py").read_text()
        forbidden_tokens = (
            "import dagster",
            "from dagster",
            "@dg.asset",
            "@dg.asset_check",
            "@dg.sensor",
            "define_asset_job",
        )
        for token in forbidden_tokens:
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
