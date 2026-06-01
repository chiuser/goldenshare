import unittest
from pathlib import Path

from orchestrator.defs.catalog import DATASET_CHINESE_NAMES
from orchestrator.defs.paths import gold_stk_mins_qfq_path
from orchestrator.defs.run_contracts import asset_column_schemas
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_SCHEMA,
)


class StkMinsQfqM7BContractTests(unittest.TestCase):
    def test_gold_qfq_path_is_stock_year_partitioned(self) -> None:
        self.assertEqual(
            gold_stk_mins_qfq_path(
                Path("data_lake"),
                5,
                "600000.SH",
                2026,
            ).as_posix(),
            "data_lake/gold/quote/stk_mins_qfq/freq=5/ts_code=600000.SH/year=2026/part-000.parquet",
        )

    def test_gold_qfq_path_rejects_invalid_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported stk_mins freq"):
            gold_stk_mins_qfq_path(Path("data_lake"), 2, "600000.SH", 2026)
        with self.assertRaisesRegex(ValueError, "ts_code must be non-empty"):
            gold_stk_mins_qfq_path(Path("data_lake"), 5, "", 2026)
        with self.assertRaisesRegex(ValueError, "must not contain '/'"):
            gold_stk_mins_qfq_path(Path("data_lake"), 5, "600000/SH", 2026)
        with self.assertRaisesRegex(ValueError, "four-digit year"):
            gold_stk_mins_qfq_path(Path("data_lake"), 5, "600000.SH", "26")
        with self.assertRaisesRegex(ValueError, "four-digit year"):
            gold_stk_mins_qfq_path(Path("data_lake"), 5, "600000.SH", "20260")
        with self.assertRaisesRegex(ValueError, "four-digit year"):
            gold_stk_mins_qfq_path(Path("data_lake"), 5, "600000.SH", "20A6")

    def test_gold_qfq_schema_is_stable(self) -> None:
        self.assertEqual(
            [(column.name, column.type) for column in GOLD_STK_MINS_QFQ_SCHEMA],
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
        self.assertNotIn("vwap", tuple(column.name for column in GOLD_STK_MINS_QFQ_SCHEMA))
        self.assertNotIn(
            "source_ts_code",
            tuple(column.name for column in GOLD_STK_MINS_QFQ_SCHEMA),
        )

    def test_gold_qfq_catalog_name_is_registered_without_summary_entities(self) -> None:
        self.assertEqual(DATASET_CHINESE_NAMES["stk_mins_qfq"], "股票分钟线前复权")
        self.assertNotIn("gold_stk_mins_qfq_daily_summary", DATASET_CHINESE_NAMES)
        self.assertNotIn("gold_stk_mins_qfq_factor_repair_summary", DATASET_CHINESE_NAMES)

        self.assertFalse(
            hasattr(asset_column_schemas, "GOLD_STK_MINS_QFQ_DAILY_SUMMARY_SCHEMA")
        )
        self.assertFalse(
            hasattr(
                asset_column_schemas,
                "GOLD_STK_MINS_QFQ_FACTOR_REPAIR_SUMMARY_SCHEMA",
            )
        )

    def test_m7b_touched_files_do_not_define_active_dagster_objects(self) -> None:
        orchestrator_root = Path(__file__).resolve().parents[1]
        touched_files = (
            orchestrator_root / "src/orchestrator/defs/paths.py",
            orchestrator_root / "src/orchestrator/defs/run_contracts/asset_column_schemas.py",
            orchestrator_root / "src/orchestrator/defs/catalog/name_mapping.py",
        )
        forbidden_tokens = ("@dg.asset", "@dg.asset_check", "define_asset_job", "@dg.sensor")
        for path in touched_files:
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                self.assertNotIn(token, text, f"{token} unexpectedly appears in {path}")


if __name__ == "__main__":
    unittest.main()
