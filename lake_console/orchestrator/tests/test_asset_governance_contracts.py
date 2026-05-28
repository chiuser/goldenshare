import re
import unittest

from orchestrator.defs.assets.calendar import (
    raw_tushare_trade_calendar,
    silver_trade_calendar,
)
from orchestrator.defs.assets.index_basic import (
    raw_tushare_index_basic,
    silver_index_basic,
)
from orchestrator.defs.assets.index_daily import (
    raw_tushare_index_daily_by_code,
    silver_index_daily,
)
from orchestrator.defs.assets.market_breadth import gold_market_breadth_daily
from orchestrator.defs.assets.market_major_indices import (
    gold_market_major_indices_daily,
)
from orchestrator.defs.assets.stock_basic import (
    raw_tushare_stock_basic,
    silver_stock_basic,
)
from orchestrator.defs.assets.stock_daily import (
    raw_tushare_stock_daily,
    silver_stock_daily,
)
from orchestrator.defs.assets.stock_return_distribution import (
    gold_stock_return_distribution,
)
from orchestrator.defs.assets.suspend_d import (
    raw_tushare_suspend_d,
    silver_stock_suspend_daily,
)
from orchestrator.defs.catalog import DATASET_CHINESE_NAMES
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
from orchestrator.defs.run_contracts.metadata import (
    DATA_CONTRACT_METADATA_KEY,
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
        self.assertEqual(len(ASSET_CONTRACTS), 15)

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
                self.assertEqual(
                    spec.metadata[PATH_TEMPLATE_METADATA_KEY],
                    ASSET_PATH_TEMPLATES[asset],
                )
