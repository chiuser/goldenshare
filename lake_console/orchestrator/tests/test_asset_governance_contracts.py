import re
import unittest

from orchestrator.defs.assets.calendar import (
    TRADE_CALENDAR_RAW_COLUMN_TYPES,
    raw_tushare_trade_calendar,
    silver_trade_calendar,
)
from orchestrator.defs.assets.clickhouse_serving import (
    CLICKHOUSE_MARKET_BREADTH_COLUMNS,
    ch_share_fact_market_breadth_daily,
)
from orchestrator.defs.assets.index_basic import (
    INDEX_BASIC_RAW_COLUMN_TYPES,
    raw_tushare_index_basic,
    silver_index_basic,
)
from orchestrator.defs.assets.index_daily import (
    INDEX_DAILY_RAW_COLUMN_TYPES,
    INDEX_DAILY_SILVER_COLUMN_TYPES,
    raw_tushare_index_daily_by_code,
    silver_index_daily,
)
from orchestrator.defs.assets.market_breadth import gold_market_breadth_daily
from orchestrator.defs.assets.market_breadth import MARKET_BREADTH_DAILY_COLUMNS
from orchestrator.defs.assets.market_major_indices import (
    MARKET_MAJOR_INDICES_DAILY_COLUMNS,
    MARKET_MAJOR_INDICES_DAILY_COLUMN_TYPES,
    gold_market_major_indices_daily,
)
from orchestrator.defs.assets.stock_basic import (
    STOCK_BASIC_RAW_COLUMN_TYPES,
    raw_tushare_stock_basic,
    silver_stock_basic,
)
from orchestrator.defs.assets.stock_daily import (
    STOCK_DAILY_RAW_COLUMN_TYPES,
    raw_tushare_stock_daily,
    silver_stock_daily,
)
from orchestrator.defs.assets.stock_return_distribution import (
    STOCK_RETURN_DISTRIBUTION_COLUMNS,
    gold_stock_return_distribution,
)
from orchestrator.defs.assets.suspend_d import (
    SUSPEND_D_RAW_COLUMN_TYPES,
    raw_tushare_suspend_d,
    silver_stock_suspend_daily,
)
from orchestrator.defs.catalog import DATASET_CHINESE_NAMES
from orchestrator.defs.checks.index_basic_checks import INDEX_BASIC_SILVER_COLUMN_TYPES
from orchestrator.defs.duckdb_sql import (
    INDEX_BASIC_RAW_COLUMNS,
    INDEX_BASIC_SILVER_COLUMNS,
    INDEX_DAILY_RAW_COLUMNS,
    INDEX_DAILY_SILVER_COLUMNS,
    STOCK_BASIC_RAW_COLUMNS,
    STOCK_BASIC_SILVER_REQUIRED_COLUMNS,
    STOCK_DAILY_RAW_REQUIRED_COLUMNS,
    STOCK_DAILY_SILVER_REQUIRED_COLUMNS,
    SUSPEND_D_RAW_COLUMNS,
    SUSPEND_D_SILVER_REQUIRED_COLUMNS,
    TRADE_CALENDAR_RAW_REQUIRED_COLUMNS,
    TRADE_CALENDAR_SILVER_REQUIRED_COLUMNS,
)
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    gold_market_breadth_daily_path,
    gold_market_major_indices_daily_path,
    gold_stock_return_distribution_path,
    lake_path_template,
    raw_index_basic_path,
    raw_index_daily_by_code_path,
    raw_stock_basic_path,
    raw_stock_daily_path,
    raw_suspend_d_path,
    raw_trade_calendar_path,
    silver_index_basic_path,
    silver_index_daily_path,
    silver_stock_basic_path,
    silver_stock_daily_path,
    silver_stock_suspend_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.asset_tags import (
    ASSET_LAYER_TAG,
    DATA_DOMAIN_TAG,
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    CH_SHARE_FACT_MARKET_BREADTH_DAILY_SCHEMA,
    GOLD_MARKET_BREADTH_DAILY_SCHEMA,
    GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA,
    GOLD_STOCK_RETURN_DISTRIBUTION_SCHEMA,
    RAW_TUSHARE_INDEX_BASIC_SCHEMA,
    RAW_TUSHARE_INDEX_DAILY_BY_CODE_SCHEMA,
    RAW_TUSHARE_STOCK_BASIC_SCHEMA,
    RAW_TUSHARE_STOCK_DAILY_SCHEMA,
    RAW_TUSHARE_STOCK_SUSPEND_DAILY_SCHEMA,
    RAW_TUSHARE_TRADE_CALENDAR_SCHEMA,
    SILVER_INDEX_BASIC_SCHEMA,
    SILVER_INDEX_DAILY_SCHEMA,
    SILVER_STOCK_BASIC_SCHEMA,
    SILVER_STOCK_DAILY_SCHEMA,
    SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
    SILVER_TRADE_CALENDAR_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import (
    DATA_CONTRACT_METADATA_KEY,
    DAGSTER_COLUMN_SCHEMA_METADATA_KEY,
    DATASET_ID_METADATA_KEY,
    DATASET_NAME_METADATA_KEY,
    PATH_TEMPLATE_METADATA_KEY,
    SOURCE_SYSTEM_METADATA_KEY,
    build_dataset_metadata,
)


DAGSTER_TAG_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,63}$")


ASSET_CONTRACTS = {
    raw_tushare_trade_calendar: ("raw", "basic_data", "trade_cal", "交易日历"),
    silver_trade_calendar: ("silver", "basic_data", "trade_cal", "交易日历"),
    raw_tushare_stock_basic: ("raw", "basic_data", "stock_basic", "股票基础信息"),
    silver_stock_basic: ("silver", "basic_data", "stock_basic", "股票基础信息"),
    raw_tushare_suspend_d: ("raw", "quote_data", "suspend_d", "每日停复牌信息"),
    silver_stock_suspend_daily: ("silver", "quote_data", "suspend_d", "每日停复牌信息"),
    raw_tushare_stock_daily: ("raw", "quote_data", "daily", "A股日线行情"),
    silver_stock_daily: ("silver", "quote_data", "daily", "A股日线行情"),
    raw_tushare_index_basic: ("raw", "index_topic", "index_basic", "指数基本信息"),
    silver_index_basic: ("silver", "index_topic", "index_basic", "指数基本信息"),
    raw_tushare_index_daily_by_code: (
        "raw",
        "index_topic",
        "index_daily",
        "指数日线行情",
    ),
    silver_index_daily: ("silver", "index_topic", "index_daily", "指数日线行情"),
    gold_market_major_indices_daily: (
        "gold",
        "index_topic",
        "market_major_indices_daily",
        "主要指数日线",
    ),
    gold_market_breadth_daily: (
        "gold",
        "derived_metric",
        "market_breadth",
        "市场宽度",
    ),
    gold_stock_return_distribution: (
        "gold",
        "derived_metric",
        "stock_return_distribution",
        "股票涨跌幅分布",
    ),
    ch_share_fact_market_breadth_daily: (
        "serving",
        "derived_metric",
        "ch_share_fact_market_breadth_daily",
        "ClickHouse 市场宽度日表",
    ),
}

ASSET_PATH_TEMPLATES = {
    raw_tushare_trade_calendar: lake_path_template(
        raw_trade_calendar_path(PATH_TEMPLATE_LAKE_ROOT)
    ),
    silver_trade_calendar: lake_path_template(
        silver_trade_calendar_path(PATH_TEMPLATE_LAKE_ROOT)
    ),
    raw_tushare_stock_basic: lake_path_template(
        raw_stock_basic_path(PATH_TEMPLATE_LAKE_ROOT)
    ),
    silver_stock_basic: lake_path_template(
        silver_stock_basic_path(PATH_TEMPLATE_LAKE_ROOT)
    ),
    raw_tushare_suspend_d: lake_path_template(
        raw_suspend_d_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
    ),
    silver_stock_suspend_daily: lake_path_template(
        silver_stock_suspend_daily_path(
            PATH_TEMPLATE_LAKE_ROOT,
            PATH_TEMPLATE_PARTITION_KEY,
        )
    ),
    raw_tushare_stock_daily: lake_path_template(
        raw_stock_daily_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
    ),
    silver_stock_daily: lake_path_template(
        silver_stock_daily_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
    ),
    raw_tushare_index_basic: lake_path_template(
        raw_index_basic_path(PATH_TEMPLATE_LAKE_ROOT)
    ),
    silver_index_basic: lake_path_template(
        silver_index_basic_path(PATH_TEMPLATE_LAKE_ROOT)
    ),
    raw_tushare_index_daily_by_code: lake_path_template(
        raw_index_daily_by_code_path(
            PATH_TEMPLATE_LAKE_ROOT,
            PATH_TEMPLATE_PARTITION_KEY,
        )
    ),
    silver_index_daily: lake_path_template(
        silver_index_daily_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
    ),
    gold_market_major_indices_daily: lake_path_template(
        gold_market_major_indices_daily_path(
            PATH_TEMPLATE_LAKE_ROOT,
            PATH_TEMPLATE_PARTITION_KEY,
        )
    ),
    gold_market_breadth_daily: lake_path_template(
        gold_market_breadth_daily_path(
            PATH_TEMPLATE_LAKE_ROOT,
            PATH_TEMPLATE_PARTITION_KEY,
        )
    ),
    gold_stock_return_distribution: lake_path_template(
        gold_stock_return_distribution_path(
            PATH_TEMPLATE_LAKE_ROOT,
            PATH_TEMPLATE_PARTITION_KEY,
        )
    ),
}

ASSET_COLUMN_SCHEMAS = {
    raw_tushare_trade_calendar: RAW_TUSHARE_TRADE_CALENDAR_SCHEMA,
    raw_tushare_stock_basic: RAW_TUSHARE_STOCK_BASIC_SCHEMA,
    raw_tushare_suspend_d: RAW_TUSHARE_STOCK_SUSPEND_DAILY_SCHEMA,
    raw_tushare_stock_daily: RAW_TUSHARE_STOCK_DAILY_SCHEMA,
    raw_tushare_index_basic: RAW_TUSHARE_INDEX_BASIC_SCHEMA,
    raw_tushare_index_daily_by_code: RAW_TUSHARE_INDEX_DAILY_BY_CODE_SCHEMA,
    silver_trade_calendar: SILVER_TRADE_CALENDAR_SCHEMA,
    silver_stock_basic: SILVER_STOCK_BASIC_SCHEMA,
    silver_stock_suspend_daily: SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
    silver_stock_daily: SILVER_STOCK_DAILY_SCHEMA,
    silver_index_basic: SILVER_INDEX_BASIC_SCHEMA,
    silver_index_daily: SILVER_INDEX_DAILY_SCHEMA,
    gold_market_breadth_daily: GOLD_MARKET_BREADTH_DAILY_SCHEMA,
    gold_stock_return_distribution: GOLD_STOCK_RETURN_DISTRIBUTION_SCHEMA,
    gold_market_major_indices_daily: GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA,
    ch_share_fact_market_breadth_daily: CH_SHARE_FACT_MARKET_BREADTH_DAILY_SCHEMA,
}


class AssetGovernanceContractTests(unittest.TestCase):
    def test_build_asset_tags_returns_dagster_legal_values(self) -> None:
        tags = build_asset_tags(
            layer=AssetLayer.RAW,
            data_domain=DataDomain.BASIC_DATA,
        )

        self.assertEqual(tags[ASSET_LAYER_TAG], "raw")
        self.assertEqual(tags[DATA_DOMAIN_TAG], "basic_data")
        for value in tags.values():
            self.assertRegex(value, DAGSTER_TAG_VALUE_PATTERN)

    def test_build_asset_tags_rejects_old_chinese_values(self) -> None:
        with self.assertRaises(ValueError):
            build_asset_tags(layer="原始层", data_domain=DataDomain.BASIC_DATA)

        with self.assertRaises(ValueError):
            build_asset_tags(layer=AssetLayer.RAW, data_domain="基础数据")

    def test_build_dataset_metadata_uses_registered_chinese_names(self) -> None:
        self.assertEqual(
            build_dataset_metadata(dataset_id="market_major_indices_daily"),
            {
                DATASET_ID_METADATA_KEY: "market_major_indices_daily",
                DATASET_NAME_METADATA_KEY: "主要指数日线",
            },
        )
        self.assertEqual(DATASET_CHINESE_NAMES["market_major_indices"], "主要指数名单")

    def test_current_assets_have_governance_tags_and_dataset_metadata(self) -> None:
        self.assertEqual(len(ASSET_CONTRACTS), 16)

        for asset, (
            layer,
            data_domain,
            dataset_id,
            dataset_name,
        ) in ASSET_CONTRACTS.items():
            with self.subTest(asset=asset.key.to_user_string()):
                spec = asset.get_asset_spec()

                self.assertEqual(spec.tags[ASSET_LAYER_TAG], layer)
                self.assertEqual(spec.tags[DATA_DOMAIN_TAG], data_domain)
                for value in spec.tags.values():
                    self.assertRegex(value, DAGSTER_TAG_VALUE_PATTERN)

                self.assertEqual(spec.metadata[DATASET_ID_METADATA_KEY], dataset_id)
                self.assertEqual(spec.metadata[DATASET_NAME_METADATA_KEY], dataset_name)
                self.assertIn(SOURCE_SYSTEM_METADATA_KEY, spec.metadata)
                self.assertIn(DATA_CONTRACT_METADATA_KEY, spec.metadata)
                if asset in ASSET_PATH_TEMPLATES:
                    self.assertEqual(
                        spec.metadata[PATH_TEMPLATE_METADATA_KEY],
                        ASSET_PATH_TEMPLATES[asset],
                    )

    def test_assets_register_definition_column_schema(
        self,
    ) -> None:
        self.assertEqual(len(ASSET_COLUMN_SCHEMAS), len(ASSET_CONTRACTS))

        for asset, expected_schema in ASSET_COLUMN_SCHEMAS.items():
            with self.subTest(asset=asset.key.to_user_string()):
                spec = asset.get_asset_spec()
                schema_metadata = spec.metadata[DAGSTER_COLUMN_SCHEMA_METADATA_KEY]
                columns = schema_metadata.schema.columns

                self.assertEqual(
                    [column.name for column in columns],
                    [column.name for column in expected_schema],
                )
                self.assertEqual(
                    [column.type for column in columns],
                    [column.type for column in expected_schema],
                )
                self.assertEqual(
                    [column.description for column in columns],
                    [column.description for column in expected_schema],
                )

    def test_column_constants_are_derived_from_schema(
        self,
    ) -> None:
        self.assertEqual(
            TRADE_CALENDAR_RAW_REQUIRED_COLUMNS,
            tuple(column.name for column in RAW_TUSHARE_TRADE_CALENDAR_SCHEMA),
        )
        self.assertEqual(
            TRADE_CALENDAR_RAW_COLUMN_TYPES,
            {column.name: column.type for column in RAW_TUSHARE_TRADE_CALENDAR_SCHEMA},
        )
        self.assertEqual(
            STOCK_BASIC_RAW_COLUMNS,
            tuple(column.name for column in RAW_TUSHARE_STOCK_BASIC_SCHEMA),
        )
        self.assertEqual(
            STOCK_BASIC_RAW_COLUMN_TYPES,
            {column.name: column.type for column in RAW_TUSHARE_STOCK_BASIC_SCHEMA},
        )
        self.assertEqual(
            STOCK_DAILY_RAW_REQUIRED_COLUMNS,
            tuple(column.name for column in RAW_TUSHARE_STOCK_DAILY_SCHEMA),
        )
        self.assertEqual(
            STOCK_DAILY_RAW_COLUMN_TYPES,
            {column.name: column.type for column in RAW_TUSHARE_STOCK_DAILY_SCHEMA},
        )
        self.assertEqual(
            SUSPEND_D_RAW_COLUMNS,
            tuple(column.name for column in RAW_TUSHARE_STOCK_SUSPEND_DAILY_SCHEMA),
        )
        self.assertEqual(
            SUSPEND_D_RAW_COLUMN_TYPES,
            {
                column.name: column.type
                for column in RAW_TUSHARE_STOCK_SUSPEND_DAILY_SCHEMA
            },
        )
        self.assertEqual(
            INDEX_BASIC_RAW_COLUMNS,
            tuple(column.name for column in RAW_TUSHARE_INDEX_BASIC_SCHEMA),
        )
        self.assertEqual(
            INDEX_BASIC_RAW_COLUMN_TYPES,
            {column.name: column.type for column in RAW_TUSHARE_INDEX_BASIC_SCHEMA},
        )
        self.assertEqual(
            INDEX_DAILY_RAW_COLUMNS,
            tuple(column.name for column in RAW_TUSHARE_INDEX_DAILY_BY_CODE_SCHEMA),
        )
        self.assertEqual(
            INDEX_DAILY_RAW_COLUMN_TYPES,
            {
                column.name: column.type
                for column in RAW_TUSHARE_INDEX_DAILY_BY_CODE_SCHEMA
            },
        )
        self.assertEqual(
            TRADE_CALENDAR_SILVER_REQUIRED_COLUMNS,
            tuple(column.name for column in SILVER_TRADE_CALENDAR_SCHEMA),
        )
        self.assertEqual(
            STOCK_BASIC_SILVER_REQUIRED_COLUMNS,
            tuple(column.name for column in SILVER_STOCK_BASIC_SCHEMA),
        )
        self.assertEqual(
            STOCK_DAILY_SILVER_REQUIRED_COLUMNS,
            tuple(column.name for column in SILVER_STOCK_DAILY_SCHEMA),
        )
        self.assertEqual(
            SUSPEND_D_SILVER_REQUIRED_COLUMNS,
            tuple(column.name for column in SILVER_STOCK_SUSPEND_DAILY_SCHEMA),
        )
        self.assertEqual(
            INDEX_BASIC_SILVER_COLUMNS,
            tuple(column.name for column in SILVER_INDEX_BASIC_SCHEMA),
        )
        self.assertEqual(
            INDEX_BASIC_SILVER_COLUMN_TYPES,
            {column.name: column.type for column in SILVER_INDEX_BASIC_SCHEMA},
        )
        self.assertEqual(
            INDEX_DAILY_SILVER_COLUMNS,
            tuple(column.name for column in SILVER_INDEX_DAILY_SCHEMA),
        )
        self.assertEqual(
            INDEX_DAILY_SILVER_COLUMN_TYPES,
            {column.name: column.type for column in SILVER_INDEX_DAILY_SCHEMA},
        )
        self.assertEqual(
            MARKET_BREADTH_DAILY_COLUMNS,
            tuple(column.name for column in GOLD_MARKET_BREADTH_DAILY_SCHEMA),
        )
        self.assertEqual(
            STOCK_RETURN_DISTRIBUTION_COLUMNS,
            tuple(column.name for column in GOLD_STOCK_RETURN_DISTRIBUTION_SCHEMA),
        )
        self.assertEqual(
            MARKET_MAJOR_INDICES_DAILY_COLUMNS,
            tuple(column.name for column in GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA),
        )
        self.assertEqual(
            MARKET_MAJOR_INDICES_DAILY_COLUMN_TYPES,
            {
                column.name: column.type
                for column in GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA
            },
        )
        self.assertEqual(
            CLICKHOUSE_MARKET_BREADTH_COLUMNS,
            tuple(column.name for column in CH_SHARE_FACT_MARKET_BREADTH_DAILY_SCHEMA),
        )
