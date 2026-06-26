import ast
import unittest
from pathlib import Path

from orchestrator.defs.assets.stk_mins import (
    SilverStkMinsWriteResult,
    StkMinsRawWriteResult,
    _raw_stk_mins_human_metadata,
    _silver_stk_mins_human_metadata,
    raw_stk_mins_1m,
    silver_stk_mins_1m,
)
from orchestrator.defs.checks.stk_mins_checks import _readable_check_metadata
from orchestrator.defs.jobs.stock_mins_raw_update import (
    stock_mins_raw_update_from_prod_job,
    stock_mins_raw_update_job,
)
from orchestrator.defs.jobs.stock_mins_silver_update import (
    stock_mins_silver_update_job,
)
from orchestrator.defs.sensors.stock_mins_raw_sensor import stock_mins_raw_sensor
from orchestrator.defs.sensors.stock_mins_silver_sensor import stock_mins_silver_sensor


ASSET_PATH = Path("src/orchestrator/defs/assets/stk_mins.py")


def _asset_description(asset_definition) -> str:  # noqa: ANN001
    descriptions = tuple(asset_definition.descriptions_by_key.values())
    return descriptions[0] if descriptions else ""


def _stdout_calls() -> list[ast.Call]:
    tree = ast.parse(ASSET_PATH.read_text(), filename=str(ASSET_PATH))
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "stdout":
            calls.append(node)
    return calls


class StkMinsHumanReadableContractTests(unittest.TestCase):
    def test_asset_job_and_sensor_descriptions_explain_business_purpose(self) -> None:
        descriptions = (
            _asset_description(raw_stk_mins_1m),
            _asset_description(silver_stk_mins_1m),
            stock_mins_raw_update_job.description or "",
            stock_mins_raw_update_from_prod_job.description or "",
            stock_mins_silver_update_job.description or "",
            stock_mins_raw_sensor.description or "",
            stock_mins_silver_sensor.description or "",
        )

        for description in descriptions:
            with self.subTest(description=description):
                self.assertRegex(description, r"[\u4e00-\u9fff]")
                self.assertNotIn("selection", description.lower())

        self.assertIn("raw", descriptions[0])
        self.assertIn("silver", descriptions[1])
        self.assertIn("prod DB", descriptions[3])

    def test_stk_mins_stdout_events_are_small_and_named(self) -> None:
        calls = _stdout_calls()
        events = {
            call.args[0].value
            for call in calls
            if call.args
            and isinstance(call.args[0], ast.Constant)
            and isinstance(call.args[0].value, str)
        }

        self.assertEqual(
            {
                "raw_stk_mins_started",
                "raw_stk_mins_completed",
                "raw_stk_mins_repair_started",
                "raw_stk_mins_repair_completed",
                "silver_stk_mins_started",
                "silver_stk_mins_completed",
            }
            - events,
            set(),
        )

        forbidden_stdout_fields = {
            "sql",
            "query",
            "dataframe",
            "df",
            "stock_codes",
            "ts_codes",
            "sample_rows",
            "raw_file_path",
            "silver_file_path",
            "input_file_paths",
        }
        issues = []
        for call in calls:
            keyword_names = {keyword.arg for keyword in call.keywords if keyword.arg}
            forbidden = keyword_names & forbidden_stdout_fields
            if forbidden:
                issues.append(f"stdout call writes forbidden fields {sorted(forbidden)}")

        self.assertEqual(issues, [])

    def test_raw_human_materialization_metadata_uses_operator_fields(self) -> None:
        result = StkMinsRawWriteResult(
            raw_file_path=Path("/tmp/raw.parquet"),
            row_count=100,
            observed_columns=("ts_code", "freq"),
            stock_code_count=3,
            returned_stock_code_count=2,
            empty_stock_code_count=1,
            page_count=3,
            source_method="prod_db_raw_tushare",
            query_count=1,
            write_mode="replace",
        )

        metadata = _raw_stk_mins_human_metadata(
            write_result=result,
            partition_key="2026-05-29",
            freq=1,
        )

        self.assertIn("股票 1min 分钟 raw 源镜像", metadata["goldenshare/summary"])
        self.assertIn("silver_stk_mins", metadata["goldenshare/next_action"])
        self.assertEqual(metadata["goldenshare/result_status"], "written")
        self.assertEqual(
            metadata["goldenshare/input_summary"]["source_method"],
            "prod_db_raw_tushare",
        )
        self.assertEqual(metadata["goldenshare/filter_summary"]["output_row_count"], 100)

    def test_silver_human_materialization_metadata_uses_operator_fields(self) -> None:
        result = SilverStkMinsWriteResult(
            raw_file_path=Path("/tmp/raw.parquet"),
            one_minute_raw_file_path=Path("/tmp/raw_1m.parquet"),
            identity_map_file_path=Path("/tmp/identity.parquet"),
            stock_daily_file_path=Path("/tmp/daily.parquet"),
            suspend_file_path=Path("/tmp/suspend.parquet"),
            silver_file_path=Path("/tmp/silver.parquet"),
            source_row_count=120,
            mapped_row_count=118,
            duplicate_removed_count=2,
            full_day_suspend_deleted_row_count=3,
            price_correction_row_count=4,
            recomputed_row_count=5,
            vol_amount_normalized_row_count=6,
            row_count=109,
            observed_columns=("ts_code", "freq"),
        )

        metadata = _silver_stk_mins_human_metadata(
            write_result=result,
            partition_key="2026-05-29",
            freq=5,
        )

        self.assertIn("股票 5min 分钟 silver 标准事实", metadata["goldenshare/summary"])
        self.assertIn("qfq", metadata["goldenshare/next_action"])
        self.assertEqual(metadata["goldenshare/result_status"], "written")
        self.assertEqual(
            metadata["goldenshare/input_summary"]["source_asset"],
            "raw_stk_mins_5m",
        )
        self.assertEqual(metadata["goldenshare/filter_summary"]["output_row_count"], 109)

    def test_check_readable_metadata_keeps_rule_summary_and_next_action(self) -> None:
        metadata = _readable_check_metadata(
            dataset_label="股票 1 分钟 raw 契约",
            rule_names=("file_exists", "schema"),
            failed_rule_names=("schema",),
            success_next_action="无需处理。",
            failure_next_action="先修复 schema。",
        )

        self.assertIn("失败", metadata["summary"])
        self.assertEqual(metadata["next_action"], "先修复 schema。")
        self.assertEqual(
            metadata["rule_summary"],
            [
                {"rule_name": "file_exists", "passed": True},
                {"rule_name": "schema", "passed": False},
            ],
        )


if __name__ == "__main__":
    unittest.main()
