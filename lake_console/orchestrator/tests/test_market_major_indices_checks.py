import tempfile
import unittest
from pathlib import Path

import duckdb

from orchestrator.defs.checks import market_major_indices_checks as checks
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    gold_market_major_indices_daily_path,
    silver_index_basic_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.seeds.market.major_indices import active_major_indices_seed_rows


TARGET_TRADE_DATE = "2026-05-26"


class _PartitionContext:
    def __init__(self, *partition_keys: str) -> None:
        self.partition_keys = partition_keys


def _check_function(check_definition):
    if not hasattr(check_definition, "node_def"):
        return check_definition
    return check_definition.node_def.compute_fn.decorated_fn


def _nullable_sql_string(value: str | None) -> str:
    return "NULL::VARCHAR" if value is None else duckdb_string(value)


def _write_gold_major_indices_file(
    root: Path,
    *,
    trade_date: str = TARGET_TRADE_DATE,
    omitted_codes: tuple[str, ...] = (),
    rank_overrides: dict[str, int] | None = None,
    price_overrides: dict[str, dict[str, float]] | None = None,
) -> Path:
    path = gold_market_major_indices_daily_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    rank_overrides = rank_overrides or {}
    price_overrides = price_overrides or {}
    value_rows = []
    for seed_row in active_major_indices_seed_rows(trade_date):
        if seed_row.ts_code in omitted_codes:
            continue
        prices = {
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "pre_close": 10.0,
        }
        prices.update(price_overrides.get(seed_row.ts_code, {}))
        value_rows.append(
            "("
            f"DATE {duckdb_string(trade_date)}, "
            f"{rank_overrides.get(seed_row.ts_code, seed_row.rank)}, "
            f"{duckdb_string(seed_row.ts_code)}, "
            f"{_nullable_sql_string(seed_row.display_name)}, "
            f"{prices['open']}, "
            f"{prices['high']}, "
            f"{prices['low']}, "
            f"{prices['close']}, "
            f"{prices['pre_close']}, "
            "0.5, "
            "5.0, "
            "100.0, "
            "1000.0"
            ")"
        )
    values_sql = ", ".join(value_rows)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT *
              FROM (VALUES {values_sql}) rows(
                trade_date,
                rank,
                ts_code,
                display_name,
                open,
                high,
                low,
                close,
                pre_close,
                change_amount,
                pct_chg,
                vol,
                amount
              )
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )
    return path


def _write_silver_index_basic_file(root: Path, ts_codes: tuple[str, ...]) -> Path:
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
    return path


class MarketMajorIndicesCheckTests(unittest.TestCase):
    def test_row_count_matches_active_seed_passes_and_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = _PartitionContext(TARGET_TRADE_DATE)
            lake_root = LakeRootResource(root_path=str(root))
            duckdb_resource = DuckDBResource()
            active_codes = tuple(
                row.ts_code for row in active_major_indices_seed_rows(TARGET_TRADE_DATE)
            )

            _write_gold_major_indices_file(root)
            check_fn = _check_function(
                checks.gold_market_major_indices_daily_row_count_matches_seed
            )
            self.assertTrue(check_fn(context, lake_root, duckdb_resource).passed)

            _write_gold_major_indices_file(root, omitted_codes=(active_codes[0],))
            self.assertFalse(check_fn(context, lake_root, duckdb_resource).passed)

    def test_seed_codes_present_passes_and_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = _PartitionContext(TARGET_TRADE_DATE)
            lake_root = LakeRootResource(root_path=str(root))
            duckdb_resource = DuckDBResource()
            active_codes = tuple(
                row.ts_code for row in active_major_indices_seed_rows(TARGET_TRADE_DATE)
            )

            _write_gold_major_indices_file(root)
            check_fn = _check_function(
                checks.gold_market_major_indices_daily_seed_codes_present
            )
            self.assertTrue(check_fn(context, lake_root, duckdb_resource).passed)

            _write_gold_major_indices_file(root, omitted_codes=(active_codes[0],))
            self.assertFalse(check_fn(context, lake_root, duckdb_resource).passed)

    def test_rank_matches_active_seed_order_passes_and_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = _PartitionContext(TARGET_TRADE_DATE)
            lake_root = LakeRootResource(root_path=str(root))
            duckdb_resource = DuckDBResource()
            active_rows = active_major_indices_seed_rows(TARGET_TRADE_DATE)

            _write_gold_major_indices_file(root)
            check_fn = _check_function(
                checks.gold_market_major_indices_daily_rank_matches_active_seed_order
            )
            self.assertTrue(check_fn(context, lake_root, duckdb_resource).passed)

            _write_gold_major_indices_file(
                root,
                rank_overrides={
                    active_rows[0].ts_code: active_rows[1].rank,
                    active_rows[1].ts_code: active_rows[0].rank,
                },
            )
            self.assertFalse(check_fn(context, lake_root, duckdb_resource).passed)

    def test_price_sanity_blocks_invalid_price_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = _PartitionContext(TARGET_TRADE_DATE)
            lake_root = LakeRootResource(root_path=str(root))
            duckdb_resource = DuckDBResource()
            first_code = active_major_indices_seed_rows(TARGET_TRADE_DATE)[0].ts_code

            _write_gold_major_indices_file(root)
            check_fn = _check_function(
                checks.gold_market_major_indices_daily_price_sanity
            )
            self.assertTrue(check_fn(context, lake_root, duckdb_resource).passed)

            _write_gold_major_indices_file(
                root,
                price_overrides={first_code: {"high": 8.0, "low": 9.0}},
            )
            self.assertFalse(check_fn(context, lake_root, duckdb_resource).passed)

    def test_seed_codes_exist_in_index_basic_passes_and_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = LakeRootResource(root_path=str(root))
            duckdb_resource = DuckDBResource()
            seed_codes = tuple(
                row.ts_code for row in active_major_indices_seed_rows(TARGET_TRADE_DATE)
            )
            check_fn = _check_function(
                checks.gold_market_major_indices_seed_codes_exist_in_index_basic
            )

            _write_silver_index_basic_file(root, seed_codes)
            self.assertTrue(check_fn(lake_root, duckdb_resource).passed)

            _write_silver_index_basic_file(root, seed_codes[1:])
            self.assertFalse(check_fn(lake_root, duckdb_resource).passed)


if __name__ == "__main__":
    unittest.main()
