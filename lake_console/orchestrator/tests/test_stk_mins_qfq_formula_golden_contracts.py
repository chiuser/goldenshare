import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_STK_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_QFQ_NATIVE_FREQS
from orchestrator.defs.stk_mins_qfq import (
    build_daily_qfq_coverage_sql,
    build_daily_qfq_select_sql,
    build_gold_stk_mins_qfq_derived_diagnostics_sql,
    build_gold_stk_mins_qfq_derived_select_sql,
)


STOCK_CODE = "600000.SH"
TRADE_DATE = "2026-06-16"
PREVIOUS_TRADE_DATE = "2026-06-15"


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
        if rows:
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


def _silver_row(
    *,
    trade_date: str,
    trade_time: str,
    freq: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    vol: float = 100.0,
    amount: float = 1000.0,
    exchange: str = "SSE",
) -> dict[str, object]:
    return {
        "ts_code": STOCK_CODE,
        "freq": freq,
        "trade_date": trade_date,
        "trade_time": f"{trade_date} {trade_time}",
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "vol": vol,
        "amount": amount,
        "exchange": exchange,
    }


def _adj_factor_row(trade_date: str, factor: float) -> dict[str, object]:
    return {
        "ts_code": STOCK_CODE,
        "trade_date": trade_date,
        "adj_factor": factor,
    }


def _query_rows(sql: str) -> list[dict[str, object]]:
    with duckdb.connect(database=":memory:") as connection:
        result = connection.execute(sql)
        columns = [column[0] for column in result.description]
        rows = result.fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


class StkMinsQfqFormulaGoldenContractsTests(unittest.TestCase):
    def test_daily_qfq_uses_same_day_factor_for_all_native_freqs(self) -> None:
        # Expected prices are manually verified: 10/11/9/10.5 * 6 / 3.
        for freq in STK_MINS_QFQ_NATIVE_FREQS:
            with self.subTest(freq=freq), TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                silver_path = root / "silver.parquet"
                trade_factor_path = root / "trade_factor.parquet"
                as_of_factor_path = root / "as_of_factor.parquet"
                _write_rows(
                    silver_path,
                    schema=SILVER_STK_MINS_SCHEMA,
                    rows=[
                        _silver_row(
                            trade_date=TRADE_DATE,
                            trade_time="09:30:00",
                            freq=freq,
                            open_=10.0,
                            high=11.0,
                            low=9.0,
                            close=10.5,
                        )
                    ],
                    order_by="trade_time",
                )
                _write_rows(
                    trade_factor_path,
                    schema=SILVER_ADJ_FACTOR_SCHEMA,
                    rows=[_adj_factor_row(TRADE_DATE, 6.0)],
                    order_by="ts_code",
                )
                _write_rows(
                    as_of_factor_path,
                    schema=SILVER_ADJ_FACTOR_SCHEMA,
                    rows=[_adj_factor_row(TRADE_DATE, 3.0)],
                    order_by="ts_code",
                )

                rows = _query_rows(
                    build_daily_qfq_select_sql(
                        silver_paths=[silver_path],
                        trade_adj_factor_paths=[trade_factor_path],
                        as_of_adj_factor_paths=[as_of_factor_path],
                    )
                )

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["freq"], freq)
            self.assertEqual(rows[0]["ts_code"], STOCK_CODE)
            self.assertEqual(rows[0]["trade_date"].isoformat(), TRADE_DATE)
            self.assertEqual(rows[0]["open"], 20.0)
            self.assertEqual(rows[0]["high"], 22.0)
            self.assertEqual(rows[0]["low"], 18.0)
            self.assertEqual(rows[0]["close"], 21.0)
            self.assertEqual(rows[0]["vol"], 100.0)
            self.assertEqual(rows[0]["amount"], 1000.0)
            self.assertEqual(rows[0]["exchange"], "SSE")

    def test_factor_repair_uses_trigger_factor_as_explicit_denominator(self) -> None:
        # Expected prices are manually verified: previous 10 * 2 / 4 = 5;
        # target 20 * 4 / 4 = 20.
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            silver_path = root / "silver.parquet"
            trade_factor_path = root / "trade_factor.parquet"
            repair_factor_path = root / "repair_factor.parquet"
            _write_rows(
                silver_path,
                schema=SILVER_STK_MINS_SCHEMA,
                rows=[
                    _silver_row(
                        trade_date=PREVIOUS_TRADE_DATE,
                        trade_time="09:30:00",
                        freq=1,
                        open_=10.0,
                        high=11.0,
                        low=9.0,
                        close=10.5,
                    ),
                    _silver_row(
                        trade_date=TRADE_DATE,
                        trade_time="09:30:00",
                        freq=1,
                        open_=20.0,
                        high=22.0,
                        low=18.0,
                        close=21.0,
                    ),
                ],
                order_by="trade_date, trade_time",
            )
            _write_rows(
                trade_factor_path,
                schema=SILVER_ADJ_FACTOR_SCHEMA,
                rows=[
                    _adj_factor_row(PREVIOUS_TRADE_DATE, 2.0),
                    _adj_factor_row(TRADE_DATE, 4.0),
                ],
                order_by="trade_date",
            )
            _write_rows(
                repair_factor_path,
                schema=SILVER_ADJ_FACTOR_SCHEMA,
                rows=[_adj_factor_row(TRADE_DATE, 4.0)],
                order_by="ts_code",
            )

            rows = _query_rows(
                build_daily_qfq_select_sql(
                    silver_paths=[silver_path],
                    trade_adj_factor_paths=[trade_factor_path],
                    as_of_adj_factor_paths=[repair_factor_path],
                )
            )

        self.assertEqual([row["open"] for row in rows], [5.0, 20.0])
        self.assertEqual([row["close"] for row in rows], [5.25, 21.0])

    def test_derived_qfq_uses_complete_source_windows_with_literal_ohlc(self) -> None:
        # Expected 90m values are manually verified from each complete 30m window.
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "source.parquet"
            _write_rows(
                source_path,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=[
                    _silver_row(
                        trade_date=TRADE_DATE,
                        trade_time=time,
                        freq=30,
                        open_=open_,
                        high=high,
                        low=low,
                        close=close,
                        vol=vol,
                        amount=vol * 10.0,
                    )
                    for time, open_, high, low, close, vol in (
                        ("10:00:00", 10.0, 11.0, 9.0, 10.5, 1.0),
                        ("10:30:00", 11.0, 12.0, 10.0, 11.5, 2.0),
                        ("11:00:00", 12.0, 20.0, 8.0, 12.5, 3.0),
                        ("11:30:00", 13.0, 14.0, 12.0, 13.5, 4.0),
                        ("13:30:00", 14.0, 15.0, 13.0, 14.5, 5.0),
                        ("14:00:00", 15.0, 16.0, 14.0, 15.5, 6.0),
                        ("14:30:00", 16.0, 17.0, 15.0, 16.5, 7.0),
                        ("15:00:00", 17.0, 18.0, 16.0, 17.5, 8.0),
                    )
                ],
                order_by="trade_time",
            )

            rows = _query_rows(
                build_gold_stk_mins_qfq_derived_select_sql(
                    source_qfq_paths=[source_path],
                    target_freq=90,
                    partition_keys=[TRADE_DATE],
                )
            )

        self.assertEqual(
            [
                (
                    row["trade_time"].strftime("%H:%M:%S"),
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row["vol"],
                    row["amount"],
                )
                for row in rows
            ],
            [
                ("11:00:00", 10.0, 20.0, 8.0, 12.5, 6.0, 60.0),
                ("14:00:00", 13.0, 16.0, 12.0, 15.5, 15.0, 150.0),
                ("15:00:00", 16.0, 18.0, 15.0, 17.5, 15.0, 150.0),
            ],
        )

    def test_factor_and_window_contracts_fail_closed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            silver_path = root / "silver.parquet"
            factor_path = root / "factor.parquet"
            source_path = root / "source.parquet"
            _write_rows(
                silver_path,
                schema=SILVER_STK_MINS_SCHEMA,
                rows=[
                    _silver_row(
                        trade_date=TRADE_DATE,
                        trade_time="09:30:00",
                        freq=1,
                        open_=10.0,
                        high=11.0,
                        low=9.0,
                        close=10.5,
                    )
                ],
                order_by="trade_time",
            )
            _write_rows(
                factor_path,
                schema=SILVER_ADJ_FACTOR_SCHEMA,
                rows=[_adj_factor_row(TRADE_DATE, 0.0)],
                order_by="ts_code",
            )
            _write_rows(
                source_path,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=[
                    _silver_row(
                        trade_date=TRADE_DATE,
                        trade_time="09:30:00",
                        freq=60,
                        open_=10.0,
                        high=11.0,
                        low=9.0,
                        close=10.5,
                    ),
                    _silver_row(
                        trade_date=TRADE_DATE,
                        trade_time="10:30:00",
                        freq=60,
                        open_=11.0,
                        high=12.0,
                        low=10.0,
                        close=11.5,
                        exchange="SZSE",
                    ),
                ],
                order_by="trade_time",
            )

            coverage = _query_rows(
                build_daily_qfq_coverage_sql(
                    silver_paths=[silver_path],
                    trade_adj_factor_paths=[factor_path],
                    as_of_adj_factor_paths=[factor_path],
                )
            )[0]
            diagnostics = _query_rows(
                build_gold_stk_mins_qfq_derived_diagnostics_sql(
                    source_qfq_paths=[source_path],
                    target_freq=120,
                    partition_keys=[TRADE_DATE],
                )
            )[0]

        self.assertEqual(coverage["silver_row_count"], 1)
        self.assertEqual(coverage["invalid_trade_adj_factor_row_count"], 1)
        self.assertEqual(coverage["invalid_as_of_adj_factor_row_count"], 1)
        self.assertEqual(coverage["qfq_output_row_count"], 0)
        self.assertEqual(diagnostics["generated_window_count"], 0)
        self.assertEqual(diagnostics["exchange_mismatch_window_count"], 1)
        self.assertTrue(math.isfinite(float(diagnostics["source_row_count"])))


if __name__ == "__main__":
    unittest.main()
