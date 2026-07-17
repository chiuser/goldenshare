from pathlib import Path
import unittest

from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_DC_DAILY_TECHNICAL_SCHEMA,
)
from orchestrator.defs.run_contracts.dc_daily_technical_serving import (
    DC_DAILY_TECHNICAL_SERVING_COLUMNS,
    DC_DAILY_TECHNICAL_SERVING_INSERT_COLUMNS,
    DC_DAILY_TECHNICAL_SERVING_KEY_COLUMNS,
    DC_DAILY_TECHNICAL_SERVING_NULLABLE_COLUMNS,
    DC_DAILY_TECHNICAL_SERVING_TABLE,
)


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "clickhouse_migrations"
    / "sql"
    / "V4__create_dc_daily_technical.sql"
)


class DcDailyTechnicalServingMigrationTests(unittest.TestCase):
    def test_serving_columns_follow_gold_contract(self) -> None:
        expected = tuple(column.name for column in GOLD_DC_DAILY_TECHNICAL_SCHEMA)
        self.assertEqual(DC_DAILY_TECHNICAL_SERVING_COLUMNS, expected)
        self.assertEqual(
            DC_DAILY_TECHNICAL_SERVING_INSERT_COLUMNS,
            (*expected, "updated_at"),
        )

    def test_serving_contract_uses_frozen_table_and_key(self) -> None:
        self.assertEqual(
            DC_DAILY_TECHNICAL_SERVING_TABLE,
            "goldenshare_serving.board_fact_technical_daily",
        )
        self.assertEqual(
            DC_DAILY_TECHNICAL_SERVING_KEY_COLUMNS,
            ("ts_code", "trade_date", "category"),
        )

    def test_migration_declares_nullability_and_month_partitioning(self) -> None:
        sql = MIGRATION_PATH.read_text()
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS goldenshare_serving.board_fact_technical_daily",
            sql,
        )
        self.assertIn("PARTITION BY toYYYYMM(trade_date)", sql)
        self.assertIn("ORDER BY (trade_date, category, ts_code)", sql)
        self.assertIn("updated_at DateTime", sql)
        for column in DC_DAILY_TECHNICAL_SERVING_NULLABLE_COLUMNS:
            self.assertIn(f"{column} Nullable(Float64)", sql)

    def test_migration_contains_every_business_column_once(self) -> None:
        sql = MIGRATION_PATH.read_text()
        for column in DC_DAILY_TECHNICAL_SERVING_COLUMNS:
            self.assertEqual(sql.count(f"    {column} "), 1, column)
