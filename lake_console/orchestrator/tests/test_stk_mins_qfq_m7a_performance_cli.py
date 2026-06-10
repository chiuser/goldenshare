import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.audits import stk_mins_qfq_performance as qfq_perf
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.paths import silver_adj_factor_path, silver_stk_mins_path
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_STK_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS


TRADE_DATE = "2014-06-03"
PREVIOUS_TRADE_DATE = "2014-06-02"
LATEST_FACTOR_DATE = "2014-06-04"
STOCK_CODE = "600000.SH"


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


def _silver_row(
    *,
    ts_code: str,
    freq: int,
    trade_date: str = TRADE_DATE,
    open_: float = 10.0,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": freq,
        "trade_date": trade_date,
        "trade_time": f"{trade_date} 09:30:00",
        "open": open_,
        "high": open_ + 1,
        "low": open_ - 1,
        "close": open_ + 0.5,
        "vol": 100.0,
        "amount": 1000.0,
        "exchange": "SSE" if ts_code.endswith(".SH") else "SZSE",
    }


def _write_silver_inputs(lake_root: Path) -> None:
    for partition_key in (PREVIOUS_TRADE_DATE, TRADE_DATE):
        for freq in STK_MINS_FREQS:
            _write_rows(
                silver_stk_mins_path(lake_root, freq, partition_key),
                column_types=_column_types(SILVER_STK_MINS_SCHEMA),
                rows=[
                    _silver_row(
                        ts_code=STOCK_CODE,
                        freq=freq,
                        trade_date=partition_key,
                        open_=10.0,
                    ),
                    _silver_row(
                        ts_code="000001.SZ",
                        freq=freq,
                        trade_date=partition_key,
                        open_=20.0,
                    ),
                ],
                order_by="ts_code, trade_time",
            )


def _write_adj_factor_inputs(lake_root: Path) -> None:
    for partition_key, factor in (
        (PREVIOUS_TRADE_DATE, 1.5),
        (TRADE_DATE, 2.0),
        (LATEST_FACTOR_DATE, 4.0),
    ):
        _write_rows(
            silver_adj_factor_path(lake_root, partition_key),
            column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
            rows=[
                {
                    "ts_code": STOCK_CODE,
                    "trade_date": partition_key,
                    "adj_factor": factor,
                },
                {
                    "ts_code": "000001.SZ",
                    "trade_date": partition_key,
                    "adj_factor": factor,
                },
            ],
            order_by="ts_code",
        )


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
            ORDER BY ts_code, trade_time
            """
        ).fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


class StkMinsQfqM7APerformanceCliTests(unittest.TestCase):
    def test_m7a_audit_module_does_not_define_dagster_components(self) -> None:
        text = Path("src/orchestrator/audits/stk_mins_qfq_performance.py").read_text()
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

    def test_dry_run_does_not_write_output_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            lake_root = temp_root / "lake"
            output_dir = temp_root / "out"

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = qfq_perf.main(
                    [
                        "dry-run",
                        "--lake-root",
                        str(lake_root),
                        "--output-dir",
                        str(output_dir),
                        "--trade-date",
                        TRADE_DATE,
                        "--stock-code",
                        STOCK_CODE,
                        "--repair-sample-days",
                        "1",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertFalse(output_dir.exists())
            self.assertIn('"will_write_files": false', stdout.getvalue())
            self.assertIn('"as_of_trade_date": "2014-06-03"', stdout.getvalue())
            self.assertIn('"as_of_adj_factor_path"', stdout.getvalue())
            self.assertNotIn('"latest_adj_factor_path"', stdout.getvalue())

    def test_output_dir_inside_formal_lake_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "data_lake"
            with self.assertRaisesRegex(ValueError, "formal lake root"):
                qfq_perf.assert_output_dir_is_safe(
                    lake_root=lake_root,
                    output_dir=lake_root / "gold" / "quote",
                )

    def test_benchmark_writes_only_output_dir_and_applies_qfq_formula(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            lake_root = temp_root / "lake"
            output_dir = temp_root / "qfq_out"
            _write_silver_inputs(lake_root)
            _write_adj_factor_inputs(lake_root)

            report = qfq_perf.run_qfq_benchmark(
                lake_root=lake_root,
                output_dir=output_dir,
                trade_date=TRADE_DATE,
                stock_code=STOCK_CODE,
                repair_sample_days=(1,),
            )

            self.assertTrue((output_dir / qfq_perf.REPORT_JSON).exists())
            self.assertTrue((output_dir / qfq_perf.REPORT_CSV).exists())
            self.assertFalse((lake_root / "gold").exists())
            self.assertGreater(len(report["metrics"]), 0)

            qfq_path = (
                output_dir
                / "daily_all_market"
                / "freq=1"
                / f"trade_date={TRADE_DATE}"
                / "part-000.parquet"
            )
            rows = _read_rows(qfq_path)
            row = next(item for item in rows if item["ts_code"] == STOCK_CODE)
            self.assertAlmostEqual(row["open"], 10.0)
            self.assertAlmostEqual(row["high"], 11.0)
            self.assertAlmostEqual(row["low"], 9.0)
            self.assertAlmostEqual(row["close"], 10.5)

    def test_partition_rewrite_replaces_only_target_stock_code(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            existing_path = temp_root / "existing.parquet"
            replacement_path = temp_root / "replacement.parquet"
            target_path = temp_root / "target.parquet"
            column_types = _column_types(SILVER_STK_MINS_SCHEMA)
            _write_rows(
                existing_path,
                column_types=column_types,
                rows=[
                    _silver_row(ts_code=STOCK_CODE, freq=1, open_=10.0),
                    _silver_row(ts_code="000001.SZ", freq=1, open_=20.0),
                ],
                order_by="ts_code, trade_time",
            )
            _write_rows(
                replacement_path,
                column_types=column_types,
                rows=[_silver_row(ts_code=STOCK_CODE, freq=1, open_=99.0)],
                order_by="ts_code, trade_time",
            )

            row_count = qfq_perf.rewrite_qfq_partition_for_stock_code(
                existing_partition_path=existing_path,
                replacement_rows_path=replacement_path,
                stock_code=STOCK_CODE,
                target_path=target_path,
            )

            self.assertEqual(row_count, 2)
            rows = _read_rows(target_path)
            by_code = {row["ts_code"]: row for row in rows}
            self.assertAlmostEqual(by_code[STOCK_CODE]["open"], 99.0)
            self.assertAlmostEqual(by_code["000001.SZ"]["open"], 20.0)

    def test_partition_rewrite_rejects_empty_target_stock_replacement(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            existing_path = temp_root / "existing.parquet"
            replacement_path = temp_root / "replacement.parquet"
            target_path = temp_root / "target.parquet"
            column_types = _column_types(SILVER_STK_MINS_SCHEMA)
            _write_rows(
                existing_path,
                column_types=column_types,
                rows=[_silver_row(ts_code=STOCK_CODE, freq=1, open_=10.0)],
                order_by="ts_code, trade_time",
            )
            _write_rows(
                replacement_path,
                column_types=column_types,
                rows=[_silver_row(ts_code="000001.SZ", freq=1, open_=99.0)],
                order_by="ts_code, trade_time",
            )

            with self.assertRaisesRegex(ValueError, "Replacement qfq rows are empty"):
                qfq_perf.rewrite_qfq_partition_for_stock_code(
                    existing_partition_path=existing_path,
                    replacement_rows_path=replacement_path,
                    stock_code=STOCK_CODE,
                    target_path=target_path,
                )
            self.assertFalse(target_path.exists())


if __name__ == "__main__":
    unittest.main()
