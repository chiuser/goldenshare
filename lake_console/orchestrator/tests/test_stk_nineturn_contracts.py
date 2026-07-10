import unittest
from pathlib import Path

from orchestrator.defs.catalog.lake_assets import (
    EventPolicy,
    IngestionSource,
    PartitionModel,
    PartitionPhysicalLayout,
    get_lake_asset_catalog_entry,
    get_partition_model_definition,
)
from orchestrator.defs.catalog.name_mapping import get_dataset_chinese_name
from orchestrator.defs.paths import (
    raw_stk_nineturn_path,
    silver_stock_nineturn_daily_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_STK_NINETURN_SCHEMA,
    SILVER_STOCK_NINETURN_DAILY_SCHEMA,
)
from orchestrator.defs.stk_nineturn_contract import (
    RAW_STK_NINETURN_COLUMNS,
    RAW_STK_NINETURN_COLUMN_TYPES,
    SILVER_STOCK_NINETURN_DAILY_COLUMNS,
    SILVER_STOCK_NINETURN_DAILY_COLUMN_TYPES,
)


class StkNineturnContractTests(unittest.TestCase):
    def test_schema_contracts_and_derived_constants_are_stable(self) -> None:
        expected_columns = (
            "ts_code",
            "trade_date",
            "freq",
            "open",
            "high",
            "low",
            "close",
            "vol",
            "amount",
            "up_count",
            "down_count",
            "nine_up_turn",
            "nine_down_turn",
        )

        self.assertEqual(RAW_STK_NINETURN_COLUMNS, expected_columns)
        self.assertEqual(SILVER_STOCK_NINETURN_DAILY_COLUMNS, expected_columns)
        self.assertEqual(
            RAW_STK_NINETURN_COLUMN_TYPES,
            {column.name: column.type for column in RAW_TUSHARE_STK_NINETURN_SCHEMA},
        )
        self.assertEqual(
            SILVER_STOCK_NINETURN_DAILY_COLUMN_TYPES,
            {
                column.name: column.type
                for column in SILVER_STOCK_NINETURN_DAILY_SCHEMA
            },
        )
        self.assertEqual(RAW_STK_NINETURN_COLUMN_TYPES["trade_date"], "DATE")
        self.assertEqual(
            SILVER_STOCK_NINETURN_DAILY_COLUMN_TYPES["trade_date"], "DATE"
        )
        self.assertEqual(RAW_STK_NINETURN_COLUMN_TYPES["up_count"], "DOUBLE")
        self.assertEqual(
            SILVER_STOCK_NINETURN_DAILY_COLUMN_TYPES["up_count"], "INTEGER"
        )
        self.assertTrue(
            set(RAW_STK_NINETURN_COLUMNS).issubset(
                SILVER_STOCK_NINETURN_DAILY_COLUMNS
            )
        )

    def test_paths_use_formal_raw_and_silver_layouts(self) -> None:
        root = Path("/lake")

        self.assertEqual(
            raw_stk_nineturn_path(root, "2026-07-09"),
            Path(
                "/lake/raw/tushare/stk_nineturn/"
                "trade_date=2026-07-09/part-000.parquet"
            ),
        )
        self.assertEqual(
            silver_stock_nineturn_daily_path(root, "2026-07-09"),
            Path(
                "/lake/silver/quote/stock_nineturn_daily/"
                "trade_date=2026-07-09/part-000.parquet"
            ),
        )

    def test_raw_catalog_entry_expresses_dual_source_boundary(self) -> None:
        entry = get_lake_asset_catalog_entry("raw_tushare_stk_nineturn")

        self.assertEqual(entry.dataset_id, "stk_nineturn")
        self.assertEqual(
            entry.ingestion_sources,
            (IngestionSource.TUSHARE_API, IngestionSource.PROD_DB_READONLY),
        )
        self.assertEqual(
            entry.default_daily_ingestion_source,
            IngestionSource.TUSHARE_API,
        )
        self.assertEqual(
            entry.bootstrap_sources,
            (IngestionSource.PROD_DB_READONLY,),
        )
        self.assertEqual(
            entry.event_policy,
            EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        )
        self.assertEqual(
            entry.blocking_check_names,
            (
                "raw_tushare_stk_nineturn_contract_check",
                "raw_tushare_stk_nineturn_content_integrity_check",
            ),
        )

    def test_silver_catalog_entry_expresses_derived_boundary(self) -> None:
        entry = get_lake_asset_catalog_entry("silver_stock_nineturn_daily")

        self.assertEqual(entry.dataset_id, "stock_nineturn_daily")
        self.assertEqual(
            entry.partition_model,
            PartitionModel.TRADE_DATE_PARTITION_SILVER_STOCK_NINETURN_DAILY,
        )
        self.assertEqual(
            entry.bootstrap_sources,
            (IngestionSource.DERIVED_FROM_ASSETS,),
        )
        self.assertEqual(
            entry.event_policy,
            EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        )
        self.assertEqual(
            entry.blocking_check_names,
            (
                "silver_stock_nineturn_daily_contract_check",
                "silver_stock_nineturn_daily_canonical_integrity_check",
            ),
        )

    def test_partition_models_exist_for_raw_and_future_silver_asset(self) -> None:
        raw_model = get_partition_model_definition(
            PartitionModel.TRADE_DATE_PARTITION_RAW_STK_NINETURN
        )
        silver_model = get_partition_model_definition(
            PartitionModel.TRADE_DATE_PARTITION_SILVER_STOCK_NINETURN_DAILY
        )

        self.assertEqual(raw_model.dagster_partition_dimension, "trade_date")
        self.assertEqual(silver_model.dagster_partition_dimension, "trade_date")
        self.assertEqual(
            raw_model.physical_layout,
            PartitionPhysicalLayout.PARTITION_FILE,
        )
        self.assertEqual(
            silver_model.physical_layout,
            PartitionPhysicalLayout.PARTITION_FILE,
        )

    def test_dataset_names_are_registered(self) -> None:
        self.assertEqual(get_dataset_chinese_name("stk_nineturn"), "神奇九转")
        self.assertEqual(
            get_dataset_chinese_name("stock_nineturn_daily"),
            "股票日线神奇九转",
        )


if __name__ == "__main__":
    unittest.main()
