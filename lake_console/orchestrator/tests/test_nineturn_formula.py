"""Contract and extraction gates for the shared nine-turn SQL formula."""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.nineturn_formula import (
    NINETURN_FORMULA_INPUT_COLUMNS,
    NINETURN_FORMULA_OUTPUT_COLUMNS,
    build_nineturn_formula_select_sql,
)
from orchestrator.defs.qfq_nineturn import (
    build_gold_stock_daily_qfq_nineturn_select_sql,
)


class NineturnFormulaTests(unittest.TestCase):
    def test_normalized_contract_and_manual_count_sequence(self) -> None:
        source_sql = """
        SELECT *
        FROM (VALUES
          ('UP', DATE '2025-12-24', TIMESTAMP '2025-12-24 00:00:00', 1.0),
          ('UP', DATE '2025-12-25', TIMESTAMP '2025-12-25 00:00:00', 2.0),
          ('UP', DATE '2025-12-26', TIMESTAMP '2025-12-26 00:00:00', 3.0),
          ('UP', DATE '2025-12-31', TIMESTAMP '2025-12-31 00:00:00', 4.0),
          ('UP', DATE '2026-01-05', TIMESTAMP '2026-01-05 00:00:00', 5.0),
          ('UP', DATE '2026-01-20', TIMESTAMP '2026-01-20 00:00:00', 6.0),
          ('DOWN', DATE '2025-12-24', TIMESTAMP '2025-12-24 00:00:00', 6.0),
          ('DOWN', DATE '2025-12-25', TIMESTAMP '2025-12-25 00:00:00', 5.0),
          ('DOWN', DATE '2025-12-26', TIMESTAMP '2025-12-26 00:00:00', 4.0),
          ('DOWN', DATE '2025-12-31', TIMESTAMP '2025-12-31 00:00:00', 3.0),
          ('DOWN', DATE '2026-01-05', TIMESTAMP '2026-01-05 00:00:00', 2.0),
          ('DOWN', DATE '2026-01-20', TIMESTAMP '2026-01-20 00:00:00', 1.0)
        ) AS rows(subject_code, bar_date, bar_time, close_value)
        """
        with duckdb.connect(database=":memory:") as connection:
            cursor = connection.execute(
                build_nineturn_formula_select_sql(source_sql=source_sql)
                + " ORDER BY subject_code, bar_time"
            )
            actual_columns = tuple(column[0] for column in cursor.description)
            actual = cursor.fetchall()

        self.assertEqual(
            NINETURN_FORMULA_INPUT_COLUMNS,
            ("subject_code", "bar_date", "bar_time", "close_value"),
        )
        self.assertEqual(
            NINETURN_FORMULA_OUTPUT_COLUMNS,
            NINETURN_FORMULA_INPUT_COLUMNS
            + ("up_count", "down_count", "nine_up_turn", "nine_down_turn"),
        )
        self.assertEqual(actual_columns, NINETURN_FORMULA_OUTPUT_COLUMNS)
        by_code = {
            code: [row for row in actual if row[0] == code]
            for code in ("UP", "DOWN")
        }
        self.assertEqual(tuple(row[4] for row in by_code["UP"]), (0, 0, 0, 0, 1, 2))
        self.assertEqual(tuple(row[5] for row in by_code["UP"]), (0, 0, 0, 0, 0, 0))
        self.assertEqual(tuple(row[4] for row in by_code["DOWN"]), (0, 0, 0, 0, 0, 0))
        self.assertEqual(tuple(row[5] for row in by_code["DOWN"]), (0, 0, 0, 0, 1, 2))

    def test_seeded_window_uses_context_without_emitting_it(self) -> None:
        context_sql = """
        SELECT *
        FROM (VALUES
          ('000001.SZ', DATE '2026-01-02', TIMESTAMP '2026-01-02 00:00:00', 10.0),
          ('000001.SZ', DATE '2026-01-05', TIMESTAMP '2026-01-05 00:00:00', 11.0),
          ('000001.SZ', DATE '2026-01-06', TIMESTAMP '2026-01-06 00:00:00', 12.0),
          ('000001.SZ', DATE '2026-01-07', TIMESTAMP '2026-01-07 00:00:00', 13.0)
        ) AS rows(subject_code, bar_date, bar_time, close_value)
        """
        source_sql = """
        SELECT *
        FROM (VALUES
          ('000001.SZ', DATE '2026-01-08', TIMESTAMP '2026-01-08 00:00:00', 20.0),
          ('000001.SZ', DATE '2026-01-09', TIMESTAMP '2026-01-09 00:00:00', 21.0)
        ) AS rows(subject_code, bar_date, bar_time, close_value)
        """
        seed_sql = """
        SELECT '000001.SZ'::VARCHAR AS subject_code,
               1::INTEGER AS seed_direction,
               8::INTEGER AS seed_count
        """
        with duckdb.connect(database=":memory:") as connection:
            actual = connection.execute(
                build_nineturn_formula_select_sql(
                    source_sql=source_sql,
                    context_sql=context_sql,
                    seed_sql=seed_sql,
                    start_date="2026-01-08",
                    end_date="2026-01-09",
                )
                + " ORDER BY bar_time"
            ).fetchall()

        self.assertEqual(tuple(row[1] for row in actual), (date(2026, 1, 8), date(2026, 1, 9)))
        self.assertEqual(tuple(row[4] for row in actual), (9, 10))
        self.assertEqual(tuple(row[5] for row in actual), (0, 0))
        self.assertEqual(tuple(row[6] for row in actual), ("+9", "+9"))
        self.assertEqual(tuple(row[7] for row in actual), (None, None))

    def test_stock_adapter_matches_normalized_kernel_row_for_row(self) -> None:
        start = date(2026, 2, 1)
        rows = [
            ("000001.SZ", start + timedelta(days=index), float(index + 1))
            for index in range(15)
        ]
        with TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "daily.parquet"
            with duckdb.connect(database=":memory:") as connection:
                connection.execute(
                    "CREATE TABLE source(ts_code VARCHAR, trade_date DATE, close DOUBLE)"
                )
                connection.executemany("INSERT INTO source VALUES (?, ?, ?)", rows)
                connection.execute(
                    copy_query_to_parquet(
                        "SELECT * FROM source ORDER BY ts_code, trade_date",
                        source_path,
                    )
                )
                stock_rows = connection.execute(
                    build_gold_stock_daily_qfq_nineturn_select_sql(
                        source_paths=(source_path,)
                    )
                ).fetchall()
                normalized_rows = connection.execute(
                    build_nineturn_formula_select_sql(
                        source_sql=f"""
                        SELECT
                          CAST(ts_code AS VARCHAR) AS subject_code,
                          CAST(trade_date AS DATE) AS bar_date,
                          CAST(trade_date AS TIMESTAMP) AS bar_time,
                          CAST(close AS DOUBLE) AS close_value
                        FROM {read_parquet(source_path, hive_partitioning=False)}
                        """
                    )
                    + " ORDER BY subject_code, bar_time"
                ).fetchall()

        normalized_records = tuple(
            dict(zip(NINETURN_FORMULA_OUTPUT_COLUMNS, row, strict=True))
            for row in normalized_rows
        )
        projected_normalized_rows = [
            (
                row["subject_code"],
                row["bar_date"],
                row["up_count"],
                row["down_count"],
                row["nine_up_turn"],
                row["nine_down_turn"],
            )
            for row in normalized_records
        ]
        self.assertEqual(stock_rows, projected_normalized_rows)

    def test_window_dates_are_an_atomic_contract(self) -> None:
        empty_source = """
        SELECT NULL::VARCHAR AS subject_code,
               NULL::DATE AS bar_date,
               NULL::TIMESTAMP AS bar_time,
               NULL::DOUBLE AS close_value
        WHERE false
        """
        with self.assertRaises(ValueError):
            build_nineturn_formula_select_sql(
                source_sql=empty_source,
                start_date="2026-01-01",
            )
        with self.assertRaises(ValueError):
            build_nineturn_formula_select_sql(
                source_sql=empty_source,
                end_date="2026-01-01",
            )

    def test_stock_module_contains_only_adapters_not_a_second_formula(self) -> None:
        defs_dir = Path(__file__).parents[1] / "src" / "orchestrator" / "defs"
        formula_source = (defs_dir / "nineturn_formula.py").read_text(encoding="utf-8")
        stock_source = (defs_dir / "qfq_nineturn.py").read_text(encoding="utf-8")

        self.assertIn("build_nineturn_formula_select_sql", stock_source)
        for forbidden in (
            "LAG(close_qfq",
            "AS segment_start",
            "AS continued_count",
        ):
            self.assertNotIn(forbidden, stock_source)
        self.assertEqual(formula_source.count("LAG(close_value,"), 1)
        self.assertEqual(formula_source.count("AS segment_start"), 1)
        self.assertEqual(formula_source.count("AS continued_count"), 1)


if __name__ == "__main__":
    unittest.main()
