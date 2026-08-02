import importlib
import pkgutil
import re
import unittest

from orchestrator.defs.assets.calendar import (
    TRADE_CALENDAR_RAW_COLUMN_TYPES,
    raw_tushare_trade_calendar,
    silver_trade_calendar,
)
from orchestrator.defs.assets.adj_factor import (
    ADJ_FACTOR_COLUMNS,
    ADJ_FACTOR_RAW_COLUMN_TYPES,
    ADJ_FACTOR_SILVER_COLUMN_TYPES,
    raw_tushare_adj_factor,
    silver_adj_factor,
)
from orchestrator.defs.assets.clickhouse_serving import (
    CLICKHOUSE_MARKET_BREADTH_COLUMNS,
    ch_share_fact_market_breadth_daily,
    prod_ch_share_fact_market_breadth_daily,
)
from orchestrator.defs.assets.dc_daily_technical_serving import (
    ch_dc_daily_technical,
    prod_ch_dc_daily_technical,
)
from orchestrator.defs.assets.lake_root_health import lake_root_health
from orchestrator.defs.assets.index_basic import (
    INDEX_BASIC_RAW_COLUMN_TYPES,
    raw_tushare_index_basic,
    silver_index_basic,
)
from orchestrator.defs.assets.index_daily import (
    INDEX_DAILY_RAW_COLUMN_TYPES,
    INDEX_DAILY_SILVER_COLUMN_TYPES,
    raw_index_daily,
    silver_index_daily,
)
from orchestrator.defs.assets.market_breadth import gold_market_breadth_daily
from orchestrator.defs.assets.market_breadth import MARKET_BREADTH_DAILY_COLUMNS
from orchestrator.defs.assets.market_major_indices import (
    MARKET_MAJOR_INDICES_DAILY_COLUMNS,
    MARKET_MAJOR_INDICES_DAILY_COLUMN_TYPES,
    gold_market_major_indices_daily,
)
from orchestrator.defs.assets.namechange import (
    NAMECHANGE_RAW_COLUMN_TYPES,
    NAMECHANGE_SILVER_COLUMN_TYPES,
    raw_tushare_namechange,
    silver_namechange,
)
from orchestrator.defs.assets.stock_basic import (
    STOCK_BASIC_RAW_COLUMN_TYPES,
    raw_tushare_stock_basic,
    silver_stock_basic,
)
from orchestrator.defs.assets.stock_lifecycle import silver_stock_lifecycle
from orchestrator.defs.assets.stock_identity_map import silver_stock_identity_map
from orchestrator.defs.assets.dc_industry_hierarchy import silver_dc_industry_hierarchy
from orchestrator.defs.assets.stock_daily import (
    STOCK_DAILY_RAW_COLUMN_TYPES,
    raw_tushare_stock_daily,
    silver_stock_daily,
)
from orchestrator.defs.assets.stock_daily_qfq import gold_stock_daily_qfq
from orchestrator.defs.assets.stk_nineturn import (
    raw_tushare_stk_nineturn,
    silver_stock_nineturn_daily,
)
from orchestrator.defs.assets.stk_mins import (
    GOLD_STK_MINS_QFQ_COLUMNS,
    STK_MINS_RAW_COLUMN_TYPES,
    gold_stk_mins_qfq_1m,
    gold_stk_mins_qfq_5m,
    gold_stk_mins_qfq_15m,
    gold_stk_mins_qfq_30m,
    gold_stk_mins_qfq_60m,
    gold_stk_mins_qfq_90m,
    gold_stk_mins_qfq_120m,
    raw_stk_mins_1m,
    raw_stk_mins_5m,
    raw_stk_mins_15m,
    raw_stk_mins_30m,
    raw_stk_mins_60m,
    silver_stk_mins_1m,
    silver_stk_mins_5m,
    silver_stk_mins_15m,
    silver_stk_mins_30m,
    silver_stk_mins_60m,
)
from orchestrator.defs.assets.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS,
)
from orchestrator.defs.assets.stock_return_distribution import (
    STOCK_RETURN_DISTRIBUTION_COLUMNS,
    gold_stock_return_distribution,
)
from orchestrator.defs.assets.wealth_market_turnover import (
    WEALTH_MARKET_TURNOVER_COLUMNS,
    gold_wealth_market_turnover,
)
from orchestrator.defs.assets.wealth_market_turnover_prod_core import (
    prod_core_wealth_market_turnover,
)
from orchestrator.defs.assets.suspend_d import (
    SUSPEND_D_RAW_COLUMN_TYPES,
    raw_tushare_suspend_d,
    silver_stock_suspend_daily,
)
import orchestrator.defs.checks as checks_pkg
from orchestrator.defs.catalog import (
    DATASET_CHINESE_NAMES,
    PartitionModel,
    PartitionPhysicalLayout,
    WritePolicy,
    get_lake_asset_catalog_entry,
    get_partition_model_definition,
    list_lake_asset_catalog_entries,
    list_lake_asset_entries_by_dataset_id,
    list_lake_asset_keys,
)
from orchestrator.defs.checks.index_basic_checks import INDEX_BASIC_SILVER_COLUMN_TYPES
from orchestrator.defs.duckdb_sql import (
    ADJ_FACTOR_RAW_REQUIRED_COLUMNS,
    ADJ_FACTOR_SILVER_REQUIRED_COLUMNS,
    INDEX_BASIC_RAW_COLUMNS,
    INDEX_BASIC_SILVER_COLUMNS,
    INDEX_DAILY_RAW_COLUMNS,
    INDEX_DAILY_SILVER_COLUMNS,
    NAMECHANGE_RAW_COLUMNS,
    NAMECHANGE_SILVER_REQUIRED_COLUMNS,
    SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS,
    STOCK_LIFECYCLE_SILVER_REQUIRED_COLUMNS,
    STOCK_BASIC_RAW_COLUMNS,
    STOCK_BASIC_SILVER_REQUIRED_COLUMNS,
    STOCK_DAILY_RAW_REQUIRED_COLUMNS,
    STOCK_DAILY_SILVER_REQUIRED_COLUMNS,
    STK_MINS_RAW_REQUIRED_COLUMNS,
    SUSPEND_D_RAW_COLUMNS,
    SUSPEND_D_SILVER_REQUIRED_COLUMNS,
    TRADE_CALENDAR_RAW_REQUIRED_COLUMNS,
    TRADE_CALENDAR_SILVER_REQUIRED_COLUMNS,
)
from orchestrator.defs.partitions import (
    cn_a_index_trade_days,
    cn_a_stock_trade_days,
    cn_a_stk_nineturn_trade_days,
    cn_a_stock_mins_silver_trade_days,
    cn_a_stock_mins_trade_days,
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
    GOLD_STOCK_DAILY_QFQ_SCHEMA,
    GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
    GOLD_STK_MINS_QFQ_SCHEMA,
    GOLD_STOCK_RETURN_DISTRIBUTION_SCHEMA,
    GOLD_WEALTH_MARKET_TURNOVER_SCHEMA,
    RAW_INDEX_DAILY_SCHEMA,
    RAW_TUSHARE_INDEX_BASIC_SCHEMA,
    RAW_TUSHARE_NAMECHANGE_SCHEMA,
    RAW_TUSHARE_ADJ_FACTOR_SCHEMA,
    RAW_STK_MINS_SCHEMA,
    RAW_TUSHARE_STOCK_BASIC_SCHEMA,
    RAW_TUSHARE_STOCK_DAILY_SCHEMA,
    RAW_TUSHARE_STK_NINETURN_SCHEMA,
    RAW_TUSHARE_STOCK_SUSPEND_DAILY_SCHEMA,
    RAW_TUSHARE_TRADE_CALENDAR_SCHEMA,
    SILVER_INDEX_BASIC_SCHEMA,
    SILVER_INDEX_DAILY_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_NAMECHANGE_SCHEMA,
    SILVER_STOCK_BASIC_SCHEMA,
    SILVER_STOCK_DAILY_SCHEMA,
    SILVER_STOCK_NINETURN_DAILY_SCHEMA,
    SILVER_STOCK_IDENTITY_MAP_SCHEMA,
    SILVER_STOCK_LIFECYCLE_SCHEMA,
    SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
    SILVER_TRADE_CALENDAR_SCHEMA,
)
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMNS,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_COLUMNS,
)
from orchestrator.defs.stk_nineturn_contract import (
    RAW_STK_NINETURN_COLUMNS,
    RAW_STK_NINETURN_COLUMN_TYPES,
    SILVER_STOCK_NINETURN_DAILY_COLUMNS,
    SILVER_STOCK_NINETURN_DAILY_COLUMN_TYPES,
)
from orchestrator.defs.run_contracts.metadata import (
    DATA_CONTRACT_METADATA_KEY,
    DAGSTER_COLUMN_SCHEMA_METADATA_KEY,
    DATASET_ID_METADATA_KEY,
    DATASET_NAME_METADATA_KEY,
    PATH_TEMPLATE_METADATA_KEY,
    SOURCE_API_METADATA_KEY,
    SOURCE_DOC_METADATA_KEY,
    SOURCE_SYSTEM_METADATA_KEY,
    build_dataset_metadata,
)


DAGSTER_TAG_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,63}$")


ACTIVE_ASSET_DEFINITIONS = (
    raw_tushare_trade_calendar,
    silver_trade_calendar,
    raw_tushare_stock_basic,
    silver_stock_basic,
    silver_stock_lifecycle,
    raw_tushare_namechange,
    silver_namechange,
    silver_stock_identity_map,
    silver_dc_industry_hierarchy,
    raw_tushare_suspend_d,
    silver_stock_suspend_daily,
    raw_tushare_stock_daily,
    raw_tushare_stk_nineturn,
    silver_stock_nineturn_daily,
    silver_stock_daily,
    raw_tushare_adj_factor,
    silver_adj_factor,
    gold_stock_daily_qfq,
    raw_stk_mins_1m,
    raw_stk_mins_5m,
    raw_stk_mins_15m,
    raw_stk_mins_30m,
    raw_stk_mins_60m,
    silver_stk_mins_1m,
    silver_stk_mins_5m,
    silver_stk_mins_15m,
    silver_stk_mins_30m,
    silver_stk_mins_60m,
    gold_stk_mins_qfq_1m,
    gold_stk_mins_qfq_5m,
    gold_stk_mins_qfq_15m,
    gold_stk_mins_qfq_30m,
    gold_stk_mins_qfq_60m,
    gold_stk_mins_qfq_90m,
    gold_stk_mins_qfq_120m,
    *GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS,
    raw_tushare_index_basic,
    silver_index_basic,
    raw_index_daily,
    silver_index_daily,
    gold_market_major_indices_daily,
    gold_market_breadth_daily,
    gold_stock_return_distribution,
    gold_wealth_market_turnover,
    prod_core_wealth_market_turnover,
    ch_share_fact_market_breadth_daily,
    prod_ch_share_fact_market_breadth_daily,
    ch_dc_daily_technical,
    prod_ch_dc_daily_technical,
    lake_root_health,
)


def _asset_specs_and_definitions_by_key():
    specs = {}
    definitions = {}
    for asset_definition in ACTIVE_ASSET_DEFINITIONS:
        for asset_key in asset_definition.keys:
            key = asset_key.to_user_string()
            specs[key] = asset_definition.get_asset_spec(asset_key)
            definitions[key] = asset_definition
    return specs, definitions


ACTIVE_ASSET_SPECS_BY_KEY, ACTIVE_ASSETS_BY_KEY = _asset_specs_and_definitions_by_key()
ASSETS_WITHOUT_COLUMN_SCHEMA = {"lake_root_health"}
CONTRACT_ONLY_CATALOG_ASSET_KEYS = {
    "raw_tushare_dc_index",
    "raw_tushare_dc_member",
    "raw_tushare_dc_daily",
    "silver_dc_index",
    "silver_dc_member",
    "silver_dc_daily",
    "gold_dc_daily_technical",
}


def _catalog_entries_by_key():
    return {entry.asset_key: entry for entry in list_lake_asset_catalog_entries()}


def _blocking_check_names_by_asset_key() -> dict[str, set[str]]:
    check_names: dict[str, set[str]] = {}
    for module_info in pkgutil.iter_modules(checks_pkg.__path__):
        if module_info.name.startswith("__"):
            continue
        module = importlib.import_module(f"orchestrator.defs.checks.{module_info.name}")
        for value in vars(module).values():
            specs = getattr(value, "check_specs", None)
            if specs is None:
                continue
            for spec in specs:
                if not spec.blocking:
                    continue
                check_names.setdefault(spec.asset_key.to_user_string(), set()).add(
                    spec.name
                )
    return check_names


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

        platform_tags = build_asset_tags(
            layer=AssetLayer.PLATFORM,
            data_domain=DataDomain.PLATFORM_OBSERVABILITY,
        )
        self.assertEqual(platform_tags[ASSET_LAYER_TAG], "platform")
        self.assertEqual(
            platform_tags[DATA_DOMAIN_TAG],
            "platform_observability",
        )
        for value in platform_tags.values():
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
        catalog_entries = _catalog_entries_by_key()
        active_catalog_entries = {
            asset_key: entry
            for asset_key, entry in catalog_entries.items()
            if asset_key not in CONTRACT_ONLY_CATALOG_ASSET_KEYS
        }
        self.assertEqual(len(active_catalog_entries), len(ACTIVE_ASSETS_BY_KEY))
        self.assertEqual(set(active_catalog_entries), set(ACTIVE_ASSETS_BY_KEY))

        for asset_key, entry in active_catalog_entries.items():
            with self.subTest(asset=asset_key):
                spec = ACTIVE_ASSET_SPECS_BY_KEY[asset_key]

                self.assertEqual(spec.group_name, entry.group_name)
                self.assertEqual(spec.tags[ASSET_LAYER_TAG], entry.layer.value)
                self.assertEqual(spec.tags[DATA_DOMAIN_TAG], entry.data_domain.value)
                for value in spec.tags.values():
                    self.assertRegex(value, DAGSTER_TAG_VALUE_PATTERN)

                self.assertEqual(
                    spec.metadata[DATASET_ID_METADATA_KEY],
                    entry.dataset_id,
                )
                self.assertEqual(
                    spec.metadata[DATASET_NAME_METADATA_KEY],
                    entry.dataset_name,
                )
                self.assertEqual(
                    spec.metadata[SOURCE_SYSTEM_METADATA_KEY],
                    entry.source_system.value,
                )
                self.assertEqual(
                    spec.metadata[DATA_CONTRACT_METADATA_KEY],
                    entry.data_contract,
                )
                if entry.path_template is None:
                    self.assertNotIn(PATH_TEMPLATE_METADATA_KEY, spec.metadata)
                else:
                    self.assertEqual(
                        spec.metadata[PATH_TEMPLATE_METADATA_KEY],
                        entry.path_template,
                    )
                if entry.source_api is not None:
                    self.assertEqual(
                        spec.metadata[SOURCE_API_METADATA_KEY],
                        entry.source_api,
                    )
                if entry.source_doc is not None:
                    self.assertEqual(
                        spec.metadata[SOURCE_DOC_METADATA_KEY],
                        entry.source_doc,
                    )

    def test_catalog_api_returns_registered_entries(self) -> None:
        entries = list_lake_asset_catalog_entries()

        self.assertIsInstance(entries, tuple)
        self.assertEqual(
            len(entries),
            len(ACTIVE_ASSETS_BY_KEY) + len(CONTRACT_ONLY_CATALOG_ASSET_KEYS),
        )
        self.assertEqual(tuple(entry.asset_key for entry in entries), list_lake_asset_keys())
        self.assertEqual(
            set(list_lake_asset_keys()),
            set(ACTIVE_ASSETS_BY_KEY) | CONTRACT_ONLY_CATALOG_ASSET_KEYS,
        )
        self.assertIs(
            get_lake_asset_catalog_entry("lake_root_health"),
            _catalog_entries_by_key()["lake_root_health"],
        )

        qfq_entries = list_lake_asset_entries_by_dataset_id("stk_mins_qfq")
        self.assertEqual(len(qfq_entries), 7)
        self.assertEqual({entry.dataset_id for entry in qfq_entries}, {"stk_mins_qfq"})

        with self.assertRaises(KeyError):
            get_lake_asset_catalog_entry("missing_asset")
        with self.assertRaises(KeyError):
            get_partition_model_definition("missing_partition_model")  # type: ignore[arg-type]

    def test_partition_models_are_registered_and_policy_aligned(self) -> None:
        expected_write_policy_by_layout = {
            PartitionPhysicalLayout.SINGLE_FILE: WritePolicy.SINGLE_FILE_ATOMIC_REPLACE,
            PartitionPhysicalLayout.PARTITION_FILE: WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
            PartitionPhysicalLayout.STOCK_YEAR_FILE: WritePolicy.STOCK_YEAR_ATOMIC_REPLACE,
            PartitionPhysicalLayout.SERVING_TABLE: WritePolicy.CLICKHOUSE_TABLE_SYNC,
            PartitionPhysicalLayout.POSTGRES_TABLE: WritePolicy.POSTGRES_TABLE_SYNC,
            PartitionPhysicalLayout.NO_DATA_FILE: WritePolicy.NO_DATA_FILE,
        }

        for entry in list_lake_asset_catalog_entries():
            with self.subTest(asset=entry.asset_key):
                definition = get_partition_model_definition(entry.partition_model)
                self.assertEqual(definition.model, entry.partition_model)
                self.assertEqual(definition.layer, entry.layer)
                self.assertEqual(
                    entry.write_policy,
                    expected_write_policy_by_layout[definition.physical_layout],
                )
                if entry.dataset_id == "stk_mins_qfq":
                    self.assertEqual(
                        entry.partition_model,
                        PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_MINS_QFQ_STOCK_YEAR_FILE,
                    )
                    self.assertEqual(
                        definition.physical_layout,
                        PartitionPhysicalLayout.STOCK_YEAR_FILE,
                    )

    def test_raw_index_daily_catalog_and_asset_are_trade_date_partitioned(self) -> None:
        entry = get_lake_asset_catalog_entry("raw_index_daily")
        definition = get_partition_model_definition(entry.partition_model)

        self.assertEqual(
            entry.partition_model,
            PartitionModel.TRADE_DATE_PARTITION_RAW_INDEX_DAILY,
        )
        self.assertEqual(definition.dagster_partition_dimension, "trade_date")
        self.assertEqual(raw_index_daily.partitions_def, cn_a_index_trade_days)

    def test_stk_mins_assets_use_expected_partitions(self) -> None:
        raw_assets = (
            raw_stk_mins_1m,
            raw_stk_mins_5m,
            raw_stk_mins_15m,
            raw_stk_mins_30m,
            raw_stk_mins_60m,
        )
        silver_assets = (
            silver_stk_mins_1m,
            silver_stk_mins_5m,
            silver_stk_mins_15m,
            silver_stk_mins_30m,
            silver_stk_mins_60m,
        )
        gold_assets = (
            gold_stk_mins_qfq_1m,
            gold_stk_mins_qfq_5m,
            gold_stk_mins_qfq_15m,
            gold_stk_mins_qfq_30m,
            gold_stk_mins_qfq_60m,
            gold_stk_mins_qfq_90m,
            gold_stk_mins_qfq_120m,
        )

        for asset in raw_assets:
            with self.subTest(asset=asset.key.to_user_string()):
                self.assertEqual(asset.partitions_def, cn_a_stock_mins_trade_days)

        for asset in silver_assets:
            with self.subTest(asset=asset.key.to_user_string()):
                self.assertEqual(
                    asset.partitions_def,
                    cn_a_stock_mins_silver_trade_days,
                )
        for asset in gold_assets:
            with self.subTest(asset=asset.key.to_user_string()):
                self.assertEqual(
                    asset.partitions_def,
                    cn_a_stock_mins_silver_trade_days,
                )
        for asset_definition in GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS:
            for asset_key in asset_definition.keys:
                with self.subTest(asset=asset_key.to_user_string()):
                    spec = asset_definition.get_asset_spec(asset_key)
                    self.assertEqual(
                        spec.partitions_def,
                        cn_a_stock_mins_silver_trade_days,
                    )

        self.assertEqual(
            raw_tushare_stk_nineturn.partitions_def,
            cn_a_stk_nineturn_trade_days,
        )
        self.assertEqual(
            silver_stock_nineturn_daily.partitions_def,
            cn_a_stk_nineturn_trade_days,
        )

    def test_assets_register_definition_column_schema(
        self,
    ) -> None:
        catalog_entries = _catalog_entries_by_key()
        active_catalog_entries = {
            asset_key: entry
            for asset_key, entry in catalog_entries.items()
            if asset_key not in CONTRACT_ONLY_CATALOG_ASSET_KEYS
        }
        schemas_by_asset_key = {
            asset_key: entry.column_schema
            for asset_key, entry in active_catalog_entries.items()
            if entry.column_schema is not None
        }
        self.assertEqual(
            set(schemas_by_asset_key) | ASSETS_WITHOUT_COLUMN_SCHEMA,
            set(ACTIVE_ASSETS_BY_KEY),
        )

        for asset_key, expected_schema in schemas_by_asset_key.items():
            with self.subTest(asset=asset_key):
                spec = ACTIVE_ASSET_SPECS_BY_KEY[asset_key]
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

        for asset_key in ASSETS_WITHOUT_COLUMN_SCHEMA:
            with self.subTest(asset=asset_key):
                spec = ACTIVE_ASSET_SPECS_BY_KEY[asset_key]
                self.assertNotIn(DAGSTER_COLUMN_SCHEMA_METADATA_KEY, spec.metadata)

    def test_catalog_blocking_checks_match_active_check_specs(self) -> None:
        expected_check_names = {
            entry.asset_key: set(entry.blocking_check_names)
            for entry in list_lake_asset_catalog_entries()
            if entry.asset_key not in CONTRACT_ONLY_CATALOG_ASSET_KEYS
        }
        active_check_names = _blocking_check_names_by_asset_key()
        actual_check_names = {
            asset_key: active_check_names.get(asset_key, set())
            for asset_key in ACTIVE_ASSETS_BY_KEY
        }

        self.assertEqual(actual_check_names, expected_check_names)

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
            NAMECHANGE_RAW_COLUMNS,
            tuple(column.name for column in RAW_TUSHARE_NAMECHANGE_SCHEMA),
        )
        self.assertEqual(
            NAMECHANGE_RAW_COLUMN_TYPES,
            {column.name: column.type for column in RAW_TUSHARE_NAMECHANGE_SCHEMA},
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
            RAW_STK_NINETURN_COLUMNS,
            tuple(column.name for column in RAW_TUSHARE_STK_NINETURN_SCHEMA),
        )
        self.assertEqual(
            RAW_STK_NINETURN_COLUMN_TYPES,
            {
                column.name: column.type
                for column in RAW_TUSHARE_STK_NINETURN_SCHEMA
            },
        )
        self.assertEqual(
            SILVER_STOCK_NINETURN_DAILY_COLUMNS,
            tuple(column.name for column in SILVER_STOCK_NINETURN_DAILY_SCHEMA),
        )
        self.assertEqual(
            SILVER_STOCK_NINETURN_DAILY_COLUMN_TYPES,
            {
                column.name: column.type
                for column in SILVER_STOCK_NINETURN_DAILY_SCHEMA
            },
        )
        self.assertEqual(
            ADJ_FACTOR_RAW_REQUIRED_COLUMNS,
            tuple(column.name for column in RAW_TUSHARE_ADJ_FACTOR_SCHEMA),
        )
        self.assertEqual(
            ADJ_FACTOR_RAW_COLUMN_TYPES,
            {column.name: column.type for column in RAW_TUSHARE_ADJ_FACTOR_SCHEMA},
        )
        self.assertEqual(
            STK_MINS_RAW_REQUIRED_COLUMNS,
            tuple(column.name for column in RAW_STK_MINS_SCHEMA),
        )
        self.assertEqual(
            STK_MINS_RAW_COLUMN_TYPES,
            {column.name: column.type for column in RAW_STK_MINS_SCHEMA},
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
            tuple(column.name for column in RAW_INDEX_DAILY_SCHEMA),
        )
        self.assertEqual(
            INDEX_DAILY_RAW_COLUMN_TYPES,
            {
                column.name: column.type
                for column in RAW_INDEX_DAILY_SCHEMA
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
            STOCK_LIFECYCLE_SILVER_REQUIRED_COLUMNS,
            tuple(column.name for column in SILVER_STOCK_LIFECYCLE_SCHEMA),
        )
        self.assertEqual(
            NAMECHANGE_SILVER_REQUIRED_COLUMNS,
            tuple(column.name for column in SILVER_NAMECHANGE_SCHEMA),
        )
        self.assertEqual(
            NAMECHANGE_SILVER_COLUMN_TYPES,
            {column.name: column.type for column in SILVER_NAMECHANGE_SCHEMA},
        )
        self.assertEqual(
            SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS,
            tuple(column.name for column in SILVER_STOCK_IDENTITY_MAP_SCHEMA),
        )
        self.assertEqual(
            STOCK_DAILY_SILVER_REQUIRED_COLUMNS,
            tuple(column.name for column in SILVER_STOCK_DAILY_SCHEMA),
        )
        self.assertEqual(
            ADJ_FACTOR_SILVER_REQUIRED_COLUMNS,
            tuple(column.name for column in SILVER_ADJ_FACTOR_SCHEMA),
        )
        self.assertEqual(
            ADJ_FACTOR_COLUMNS,
            tuple(column.name for column in SILVER_ADJ_FACTOR_SCHEMA),
        )
        self.assertEqual(
            ADJ_FACTOR_SILVER_COLUMN_TYPES,
            {column.name: column.type for column in SILVER_ADJ_FACTOR_SCHEMA},
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
            GOLD_STK_MINS_QFQ_COLUMNS,
            tuple(column.name for column in GOLD_STK_MINS_QFQ_SCHEMA),
        )
        self.assertEqual(
            GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMNS,
            tuple(column.name for column in GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA),
        )
        self.assertEqual(
            GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_COLUMNS,
            tuple(column.name for column in GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA),
        )
        self.assertEqual(
            WEALTH_MARKET_TURNOVER_COLUMNS,
            tuple(column.name for column in GOLD_WEALTH_MARKET_TURNOVER_SCHEMA),
        )
        self.assertEqual(
            CLICKHOUSE_MARKET_BREADTH_COLUMNS,
            tuple(column.name for column in CH_SHARE_FACT_MARKET_BREADTH_DAILY_SCHEMA),
        )
