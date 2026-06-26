import ast
import unittest
from pathlib import Path

from orchestrator.defs.assets.index_daily import (
    _human_materialization_metadata,
    raw_index_daily,
    silver_index_daily,
)


ASSET_PATH = Path("src/orchestrator/defs/assets/index_daily.py")


def _asset_description(asset_definition) -> str:
    descriptions = tuple(asset_definition.descriptions_by_key.values())
    return descriptions[0] if descriptions else ""


def _stdout_calls() -> list[ast.Call]:
    source = ASSET_PATH.read_text()
    tree = ast.parse(source, filename=str(ASSET_PATH))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "stdout"
    ]


class IndexDailyHumanReadableContractTests(unittest.TestCase):
    def test_asset_descriptions_explain_source_and_purpose(self) -> None:
        raw_description = _asset_description(raw_index_daily)
        silver_description = _asset_description(silver_index_daily)

        self.assertIn("raw 源镜像", raw_description)
        self.assertIn("prod core serving", raw_description)
        self.assertIn("DG 管理", raw_description)
        self.assertIn("silver 标准事实", silver_description)
        self.assertIn("raw_index_daily", silver_description)
        self.assertNotIn("selection", raw_description)
        self.assertNotIn("selection", silver_description)

    def test_index_daily_stdout_events_are_small_and_named(self) -> None:
        expected_events = {
            "raw_index_daily_started",
            "raw_index_daily_completed",
            "silver_partition_written",
            "silver_partitions_completed",
        }
        observed_events = set()
        forbidden_stdout_fields = {
            "sql",
            "query",
            "dataframe",
            "df",
            "ts_codes",
            "index_codes",
            "missing_codes",
            "sample_rows",
            "duplicate_sample_rows",
            "missing_code_samples",
            "extra_code_samples",
        }
        forbidden_hits = []

        for call in _stdout_calls():
            if call.args and isinstance(call.args[0], ast.Constant):
                observed_events.add(call.args[0].value)
            for keyword in call.keywords:
                if keyword.arg in forbidden_stdout_fields:
                    forbidden_hits.append(keyword.arg)

        self.assertTrue(expected_events.issubset(observed_events))
        self.assertEqual(forbidden_hits, [])

    def test_human_materialization_metadata_uses_operator_fields(self) -> None:
        metadata = _human_materialization_metadata(
            summary="已写入测试指数分区。",
            next_action="等待 checks。",
            result_status="written",
            input_summary={"source": "prod_core_db"},
            diagnostic_ref="看 run stdout。",
            code_set_summary={"expected_code_count": 1},
            filter_summary={"output_row_count": 1},
        )

        self.assertEqual(metadata["summary"], "已写入测试指数分区。")
        self.assertEqual(metadata["next_action"], "等待 checks。")
        self.assertEqual(metadata["result_status"], "written")
        self.assertEqual(metadata["input_summary"], {"source": "prod_core_db"})
        self.assertEqual(metadata["code_set_summary"], {"expected_code_count": 1})
        self.assertEqual(metadata["filter_summary"], {"output_row_count": 1})
        self.assertEqual(metadata["diagnostic_ref"], "看 run stdout。")


if __name__ == "__main__":
    unittest.main()
