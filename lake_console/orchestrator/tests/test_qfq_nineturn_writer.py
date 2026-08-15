import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import duckdb

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_nineturn_path,
    gold_stk_mins_qfq_nineturn_staging_path,
    gold_stock_daily_qfq_nineturn_path,
    gold_stock_daily_qfq_nineturn_staging_path,
)
from orchestrator.defs.qfq_nineturn import (
    GOLD_STK_MINS_QFQ_NINETURN_COLUMNS,
    GOLD_STOCK_DAILY_QFQ_NINETURN_COLUMNS,
    write_gold_stk_mins_qfq_nineturn_partition,
    write_gold_stock_daily_qfq_nineturn_partition,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_NINETURN_SCHEMA,
    GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
)
from orchestrator.defs.run_contracts.qfq_nineturn import (
    QFQ_NINETURN_MINUTE_FREQS,
    normalize_qfq_nineturn_minute_freq,
)

TRADE_DATE = "2026-08-07"


def _write_source_marker(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(copy_query_to_parquet("SELECT 1::INTEGER AS marker", path))


def _daily_select_sql(*, trade_date: str = TRADE_DATE) -> str:
    return f"""
    SELECT *
    FROM (
      VALUES
        ('000001.SZ', DATE '{trade_date}', 10.0::DOUBLE, 9::INTEGER, 0::INTEGER, '+9'::VARCHAR, NULL::VARCHAR),
        ('600000.SH', DATE '{trade_date}', 20.0::DOUBLE, 0::INTEGER, 2::INTEGER, NULL::VARCHAR, NULL::VARCHAR)
    ) AS rows(ts_code, trade_date, close_qfq, up_count, down_count, nine_up_turn, nine_down_turn)
    ORDER BY ts_code, trade_date
    """


def _minute_select_sql(*, freq: int = 60, trade_date: str = TRADE_DATE) -> str:
    return f"""
    SELECT *
    FROM (
      VALUES
        ('000001.SZ', {freq}::INTEGER, DATE '{trade_date}', TIMESTAMP '{trade_date} 10:30:00', 1::INTEGER, 0::INTEGER, NULL::VARCHAR, NULL::VARCHAR),
        ('000001.SZ', {freq}::INTEGER, DATE '{trade_date}', TIMESTAMP '{trade_date} 11:30:00', 2::INTEGER, 0::INTEGER, NULL::VARCHAR, NULL::VARCHAR)
    ) AS rows(ts_code, freq, trade_date, trade_time, up_count, down_count, nine_up_turn, nine_down_turn)
    ORDER BY ts_code, trade_time
    """


class QfqNineturnWriterTests(unittest.TestCase):
    def test_contract_schemas_and_paths_are_exact(self) -> None:
        self.assertEqual(
            GOLD_STOCK_DAILY_QFQ_NINETURN_COLUMNS,
            tuple(column.name for column in GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA),
        )
        self.assertEqual(
            GOLD_STK_MINS_QFQ_NINETURN_COLUMNS,
            tuple(column.name for column in GOLD_STK_MINS_QFQ_NINETURN_SCHEMA),
        )
        self.assertEqual(
            GOLD_STK_MINS_QFQ_NINETURN_COLUMNS,
            (
                "ts_code",
                "freq",
                "trade_date",
                "trade_time",
                "up_count",
                "down_count",
                "nine_up_turn",
                "nine_down_turn",
            ),
        )
        self.assertIn("close_qfq", GOLD_STOCK_DAILY_QFQ_NINETURN_COLUMNS)
        self.assertNotIn("close_qfq", GOLD_STK_MINS_QFQ_NINETURN_COLUMNS)
        root = Path("/lake")
        self.assertEqual(
            gold_stock_daily_qfq_nineturn_path(root, TRADE_DATE),
            root
            / "gold/indicator/stock_daily_qfq_nineturn"
            / f"trade_date={TRADE_DATE}/part-000.parquet",
        )
        self.assertEqual(
            gold_stk_mins_qfq_nineturn_path(root, 60, TRADE_DATE),
            root
            / "gold/indicator/stk_mins_qfq_nineturn/freq=60"
            / f"trade_date={TRADE_DATE}/part-000.parquet",
        )
        self.assertEqual(
            gold_stock_daily_qfq_nineturn_staging_path(
                root,
                "run-1",
                TRADE_DATE,
            ),
            root
            / "gold/indicator/stock_daily_qfq_nineturn/_staging/run_id=run-1"
            / f"trade_date={TRADE_DATE}/part-000.parquet",
        )
        self.assertEqual(
            gold_stk_mins_qfq_nineturn_staging_path(
                root,
                "run-1",
                120,
                TRADE_DATE,
            ),
            root
            / "gold/indicator/stk_mins_qfq_nineturn/_staging/run_id=run-1/freq=120"
            / f"trade_date={TRADE_DATE}/part-000.parquet",
        )
        self.assertEqual(
            tuple(
                normalize_qfq_nineturn_minute_freq(freq)
                for freq in QFQ_NINETURN_MINUTE_FREQS
            ),
            QFQ_NINETURN_MINUTE_FREQS,
        )
        for unsupported in (1, 5, 15, 45, "daily"):
            with self.subTest(unsupported=unsupported), self.assertRaises(ValueError):
                normalize_qfq_nineturn_minute_freq(unsupported)

    def test_daily_partition_is_validated_then_promoted(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            source_path = lake_root / "gold/source.parquet"
            _write_source_marker(source_path)
            result = write_gold_stock_daily_qfq_nineturn_partition(
                duckdb_resource=DuckDBResource(),
                lake_root=lake_root,
                partition_key=TRADE_DATE,
                run_id="run-1",
                select_sql=_daily_select_sql(),
                source_paths=(source_path,),
                source_row_count=2,
                fallback_recomputed_code_count=1,
            )
            with duckdb.connect(database=":memory:") as connection:
                rows = connection.execute(
                    f"SELECT * FROM {read_parquet(result.target_path, hive_partitioning=False)} "
                    "ORDER BY ts_code"
                ).fetchall()

        self.assertEqual(result.output_row_count, 2)
        self.assertEqual(result.stock_code_count, 2)
        self.assertEqual(result.fallback_recomputed_code_count, 1)
        self.assertEqual(result.source_file_count, 1)
        self.assertEqual(result.observed_columns, GOLD_STOCK_DAILY_QFQ_NINETURN_COLUMNS)
        self.assertEqual(len(rows), 2)

    def test_minute_partition_is_validated_then_promoted(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            source_path = lake_root / "gold/source.parquet"
            _write_source_marker(source_path)
            result = write_gold_stk_mins_qfq_nineturn_partition(
                duckdb_resource=DuckDBResource(),
                lake_root=lake_root,
                freq=60,
                partition_key=TRADE_DATE,
                run_id="run-1",
                select_sql=_minute_select_sql(),
                source_paths=(source_path,),
                source_row_count=2,
            )
            with duckdb.connect(database=":memory:") as connection:
                observed_columns = tuple(
                    row[0]
                    for row in connection.execute(
                        f"DESCRIBE SELECT * FROM {read_parquet(result.target_path, hive_partitioning=False)}"
                    ).fetchall()
                )

        self.assertEqual(result.output_row_count, 2)
        self.assertEqual(result.stock_code_count, 1)
        self.assertEqual(result.observed_columns, GOLD_STK_MINS_QFQ_NINETURN_COLUMNS)
        self.assertEqual(observed_columns, GOLD_STK_MINS_QFQ_NINETURN_COLUMNS)

    def test_contract_failure_does_not_replace_existing_target(self) -> None:
        invalid_queries = {
            "wrong_schema": "SELECT '000001.SZ'::VARCHAR AS ts_code",
            "wrong_date": _daily_select_sql(trade_date="2026-08-06"),
            "duplicate_key": """
                SELECT * FROM (
                  VALUES
                    ('000001.SZ', DATE '2026-08-07', 10.0::DOUBLE, 1::INTEGER, 0::INTEGER, NULL::VARCHAR, NULL::VARCHAR),
                    ('000001.SZ', DATE '2026-08-07', 11.0::DOUBLE, 2::INTEGER, 0::INTEGER, NULL::VARCHAR, NULL::VARCHAR)
                ) AS rows(ts_code, trade_date, close_qfq, up_count, down_count, nine_up_turn, nine_down_turn)
            """,
            "null_key": """
                SELECT NULL::VARCHAR AS ts_code, DATE '2026-08-07' AS trade_date,
                  10.0::DOUBLE AS close_qfq, 1::INTEGER AS up_count,
                  0::INTEGER AS down_count, NULL::VARCHAR AS nine_up_turn,
                  NULL::VARCHAR AS nine_down_turn
            """,
            "invalid_value": """
                SELECT '000001.SZ'::VARCHAR AS ts_code, DATE '2026-08-07' AS trade_date,
                  10.0::DOUBLE AS close_qfq, 1::INTEGER AS up_count,
                  1::INTEGER AS down_count, NULL::VARCHAR AS nine_up_turn,
                  NULL::VARCHAR AS nine_down_turn
            """,
        }
        for name, select_sql in invalid_queries.items():
            with self.subTest(name=name), TemporaryDirectory() as temp_dir:
                lake_root = Path(temp_dir)
                source_path = lake_root / "gold/source.parquet"
                target_path = gold_stock_daily_qfq_nineturn_path(
                    lake_root,
                    TRADE_DATE,
                )
                _write_source_marker(source_path)
                _write_source_marker(target_path)
                previous_bytes = target_path.read_bytes()

                with self.assertRaises(ValueError):
                    write_gold_stock_daily_qfq_nineturn_partition(
                        duckdb_resource=DuckDBResource(),
                        lake_root=lake_root,
                        partition_key=TRADE_DATE,
                        run_id="run-1",
                        select_sql=select_sql,
                        source_paths=(source_path,),
                        source_row_count=(2 if name == "duplicate_key" else 1),
                    )

                self.assertEqual(target_path.read_bytes(), previous_bytes)

    def test_minute_frequency_mismatch_does_not_promote(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            source_path = lake_root / "gold/source.parquet"
            target_path = gold_stk_mins_qfq_nineturn_path(
                lake_root,
                60,
                TRADE_DATE,
            )
            _write_source_marker(source_path)
            _write_source_marker(target_path)
            previous_bytes = target_path.read_bytes()

            with self.assertRaises(ValueError):
                write_gold_stk_mins_qfq_nineturn_partition(
                    duckdb_resource=DuckDBResource(),
                    lake_root=lake_root,
                    freq=60,
                    partition_key=TRADE_DATE,
                    run_id="run-1",
                    select_sql=_minute_select_sql(freq=30),
                    source_paths=(source_path,),
                    source_row_count=2,
                )

            self.assertEqual(target_path.read_bytes(), previous_bytes)

    def test_source_fingerprint_change_does_not_promote(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            source_path = lake_root / "gold/source.parquet"
            target_path = gold_stock_daily_qfq_nineturn_path(
                lake_root,
                TRADE_DATE,
            )
            _write_source_marker(source_path)
            _write_source_marker(target_path)
            previous_bytes = target_path.read_bytes()

            with (
                patch(
                    "orchestrator.defs.qfq_nineturn.build_qfq_nineturn_source_fingerprint",
                    side_effect=("before", "after"),
                ),
                self.assertRaises(RuntimeError),
            ):
                write_gold_stock_daily_qfq_nineturn_partition(
                    duckdb_resource=DuckDBResource(),
                    lake_root=lake_root,
                    partition_key=TRADE_DATE,
                    run_id="run-1",
                    select_sql=_daily_select_sql(),
                    source_paths=(source_path,),
                    source_row_count=2,
                )

            self.assertEqual(target_path.read_bytes(), previous_bytes)


if __name__ == "__main__":
    unittest.main()
