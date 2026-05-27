import unittest
from pathlib import Path

from orchestrator.defs.run_contracts.metadata import (
    CHECK_SCOPE_METADATA_KEY,
    CHECKED_ROW_COUNT_METADATA_KEY,
    DAGSTER_COLUMN_SCHEMA_METADATA_KEY,
    DAGSTER_ROW_COUNT_METADATA_KEY,
    DAGSTER_URI_METADATA_KEY,
    DATA_CONTRACT_METADATA_KEY,
    DATASET_ID_METADATA_KEY,
    DATASET_NAME_METADATA_KEY,
    FAILED_ROW_COUNT_METADATA_KEY,
    FILE_PATH_METADATA_KEY,
    PATH_TEMPLATE_METADATA_KEY,
    SOURCE_API_METADATA_KEY,
    SOURCE_CATEGORY_PATH_METADATA_KEY,
    SOURCE_DOC_METADATA_KEY,
    SOURCE_SYSTEM_METADATA_KEY,
    CheckScope,
    SourceSystem,
    build_asset_definition_metadata,
    build_check_metadata,
    build_materialization_metadata,
)


class MetadataContractTests(unittest.TestCase):
    def test_asset_definition_metadata_includes_dataset_and_source_contract(
        self,
    ) -> None:
        metadata = build_asset_definition_metadata(
            dataset_id="daily",
            source_system=SourceSystem.TUSHARE,
            source_api="daily",
            source_category_path="股票数据 / 行情数据",
            source_doc="docs/sources/tushare/股票数据/行情数据/0027_A股日线行情.md",
            data_contract="source_mirror",
            path_template="data_lake/raw/tushare/stock_daily/trade_date={partition_key}/part-000.parquet",
        )

        self.assertEqual(metadata[DATASET_ID_METADATA_KEY], "daily")
        self.assertEqual(metadata[DATASET_NAME_METADATA_KEY], "A股日线行情")
        self.assertEqual(metadata[SOURCE_SYSTEM_METADATA_KEY], "tushare")
        self.assertEqual(metadata[SOURCE_API_METADATA_KEY], "daily")
        self.assertEqual(
            metadata[SOURCE_CATEGORY_PATH_METADATA_KEY], "股票数据 / 行情数据"
        )
        self.assertIn("0027_A股日线行情.md", metadata[SOURCE_DOC_METADATA_KEY])
        self.assertEqual(metadata[DATA_CONTRACT_METADATA_KEY], "source_mirror")
        self.assertIn("stock_daily", metadata[PATH_TEMPLATE_METADATA_KEY])

    def test_materialization_metadata_uses_dagster_standard_keys(self) -> None:
        metadata = build_materialization_metadata(
            uri=Path("/tmp/example.parquet"),
            row_count=3,
            columns=("ts_code", "trade_date"),
            extra_metadata={"partition_key": "2026-05-26"},
        )

        self.assertEqual(metadata[DAGSTER_URI_METADATA_KEY], "/tmp/example.parquet")
        self.assertEqual(metadata[DAGSTER_ROW_COUNT_METADATA_KEY], 3)
        self.assertIn(DAGSTER_COLUMN_SCHEMA_METADATA_KEY, metadata)
        self.assertEqual(metadata["goldenshare/partition_key"], "2026-05-26")
        self.assertNotIn("path", metadata)
        self.assertNotIn("row_count", metadata)
        self.assertNotIn("columns", metadata)

    def test_materialization_metadata_rejects_legacy_top_level_keys(self) -> None:
        with self.assertRaises(ValueError):
            build_materialization_metadata(extra_metadata={"row_count": 3})

        with self.assertRaises(ValueError):
            build_materialization_metadata(
                extra_metadata={"path": "/tmp/example.parquet"}
            )

    def test_check_metadata_namespaces_legacy_details(self) -> None:
        metadata = build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            extra_metadata={
                "path": "/tmp/example.parquet",
                "row_count": 3,
                "columns": ["ts_code", "trade_date"],
                "missing_columns": [],
            },
            failed_row_count=0,
        )

        self.assertEqual(metadata[CHECK_SCOPE_METADATA_KEY], "schema")
        self.assertEqual(metadata[FILE_PATH_METADATA_KEY], "/tmp/example.parquet")
        self.assertEqual(metadata[CHECKED_ROW_COUNT_METADATA_KEY], 3)
        self.assertEqual(metadata[FAILED_ROW_COUNT_METADATA_KEY], 0)
        self.assertEqual(
            metadata["goldenshare/observed_columns"], ["ts_code", "trade_date"]
        )
        self.assertEqual(metadata["goldenshare/missing_columns"], [])
        self.assertNotIn("path", metadata)
        self.assertNotIn("row_count", metadata)
        self.assertNotIn("columns", metadata)

    def test_check_files_do_not_write_legacy_metadata_keys(self) -> None:
        checks_dir = Path("src/orchestrator/defs/checks")
        legacy_key_literals = (
            '"path":',
            '"raw_path":',
            '"silver_path":',
            '"gold_path":',
            '"paths":',
            '"missing_paths":',
            '"row_count":',
            '"columns":',
            '"schema":',
        )

        for path in sorted(checks_dir.glob("*.py")):
            with self.subTest(path=str(path)):
                text = path.read_text()
                for literal in legacy_key_literals:
                    self.assertNotIn(literal, text)


if __name__ == "__main__":
    unittest.main()
