import unittest

from orchestrator.defs.catalog import DATASET_CHINESE_NAMES
from orchestrator.defs.duckdb_sql import (
    SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS,
    STK_MINS_RAW_REQUIRED_COLUMNS,
    STK_MINS_SILVER_REQUIRED_COLUMNS,
)
from orchestrator.defs.partitions import (
    cn_a_stock_mins_silver_trade_days,
    cn_a_stock_mins_trade_days,
)
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    raw_stk_mins_path,
    silver_stk_mins_path,
    silver_stock_identity_map_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_STK_MINS_SCHEMA,
    SILVER_STK_MINS_SCHEMA,
    SILVER_STOCK_IDENTITY_MAP_SCHEMA,
)
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_FREQS,
    STK_MINS_QFQ_DERIVED_FREQS,
    STK_MINS_QFQ_FREQS,
    STK_MINS_QFQ_NATIVE_FREQS,
    STK_MINS_SOURCE_FREQS,
    derive_silver_stk_mins_exchange_from_ts_code,
    normalize_stk_mins_freq,
    normalize_stk_mins_qfq_freq,
    qfq_source_freq_for_derived_freq,
)


class StkMinsContractTests(unittest.TestCase):
    def test_stock_mins_partition_name_is_stable(self) -> None:
        self.assertEqual(
            cn_a_stock_mins_trade_days.name,
            "cn_a_stock_mins_trade_days",
        )
        self.assertEqual(
            cn_a_stock_mins_silver_trade_days.name,
            "cn_a_stock_mins_silver_trade_days",
        )

    def test_stk_mins_frequency_contract_is_stable(self) -> None:
        self.assertEqual(STK_MINS_FREQS, (1, 5, 15, 30, 60))
        self.assertEqual(STK_MINS_SOURCE_FREQS, (1, 5, 15, 30, 60))
        self.assertEqual(normalize_stk_mins_freq(30), 30)
        self.assertEqual(normalize_stk_mins_freq("30"), 30)
        with self.assertRaisesRegex(ValueError, "Unsupported stk_mins freq"):
            normalize_stk_mins_freq(2)
        with self.assertRaisesRegex(ValueError, "Unsupported stk_mins freq"):
            normalize_stk_mins_freq("30min")

    def test_qfq_frequency_contract_allows_derived_freqs_only_for_qfq(self) -> None:
        self.assertEqual(STK_MINS_QFQ_NATIVE_FREQS, (1, 5, 15, 30, 60))
        self.assertEqual(STK_MINS_QFQ_DERIVED_FREQS, (90, 120))
        self.assertEqual(STK_MINS_QFQ_FREQS, (1, 5, 15, 30, 60, 90, 120))
        self.assertEqual(normalize_stk_mins_qfq_freq("90"), 90)
        self.assertEqual(normalize_stk_mins_qfq_freq(120), 120)
        self.assertEqual(qfq_source_freq_for_derived_freq(90), 30)
        self.assertEqual(qfq_source_freq_for_derived_freq("120"), 60)
        with self.assertRaisesRegex(ValueError, "Unsupported stk_mins freq"):
            normalize_stk_mins_freq(90)
        with self.assertRaisesRegex(ValueError, "Unsupported derived stk_mins qfq freq"):
            qfq_source_freq_for_derived_freq(30)

    def test_stk_mins_catalog_names_are_registered(self) -> None:
        self.assertEqual(DATASET_CHINESE_NAMES["stk_mins"], "股票分钟线")
        self.assertEqual(
            DATASET_CHINESE_NAMES["stock_identity_map"],
            "股票身份映射",
        )

    def test_stk_mins_column_schemas_are_stable(self) -> None:
        self.assertEqual(
            [(column.name, column.type) for column in RAW_STK_MINS_SCHEMA],
            [
                ("ts_code", "VARCHAR"),
                ("freq", "INTEGER"),
                ("trade_time", "TIMESTAMP"),
                ("open", "DOUBLE"),
                ("close", "DOUBLE"),
                ("high", "DOUBLE"),
                ("low", "DOUBLE"),
                ("vol", "BIGINT"),
                ("amount", "DOUBLE"),
                ("exchange", "VARCHAR"),
                ("vwap", "DOUBLE"),
            ],
        )
        self.assertEqual(
            STK_MINS_RAW_REQUIRED_COLUMNS,
            tuple(column.name for column in RAW_STK_MINS_SCHEMA),
        )

    def test_stock_identity_map_column_schema_is_stable(self) -> None:
        self.assertEqual(
            [(column.name, column.type) for column in SILVER_STOCK_IDENTITY_MAP_SCHEMA],
            [
                ("latest_ts_code", "VARCHAR"),
                ("source_ts_code", "VARCHAR"),
                ("valid_from", "DATE"),
                ("valid_to", "DATE"),
                ("effective_list_date", "DATE"),
                ("effective_delist_date", "DATE"),
                ("identity_source", "VARCHAR"),
                ("confidence", "VARCHAR"),
                ("reason", "VARCHAR"),
                ("created_at", "TIMESTAMP WITH TIME ZONE"),
            ],
        )
        self.assertEqual(
            SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS,
            tuple(column.name for column in SILVER_STOCK_IDENTITY_MAP_SCHEMA),
        )

    def test_silver_stk_mins_column_schema_is_stable(self) -> None:
        self.assertEqual(
            [(column.name, column.type) for column in SILVER_STK_MINS_SCHEMA],
            [
                ("ts_code", "VARCHAR"),
                ("freq", "INTEGER"),
                ("trade_date", "DATE"),
                ("trade_time", "TIMESTAMP"),
                ("open", "DOUBLE"),
                ("high", "DOUBLE"),
                ("low", "DOUBLE"),
                ("close", "DOUBLE"),
                ("vol", "DOUBLE"),
                ("amount", "DOUBLE"),
                ("exchange", "VARCHAR"),
            ],
        )
        self.assertNotIn("source_ts_code", STK_MINS_SILVER_REQUIRED_COLUMNS)
        self.assertNotIn("vwap", STK_MINS_SILVER_REQUIRED_COLUMNS)
        self.assertEqual(
            STK_MINS_SILVER_REQUIRED_COLUMNS,
            tuple(column.name for column in SILVER_STK_MINS_SCHEMA),
        )

    def test_stk_mins_paths_are_stable(self) -> None:
        self.assertEqual(
            raw_stk_mins_path(
                PATH_TEMPLATE_LAKE_ROOT,
                30,
                "2026-05-07",
            ).as_posix(),
            "data_lake/raw/tushare/stk_mins/freq=30/trade_date=2026-05-07/part-000.parquet",
        )
        self.assertEqual(
            silver_stk_mins_path(
                PATH_TEMPLATE_LAKE_ROOT,
                30,
                "2026-05-07",
            ).as_posix(),
            "data_lake/silver/quote/stk_mins/freq=30/trade_date=2026-05-07/part-000.parquet",
        )
        self.assertEqual(
            silver_stock_identity_map_path(PATH_TEMPLATE_LAKE_ROOT).as_posix(),
            "data_lake/silver/basic/stock_identity_map/part-000.parquet",
        )
        with self.assertRaisesRegex(ValueError, "Unsupported stk_mins freq"):
            raw_stk_mins_path(PATH_TEMPLATE_LAKE_ROOT, 2, "2026-05-07")
        with self.assertRaisesRegex(ValueError, "Unsupported stk_mins freq"):
            silver_stk_mins_path(PATH_TEMPLATE_LAKE_ROOT, 2, "2026-05-07")

    def test_silver_stk_mins_exchange_derivation_is_stable(self) -> None:
        self.assertEqual(
            derive_silver_stk_mins_exchange_from_ts_code("600000.SH"),
            "SSE",
        )
        self.assertEqual(
            derive_silver_stk_mins_exchange_from_ts_code("000001.SZ"),
            "SZSE",
        )
        self.assertEqual(
            derive_silver_stk_mins_exchange_from_ts_code("430047.BJ"),
            "BSE",
        )
        with self.assertRaisesRegex(ValueError, "Unsupported silver stk_mins"):
            derive_silver_stk_mins_exchange_from_ts_code("")
        with self.assertRaisesRegex(ValueError, "Unsupported silver stk_mins"):
            derive_silver_stk_mins_exchange_from_ts_code("000001.HK")



if __name__ == "__main__":
    unittest.main()
