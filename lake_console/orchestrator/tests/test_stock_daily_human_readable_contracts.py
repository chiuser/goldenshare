import ast
import unittest
from pathlib import Path

from orchestrator.defs.assets.stock_daily import (
    _human_materialization_metadata,
    raw_tushare_stock_daily,
    silver_stock_daily,
)
from orchestrator.defs.jobs.stock_daily_update import (
    raw_stock_daily_update_job,
    silver_stock_daily_update_job,
)
from orchestrator.defs.sensors.stock_daily_sensor import (
    raw_stock_daily_update_job_sensor,
    silver_stock_daily_update_job_sensor,
)


ASSET_PATH = Path("src/orchestrator/defs/assets/stock_daily.py")


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


class StockDailyHumanReadableContractTests(unittest.TestCase):
    def test_asset_job_and_sensor_descriptions_explain_business_purpose(self) -> None:
        descriptions = (
            _asset_description(raw_tushare_stock_daily),
            _asset_description(silver_stock_daily),
            raw_stock_daily_update_job.description or "",
            silver_stock_daily_update_job.description or "",
            raw_stock_daily_update_job_sensor.description or "",
            silver_stock_daily_update_job_sensor.description or "",
        )

        for description in descriptions:
            with self.subTest(description=description):
                self.assertRegex(description, r"[\u4e00-\u9fff]")
                self.assertNotIn("selection", description.lower())

        self.assertIn("源镜像", descriptions[0])
        self.assertIn("标准事实", descriptions[1])
        self.assertIn("Tushare", descriptions[2])
        self.assertIn("silver", descriptions[3])

    def test_stock_daily_stdout_events_are_small_and_named(self) -> None:
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
                "raw_stock_daily_started",
                "raw_stock_daily_completed",
                "raw_stock_daily_repair_started",
                "raw_stock_daily_repair_completed",
                "silver_stock_daily_started",
                "silver_stock_daily_validation_failed",
                "silver_stock_daily_completed",
            }
            - events,
            set(),
        )

        forbidden_stdout_fields = {
            "sql",
            "query",
            "dataframe",
            "df",
            "ts_codes",
            "missing_codes",
            "sample_rows",
            "conflict_sample_rows",
            "duplicate_sample_rows",
        }
        issues = []
        for call in calls:
            keyword_names = {keyword.arg for keyword in call.keywords if keyword.arg}
            forbidden = keyword_names & forbidden_stdout_fields
            if forbidden:
                issues.append(f"stdout call writes forbidden fields {sorted(forbidden)}")

        self.assertEqual(issues, [])

    def test_human_materialization_metadata_uses_namespaced_operator_fields(
        self,
    ) -> None:
        metadata = _human_materialization_metadata(
            summary="已写入股票日线测试产物。",
            next_action="等待 checks。",
            result_status="written",
            input_summary={"source": "test"},
            filter_summary={"final_silver_row_count": 1},
            diagnostic_ref="看 run stdout。",
        )

        self.assertEqual(metadata["goldenshare/summary"], "已写入股票日线测试产物。")
        self.assertEqual(metadata["goldenshare/next_action"], "等待 checks。")
        self.assertEqual(metadata["goldenshare/result_status"], "written")
        self.assertEqual(metadata["goldenshare/input_summary"], {"source": "test"})
        self.assertEqual(
            metadata["goldenshare/filter_summary"],
            {"final_silver_row_count": 1},
        )
        self.assertEqual(metadata["goldenshare/diagnostic_ref"], "看 run stdout。")


if __name__ == "__main__":
    unittest.main()
