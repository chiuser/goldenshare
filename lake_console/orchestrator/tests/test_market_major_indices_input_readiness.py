import tempfile
import unittest
from pathlib import Path

import duckdb

from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import silver_index_basic_path, silver_index_daily_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.sensors.market_major_indices_input_readiness import (
    check_market_major_indices_inputs_for_trade_date,
)
from orchestrator.seeds.market.major_indices import (
    active_major_indices_seed_rows,
    load_major_indices_seed,
)


TARGET_TRADE_DATE = "2026-05-26"


def _seed_codes() -> tuple[str, ...]:
    return tuple(row.ts_code for row in load_major_indices_seed())


def _active_seed_codes() -> tuple[str, ...]:
    return tuple(row.ts_code for row in active_major_indices_seed_rows(TARGET_TRADE_DATE))


def _write_index_basic_file(root: Path, ts_codes: tuple[str, ...]) -> None:
    path = silver_index_basic_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(f"({duckdb_string(ts_code)})" for ts_code in ts_codes)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT *
              FROM (VALUES {values_sql}) rows(ts_code)
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )


def _write_silver_daily_file(root: Path, trade_date: str, ts_codes: tuple[str, ...]) -> None:
    path = silver_index_daily_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(
        f"({duckdb_string(ts_code)}, DATE {duckdb_string(trade_date)})"
        for ts_code in ts_codes
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT *
              FROM (VALUES {values_sql}) rows(ts_code, trade_date)
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )


class MarketMajorIndicesInputReadinessTests(unittest.TestCase):
    def test_all_seed_inputs_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            seed_codes = _seed_codes()
            active_codes = _active_seed_codes()
            _write_index_basic_file(root, seed_codes)
            _write_silver_daily_file(root, TARGET_TRADE_DATE, active_codes)

            result = check_market_major_indices_inputs_for_trade_date(
                lake_root_path=root,
                duckdb=DuckDBResource(),
                registered_index_codes=seed_codes,
                trade_date=TARGET_TRADE_DATE,
            )

            self.assertTrue(result.ready)
            self.assertEqual(result.seed_row_count, len(seed_codes))
            self.assertEqual(result.active_seed_code_count, len(active_codes))
            self.assertEqual(result.blocked_count, 0)

    def test_reports_seed_codes_missing_from_registered_partitions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            seed_codes = _seed_codes()
            missing_code = seed_codes[0]
            _write_index_basic_file(root, seed_codes)
            _write_silver_daily_file(root, TARGET_TRADE_DATE, _active_seed_codes())

            result = check_market_major_indices_inputs_for_trade_date(
                lake_root_path=root,
                duckdb=DuckDBResource(),
                registered_index_codes=seed_codes[1:],
                trade_date=TARGET_TRADE_DATE,
            )

            self.assertFalse(result.ready)
            self.assertEqual(result.missing_registered_seed_codes, (missing_code,))

    def test_reports_seed_codes_missing_from_index_basic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            seed_codes = _seed_codes()
            missing_code = seed_codes[0]
            _write_index_basic_file(root, seed_codes[1:])
            _write_silver_daily_file(root, TARGET_TRADE_DATE, _active_seed_codes())

            result = check_market_major_indices_inputs_for_trade_date(
                lake_root_path=root,
                duckdb=DuckDBResource(),
                registered_index_codes=seed_codes,
                trade_date=TARGET_TRADE_DATE,
            )

            self.assertFalse(result.ready)
            self.assertEqual(result.missing_index_basic_seed_codes, (missing_code,))

    def test_reports_active_seed_codes_missing_from_silver_daily(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            seed_codes = _seed_codes()
            active_codes = _active_seed_codes()
            missing_code = active_codes[0]
            _write_index_basic_file(root, seed_codes)
            _write_silver_daily_file(root, TARGET_TRADE_DATE, active_codes[1:])

            result = check_market_major_indices_inputs_for_trade_date(
                lake_root_path=root,
                duckdb=DuckDBResource(),
                registered_index_codes=seed_codes,
                trade_date=TARGET_TRADE_DATE,
            )

            self.assertFalse(result.ready)
            self.assertEqual(result.missing_silver_daily_seed_codes, (missing_code,))


if __name__ == "__main__":
    unittest.main()
