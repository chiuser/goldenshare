"""Protected formula examples for QFQ nine-turn.

The expected count and signal sequences below are manually reviewed business
fixtures. Do not regenerate them from production SQL or helper functions. A
formula change requires an approved contract version and history rebuild plan.
"""

import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.qfq_nineturn import (
    build_gold_stk_mins_qfq_nineturn_partition_select_sql,
    build_gold_stk_mins_qfq_nineturn_select_sql,
    build_gold_stock_daily_qfq_nineturn_partition_select_sql,
    build_gold_stock_daily_qfq_nineturn_select_sql,
)
from orchestrator.defs.run_contracts.qfq_nineturn import (
    QFQ_NINETURN_FALLBACK_CODE_LIMIT,
    QFQ_NINETURN_MINUTE_FREQS,
)

UP_COUNTS_15 = (0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)
DOWN_COUNTS_15 = (0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)
UP_SIGNALS_15 = (None,) * 12 + ("+9", "+9", "+9")
DOWN_SIGNALS_15 = (None,) * 12 + ("-9", "-9", "-9")


def _write_daily_source(
    path: Path,
    rows: list[tuple[str, date, float]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            "CREATE TABLE source(ts_code VARCHAR, trade_date DATE, close DOUBLE)"
        )
        connection.executemany("INSERT INTO source VALUES (?, ?, ?)", rows)
        connection.execute(
            copy_query_to_parquet(
                "SELECT ts_code, trade_date, close FROM source "
                "ORDER BY ts_code, trade_date",
                path,
            )
        )


def _write_minute_source(
    path: Path,
    rows: list[tuple[str, int, date, datetime, float]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            "CREATE TABLE source("
            "ts_code VARCHAR, freq INTEGER, trade_date DATE, "
            "trade_time TIMESTAMP, close DOUBLE)"
        )
        connection.executemany("INSERT INTO source VALUES (?, ?, ?, ?, ?)", rows)
        connection.execute(
            copy_query_to_parquet(
                "SELECT ts_code, freq, trade_date, trade_time, close FROM source "
                "ORDER BY ts_code, freq, trade_time",
                path,
            )
        )


def _write_daily_seed(
    path: Path,
    *,
    ts_code: str,
    trade_date: date,
    up_count: int,
    down_count: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            copy_query_to_parquet(
                f"""
                SELECT
                  '{ts_code}'::VARCHAR AS ts_code,
                  DATE '{trade_date.isoformat()}' AS trade_date,
                  10.0::DOUBLE AS close_qfq,
                  {up_count}::INTEGER AS up_count,
                  {down_count}::INTEGER AS down_count,
                  NULL::VARCHAR AS nine_up_turn,
                  NULL::VARCHAR AS nine_down_turn
                """,
                path,
            )
        )


def _write_minute_seed(
    path: Path,
    *,
    ts_code: str,
    freq: int,
    trade_date: date,
    trade_time: datetime,
    up_count: int,
    down_count: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            copy_query_to_parquet(
                f"""
                SELECT
                  '{ts_code}'::VARCHAR AS ts_code,
                  {freq}::INTEGER AS freq,
                  DATE '{trade_date.isoformat()}' AS trade_date,
                  TIMESTAMP '{trade_time.isoformat(sep=" ")}' AS trade_time,
                  10.0::DOUBLE AS close_qfq,
                  {up_count}::INTEGER AS up_count,
                  {down_count}::INTEGER AS down_count,
                  NULL::VARCHAR AS nine_up_turn,
                  NULL::VARCHAR AS nine_down_turn
                """,
                path,
            )
        )


def _daily_rows(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
) -> list[tuple[object, ...]]:
    return connection.execute(
        build_gold_stock_daily_qfq_nineturn_select_sql(source_paths=(path,))
    ).fetchall()


class QfqNineturnFormulaGoldenTests(unittest.TestCase):
    def test_daily_up_and_down_sequences_continue_past_nine(self) -> None:
        start = date(2026, 1, 1)
        rows = [
            ("000001.SZ", start + timedelta(days=index), float(index + 1))
            for index in range(15)
        ] + [
            ("600000.SH", start + timedelta(days=index), float(15 - index))
            for index in range(15)
        ]
        with TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "daily.parquet"
            _write_daily_source(source_path, rows)
            with duckdb.connect(database=":memory:") as connection:
                actual = _daily_rows(connection, source_path)

        by_code = {
            code: [row for row in actual if row[0] == code]
            for code in ("000001.SZ", "600000.SH")
        }
        up_rows = by_code["000001.SZ"]
        down_rows = by_code["600000.SH"]
        self.assertEqual(tuple(row[2] for row in up_rows), UP_COUNTS_15)
        self.assertEqual(tuple(row[3] for row in up_rows), (0,) * 15)
        self.assertEqual(tuple(row[4] for row in up_rows), UP_SIGNALS_15)
        self.assertEqual(tuple(row[5] for row in up_rows), (None,) * 15)
        self.assertEqual(tuple(row[2] for row in down_rows), (0,) * 15)
        self.assertEqual(tuple(row[3] for row in down_rows), DOWN_COUNTS_15)
        self.assertEqual(tuple(row[4] for row in down_rows), (None,) * 15)
        self.assertEqual(tuple(row[5] for row in down_rows), DOWN_SIGNALS_15)

    def test_equal_price_and_direction_change_reset_the_count(self) -> None:
        prices = (10.0, 10.0, 10.0, 10.0, 11.0, 12.0, 13.0, 14.0, 11.0, 10.0, 9.0, 20.0)
        expected_up = (0, 0, 0, 0, 1, 2, 3, 4, 0, 0, 0, 1)
        expected_down = (0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 0)
        with TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "daily.parquet"
            _write_daily_source(
                source_path,
                [
                    ("000001.SZ", date(2026, 2, 1) + timedelta(days=index), price)
                    for index, price in enumerate(prices)
                ],
            )
            with duckdb.connect(database=":memory:") as connection:
                actual = _daily_rows(connection, source_path)

        self.assertEqual(tuple(row[2] for row in actual), expected_up)
        self.assertEqual(tuple(row[3] for row in actual), expected_down)

    def test_actual_bar_order_crosses_year_and_ignores_calendar_gaps(self) -> None:
        rows = [
            ("000001.SZ", date(2025, 12, 24), 10.0),
            ("000001.SZ", date(2025, 12, 25), 11.0),
            ("000001.SZ", date(2025, 12, 26), 12.0),
            ("000001.SZ", date(2025, 12, 31), 13.0),
            ("000001.SZ", date(2026, 1, 5), 14.0),
            ("000001.SZ", date(2026, 1, 20), 15.0),
        ]
        with TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "daily.parquet"
            _write_daily_source(source_path, rows)
            with duckdb.connect(database=":memory:") as connection:
                actual = _daily_rows(connection, source_path)

        self.assertEqual(tuple(row[2] for row in actual), (0, 0, 0, 0, 1, 2))
        self.assertEqual(tuple(row[3] for row in actual), (0, 0, 0, 0, 0, 0))

    def test_each_minute_frequency_uses_trade_time_order(self) -> None:
        expected_up = (0, 0, 0, 0, 1, 2)
        for freq in QFQ_NINETURN_MINUTE_FREQS:
            with self.subTest(freq=freq), TemporaryDirectory() as temp_dir:
                source_path = Path(temp_dir) / f"{freq}m.parquet"
                start = datetime.fromisoformat("2026-03-02T09:30:00")
                _write_minute_source(
                    source_path,
                    [
                        (
                            "000001.SZ",
                            freq,
                            date(2026, 3, 2),
                            start + timedelta(minutes=freq * index),
                            float(index + 1),
                        )
                        for index in range(6)
                    ],
                )
                with duckdb.connect(database=":memory:") as connection:
                    actual = connection.execute(
                        build_gold_stk_mins_qfq_nineturn_select_sql(
                            source_paths=(source_path,),
                            freq=freq,
                        )
                    ).fetchall()

            self.assertEqual(tuple(row[4] for row in actual), expected_up)
            self.assertEqual(tuple(row[5] for row in actual), (0,) * 6)

    def test_positive_price_scaling_does_not_change_counts_or_signals(self) -> None:
        prices = (10.0, 11.0, 9.0, 12.0, 13.0, 14.0, 8.0, 15.0, 16.0, 7.0, 17.0)
        start = date(2026, 4, 1)
        with TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "daily.parquet"
            scaled_path = Path(temp_dir) / "daily_scaled.parquet"
            _write_daily_source(
                source_path,
                [
                    ("000001.SZ", start + timedelta(days=index), price)
                    for index, price in enumerate(prices)
                ],
            )
            _write_daily_source(
                scaled_path,
                [
                    ("000001.SZ", start + timedelta(days=index), price * 3.5)
                    for index, price in enumerate(prices)
                ],
            )
            with duckdb.connect(database=":memory:") as connection:
                actual = _daily_rows(connection, source_path)
                scaled = _daily_rows(connection, scaled_path)

        self.assertEqual(
            tuple((row[2], row[3], row[4], row[5]) for row in actual),
            tuple((row[2], row[3], row[4], row[5]) for row in scaled),
        )

    def test_daily_partition_continues_seed_and_new_stock_starts_at_zero(self) -> None:
        previous_date = date(2026, 5, 7)
        target_date = date(2026, 5, 8)
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "daily.parquet"
            seed_path = root / "previous.parquet"
            _write_daily_source(
                source_path,
                [
                    ("000001.SZ", date(2026, 5, 4), 10.0),
                    ("000001.SZ", date(2026, 5, 5), 11.0),
                    ("000001.SZ", date(2026, 5, 6), 12.0),
                    ("000001.SZ", previous_date, 13.0),
                    ("000001.SZ", target_date, 20.0),
                    ("301000.SZ", target_date, 30.0),
                ],
            )
            _write_daily_seed(
                seed_path,
                ts_code="000001.SZ",
                trade_date=previous_date,
                up_count=8,
                down_count=0,
            )
            with duckdb.connect(database=":memory:") as connection:
                actual = connection.execute(
                    build_gold_stock_daily_qfq_nineturn_partition_select_sql(
                        source_paths=(source_path,),
                        target_trade_date=target_date.isoformat(),
                        previous_partition_path=seed_path,
                    )
                ).fetchall()

        self.assertEqual(
            tuple((row[0], row[2], row[3], row[4], row[5]) for row in actual),
            (
                ("000001.SZ", 9, 0, "+9", None),
                ("301000.SZ", 0, 0, None, None),
            ),
        )

    def test_missing_old_seed_uses_exact_code_scoped_fallback(self) -> None:
        start = date(2026, 6, 1)
        target_date = start + timedelta(days=12)
        rows = [
            ("000001.SZ", start + timedelta(days=index), float(index + 1))
            for index in range(13)
        ]
        with TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "daily.parquet"
            _write_daily_source(source_path, rows)
            with duckdb.connect(database=":memory:") as connection:
                actual = connection.execute(
                    build_gold_stock_daily_qfq_nineturn_partition_select_sql(
                        source_paths=(source_path,),
                        target_trade_date=target_date.isoformat(),
                        fallback_source_paths=(source_path,),
                        fallback_codes=("000001.SZ",),
                    )
                ).fetchall()

        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0][2:], (9, 0, "+9", None))

    def test_minute_partition_continues_previous_day_last_seed(self) -> None:
        previous_date = date(2026, 7, 30)
        target_date = date(2026, 7, 31)
        previous_times = (
            datetime.fromisoformat("2026-07-30T10:30:00"),
            datetime.fromisoformat("2026-07-30T11:30:00"),
            datetime.fromisoformat("2026-07-30T14:00:00"),
            datetime.fromisoformat("2026-07-30T15:00:00"),
        )
        target_times = (
            datetime.fromisoformat("2026-07-31T10:30:00"),
            datetime.fromisoformat("2026-07-31T11:30:00"),
        )
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "60m.parquet"
            seed_path = root / "previous.parquet"
            _write_minute_source(
                source_path,
                [
                    ("000001.SZ", 60, previous_date, trade_time, float(index + 1))
                    for index, trade_time in enumerate(previous_times)
                ]
                + [
                    ("000001.SZ", 60, target_date, trade_time, float(index + 10))
                    for index, trade_time in enumerate(target_times)
                ],
            )
            _write_minute_seed(
                seed_path,
                ts_code="000001.SZ",
                freq=60,
                trade_date=previous_date,
                trade_time=previous_times[-1],
                up_count=8,
                down_count=0,
            )
            with duckdb.connect(database=":memory:") as connection:
                actual = connection.execute(
                    build_gold_stk_mins_qfq_nineturn_partition_select_sql(
                        source_paths=(source_path,),
                        freq=60,
                        target_trade_date=target_date.isoformat(),
                        previous_partition_path=seed_path,
                    )
                ).fetchall()

        self.assertEqual(tuple(row[4] for row in actual), (9, 10))
        self.assertEqual(tuple(row[5] for row in actual), (0, 0))
        self.assertEqual(tuple(row[6] for row in actual), ("+9", "+9"))

    def test_fallback_scope_over_limit_fails_before_sql_execution(self) -> None:
        with self.assertRaises(ValueError):
            build_gold_stock_daily_qfq_nineturn_partition_select_sql(
                source_paths=(Path("source.parquet"),),
                target_trade_date="2026-08-07",
                fallback_source_paths=(Path("source.parquet"),),
                fallback_codes=tuple(
                    f"{index:06d}.SZ"
                    for index in range(QFQ_NINETURN_FALLBACK_CODE_LIMIT + 1)
                ),
            )


if __name__ == "__main__":
    unittest.main()
