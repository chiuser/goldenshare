import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs import stk_mins_qfq as qfq_module
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_STK_MINS_SCHEMA,
)
from orchestrator.defs.stk_mins_qfq import (
    build_adj_factor_changed_codes_sql,
    build_as_of_adj_factor_by_code_sql,
    build_daily_qfq_coverage_sql,
    build_daily_qfq_select_sql,
)


TRADE_DATE = "2014-06-03"
LATEST_DATE = "2014-06-04"


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


def _silver_row(ts_code: str, *, open_: float = 10.0) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": 5,
        "trade_date": TRADE_DATE,
        "trade_time": f"{TRADE_DATE} 09:35:00",
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


def _fetch_dicts(sql: str) -> list[dict[str, object]]:
    with duckdb.connect(database=":memory:") as connection:
        columns = [item[0] for item in connection.execute(f"DESCRIBE ({sql})").fetchall()]
        rows = connection.execute(sql).fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


class StkMinsQfqSqlHelperTests(unittest.TestCase):
    def test_as_of_adj_factor_uses_only_explicit_as_of_paths(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            as_of_path = root / "adj_as_of.parquet"
            future_path = root / "adj_future.parquet"
            _write_rows(
                as_of_path,
                column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
                rows=[
                    _adj_row("600000.SH", TRADE_DATE, 2.0),
                    _adj_row("000001.SZ", TRADE_DATE, 3.0),
                ],
                order_by="ts_code",
            )
            _write_rows(
                future_path,
                column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
                rows=[_adj_row("600000.SH", LATEST_DATE, 4.0)],
                order_by="ts_code",
            )

            rows = _fetch_dicts(
                build_as_of_adj_factor_by_code_sql([as_of_path])
            )

        by_code = {row["ts_code"]: row for row in rows}
        self.assertEqual(by_code["600000.SH"]["as_of_trade_date"].isoformat(), TRADE_DATE)
        self.assertEqual(by_code["600000.SH"]["as_of_adj_factor"], 2.0)
        self.assertEqual(by_code["000001.SZ"]["as_of_trade_date"].isoformat(), TRADE_DATE)
        self.assertEqual(by_code["000001.SZ"]["as_of_adj_factor"], 3.0)
        self.assertFalse(hasattr(qfq_module, "build_latest_adj_factor_by_code_sql"))

    def test_daily_qfq_select_uses_formula_and_preserves_non_price_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            silver_path = root / "silver.parquet"
            trade_adj_path = root / "trade_adj.parquet"
            as_of_adj_path = root / "as_of_adj.parquet"
            future_adj_path = root / "future_adj.parquet"
            _write_rows(
                silver_path,
                column_types=_column_types(SILVER_STK_MINS_SCHEMA),
                rows=[_silver_row("600000.SH", open_=10.0)],
                order_by="ts_code, trade_time",
            )
            _write_rows(
                trade_adj_path,
                column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
                rows=[_adj_row("600000.SH", TRADE_DATE, 2.0)],
                order_by="ts_code",
            )
            _write_rows(
                as_of_adj_path,
                column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
                rows=[_adj_row("600000.SH", TRADE_DATE, 2.0)],
                order_by="ts_code",
            )
            _write_rows(
                future_adj_path,
                column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
                rows=[_adj_row("600000.SH", LATEST_DATE, 4.0)],
                order_by="ts_code",
            )

            sql = build_daily_qfq_select_sql(
                silver_paths=[silver_path],
                trade_adj_factor_paths=[trade_adj_path],
                as_of_adj_factor_paths=[as_of_adj_path],
            )
            with duckdb.connect(database=":memory:") as connection:
                described = connection.execute(f"DESCRIBE ({sql})").fetchall()
                row = connection.execute(sql).fetchone()

        self.assertEqual(
            [(column[0], column[1]) for column in described],
            [(column.name, column.type) for column in GOLD_STK_MINS_QFQ_SCHEMA],
        )
        result = dict(zip((column.name for column in GOLD_STK_MINS_QFQ_SCHEMA), row, strict=True))
        self.assertAlmostEqual(result["open"], 10.0)
        self.assertAlmostEqual(result["high"], 11.0)
        self.assertAlmostEqual(result["low"], 9.0)
        self.assertAlmostEqual(result["close"], 10.5)
        self.assertEqual(result["vol"], 100.0)
        self.assertEqual(result["amount"], 1000.0)
        self.assertEqual(result["exchange"], "SSE")

    def test_daily_qfq_coverage_reports_missing_factors(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            silver_path = root / "silver.parquet"
            trade_adj_path = root / "trade_adj.parquet"
            as_of_adj_path = root / "as_of_adj.parquet"
            _write_rows(
                silver_path,
                column_types=_column_types(SILVER_STK_MINS_SCHEMA),
                rows=[
                    _silver_row("600000.SH"),
                    _silver_row("000001.SZ", open_=20.0),
                    _silver_row("300001.SZ", open_=30.0),
                ],
                order_by="ts_code, trade_time",
            )
            _write_rows(
                trade_adj_path,
                column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
                rows=[
                    _adj_row("600000.SH", TRADE_DATE, 2.0),
                    _adj_row("000001.SZ", TRADE_DATE, 2.0),
                ],
                order_by="ts_code",
            )
            _write_rows(
                as_of_adj_path,
                column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
                rows=[
                    _adj_row("600000.SH", TRADE_DATE, 2.0),
                    _adj_row("300001.SZ", TRADE_DATE, 4.0),
                ],
                order_by="ts_code",
            )

            rows = _fetch_dicts(
                build_daily_qfq_coverage_sql(
                    silver_paths=[silver_path],
                    trade_adj_factor_paths=[trade_adj_path],
                    as_of_adj_factor_paths=[as_of_adj_path],
                )
            )

        self.assertEqual(rows[0]["silver_row_count"], 3)
        self.assertEqual(rows[0]["qfq_output_row_count"], 1)
        self.assertEqual(rows[0]["missing_trade_adj_factor_row_count"], 1)
        self.assertEqual(rows[0]["missing_as_of_adj_factor_row_count"], 1)

    def test_changed_code_detection_omits_unchanged_codes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current_path = root / "current.parquet"
            previous_path = root / "previous.parquet"
            _write_rows(
                current_path,
                column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
                rows=[
                    _adj_row("600000.SH", TRADE_DATE, 2.0),
                    _adj_row("000001.SZ", TRADE_DATE, 3.0),
                    _adj_row("300001.SZ", TRADE_DATE, 4.0),
                ],
                order_by="ts_code",
            )
            _write_rows(
                previous_path,
                column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
                rows=[
                    _adj_row("600000.SH", "2014-06-02", 2.0),
                    _adj_row("000001.SZ", "2014-06-02", 2.5),
                ],
                order_by="ts_code",
            )

            rows = _fetch_dicts(
                build_adj_factor_changed_codes_sql(
                    current_adj_factor_path=current_path,
                    previous_adj_factor_path=previous_path,
                )
            )

        self.assertEqual(
            [(row["ts_code"], row["change_reason"]) for row in rows],
            [
                ("000001.SZ", "factor_changed"),
                ("300001.SZ", "new_current_code"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
