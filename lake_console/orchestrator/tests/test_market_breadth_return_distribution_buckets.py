from datetime import date
import tempfile
import unittest
from pathlib import Path

import duckdb

from orchestrator.defs.assets.clickhouse_serving import (
    CLICKHOUSE_MARKET_BREADTH_COLUMNS,
    _build_clickhouse_row,
    _replace_clickhouse_partition,
)
from orchestrator.defs.duckdb_sql import duckdb_string, stock_return_distribution_select


PARTITION_KEY = "2026-06-05"
ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[1]


def _write_silver_stock_daily_file(root: Path, pct_chg_values: tuple[float, ...]) -> Path:
    path = root / "silver_stock_daily.parquet"
    values_sql = ", ".join(
        f"(DATE {duckdb_string(PARTITION_KEY)}, {idx}, {pct_chg}::DOUBLE)"
        for idx, pct_chg in enumerate(pct_chg_values, start=1)
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT *
              FROM (VALUES {values_sql}) rows(trade_date, row_id, pct_chg)
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )
    return path


class _FakeClickHouseClient:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.operations: list[str] = []

    @staticmethod
    def _selected_dates(params) -> set:
        if not isinstance(params, dict):
            return set()
        if "trade_date" in params:
            return {params["trade_date"]}
        return {
            value
            for key, value in params.items()
            if key.startswith("trade_date_")
        }

    def execute(self, query: str, params=None, data=None):
        normalised_query = " ".join(query.split()).upper()
        if normalised_query.startswith("SET LIGHTWEIGHT_DELETES_SYNC"):
            self.operations.append("set")
            return []
        if normalised_query.startswith("DELETE FROM"):
            self.operations.append("delete")
            selected_dates = self._selected_dates(params)
            self.rows = [row for row in self.rows if row[0] not in selected_dates]
            return []
        if normalised_query.startswith("SELECT TRADE_DATE, COUNT()"):
            self.operations.append("count")
            selected_dates = self._selected_dates(params)
            return [
                (trade_date, sum(1 for row in self.rows if row[0] == trade_date))
                for trade_date in selected_dates
                if any(row[0] == trade_date for row in self.rows)
            ]
        if normalised_query.startswith("SELECT COUNT()"):
            self.operations.append("count")
            selected_dates = self._selected_dates(params)
            trade_date = next(iter(selected_dates))
            return [(sum(1 for row in self.rows if row[0] == trade_date),)]
        if normalised_query.startswith("INSERT INTO"):
            self.operations.append("insert")
            insert_rows = data if data is not None else params
            self.rows.extend(insert_rows)
            return []
        raise AssertionError(f"Unexpected query: {query}")


class MarketBreadthReturnDistributionBucketTests(unittest.TestCase):
    def test_old_bucket_field_names_are_removed_from_formal_python_code(self) -> None:
        old_field_names = (
            "down_" + "gt_7_count",
            "up_" + "gt_7_count",
        )
        issues: list[str] = []
        for root in (
            ORCHESTRATOR_ROOT / "src" / "orchestrator" / "defs",
            ORCHESTRATOR_ROOT / "tests",
        ):
            for path in root.rglob("*.py"):
                source = path.read_text()
                for old_field_name in old_field_names:
                    if old_field_name in source:
                        issues.append(f"{path.relative_to(ORCHESTRATOR_ROOT)}:{old_field_name}")

        self.assertEqual(issues, [])

    def test_v3_clickhouse_migration_only_renames_and_adds_columns(self) -> None:
        old_down_field = "down_" + "gt_7_count"
        old_up_field = "up_" + "gt_7_count"
        migration_path = (
            ORCHESTRATOR_ROOT
            / "clickhouse_migrations"
            / "sql"
            / "V3__split_market_breadth_return_distribution_buckets.sql"
        )
        migration_sql = migration_path.read_text()

        self.assertIn(
            f"RENAME COLUMN {old_down_field} TO down_7_10_count",
            migration_sql,
        )
        self.assertIn(
            f"RENAME COLUMN {old_up_field} TO up_7_10_count",
            migration_sql,
        )
        self.assertIn("ADD COLUMN down_gt_10_count UInt32", migration_sql)
        self.assertIn("ADD COLUMN up_gt_10_count UInt32", migration_sql)
        self.assertNotIn("UPDATE", migration_sql.upper())

    def test_duckdb_distribution_uses_eleven_bucket_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            silver_path = _write_silver_stock_daily_file(
                Path(temp_dir),
                (-10.01, -10.0, -7.0, -5.0, -3.0, 0.0, 3.0, 5.0, 7.0, 10.0, 10.01),
            )
            with duckdb.connect(database=":memory:") as connection:
                row = connection.execute(
                    stock_return_distribution_select(silver_path, PARTITION_KEY)
                ).fetchone()

        self.assertEqual(
            row,
            (
                date.fromisoformat(PARTITION_KEY),
                1,
                1,
                1,
                1,
                1,
                1,
                1,
                1,
                1,
                1,
                1,
                11,
            ),
        )

    def test_clickhouse_row_order_matches_new_schema_contract(self) -> None:
        breadth_row = {
            "trade_date": PARTITION_KEY,
            "up_count": 6,
            "down_count": 5,
            "flat_count": 1,
            "total_count": 12,
            "red_rate": 50.0,
        }
        distribution_row = {
            "trade_date": PARTITION_KEY,
            "down_gt_10_count": 1,
            "down_7_10_count": 2,
            "down_5_7_count": 3,
            "down_3_5_count": 4,
            "down_0_3_count": 5,
            "flat_count": 1,
            "up_0_3_count": 6,
            "up_3_5_count": 7,
            "up_5_7_count": 8,
            "up_7_10_count": 9,
            "up_gt_10_count": 10,
            "total_count": 12,
        }

        row = _build_clickhouse_row(
            partition_key=PARTITION_KEY,
            breadth_row=breadth_row,
            distribution_row=distribution_row,
        )
        row_dict = dict(zip(CLICKHOUSE_MARKET_BREADTH_COLUMNS, row, strict=True))

        self.assertEqual(row_dict["trade_date"], date.fromisoformat(PARTITION_KEY))
        self.assertEqual(row_dict["down_gt_10_count"], 1)
        self.assertEqual(row_dict["down_7_10_count"], 2)
        self.assertEqual(row_dict["up_7_10_count"], 9)
        self.assertEqual(row_dict["up_gt_10_count"], 10)
        self.assertEqual(
            tuple(row_dict)[:-1],
            CLICKHOUSE_MARKET_BREADTH_COLUMNS[:-1],
        )

    def test_clickhouse_replace_deletes_same_date_before_full_row_insert(self) -> None:
        partition_date = date.fromisoformat(PARTITION_KEY)
        old_row = (
            partition_date,
            *([0] * (len(CLICKHOUSE_MARKET_BREADTH_COLUMNS) - 2)),
            "2026-06-05 12:00:00",
        )
        new_row = (
            partition_date,
            *range(1, len(CLICKHOUSE_MARKET_BREADTH_COLUMNS) - 1),
            "2026-06-05 13:00:00",
        )
        client = _FakeClickHouseClient([old_row])

        _replace_clickhouse_partition(client, new_row)

        self.assertEqual(client.rows, [new_row])
        self.assertEqual(client.operations, ["set", "delete", "count", "insert", "count"])


if __name__ == "__main__":
    unittest.main()
