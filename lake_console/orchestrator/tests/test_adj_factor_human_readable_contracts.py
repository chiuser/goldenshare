import ast
import unittest
from pathlib import Path

from orchestrator.defs.assets.adj_factor import (
    _human_materialization_metadata,
    raw_tushare_adj_factor,
    silver_adj_factor,
)


ASSET_PATH = Path("src/orchestrator/defs/assets/adj_factor.py")


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


class AdjFactorHumanReadableContractTests(unittest.TestCase):
    def test_asset_descriptions_explain_business_purpose(self) -> None:
        raw_description = _asset_description(raw_tushare_adj_factor)
        silver_description = _asset_description(silver_adj_factor)

        self.assertIn("源镜像", raw_description)
        self.assertIn("qfq", raw_description)
        self.assertIn("标准事实", silver_description)
        self.assertIn("生命周期", silver_description)
        self.assertNotIn("selection", raw_description)
        self.assertNotIn("selection", silver_description)

    def test_adj_factor_stdout_events_are_small_and_named(self) -> None:
        expected_events = {
            "raw_adj_factor_started",
            "raw_adj_factor_completed",
            "silver_adj_factor_started",
            "silver_adj_factor_completed",
        }
        observed_events = set()
        forbidden_stdout_fields = {
            "sql",
            "query",
            "dataframe",
            "df",
            "ts_codes",
            "missing_codes",
            "sample_rows",
            "duplicate_sample_rows",
            "invalid_sample_rows",
            "missing_code_samples",
            "unexpected_code_samples",
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
            summary="已写入测试分区。",
            next_action="等待 checks。",
            result_status="written",
            input_summary={"source": "test"},
            filter_summary={"output_row_count": 1},
            diagnostic_ref="看 run stdout。",
        )

        self.assertEqual(metadata["goldenshare/summary"], "已写入测试分区。")
        self.assertEqual(metadata["goldenshare/next_action"], "等待 checks。")
        self.assertEqual(metadata["goldenshare/result_status"], "written")
        self.assertEqual(metadata["goldenshare/input_summary"], {"source": "test"})
        self.assertEqual(
            metadata["goldenshare/filter_summary"],
            {"output_row_count": 1},
        )
        self.assertEqual(metadata["goldenshare/diagnostic_ref"], "看 run stdout。")


if __name__ == "__main__":
    unittest.main()
