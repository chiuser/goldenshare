import ast
import unittest
from pathlib import Path

from orchestrator.defs.assets.market_major_indices import (
    _human_materialization_metadata,
    gold_market_major_indices_daily,
)


ASSET_PATH = Path("src/orchestrator/defs/assets/market_major_indices.py")


def _asset_description(asset_definition) -> str:  # noqa: ANN001
    descriptions = tuple(asset_definition.descriptions_by_key.values())
    return descriptions[0] if descriptions else ""


def _stdout_calls() -> list[ast.Call]:
    tree = ast.parse(ASSET_PATH.read_text(), filename=str(ASSET_PATH))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "stdout"
    ]


class MarketMajorIndicesHumanReadableContractTests(unittest.TestCase):
    def test_asset_description_explains_business_purpose(self) -> None:
        description = _asset_description(gold_market_major_indices_daily)

        self.assertIn("主要指数日线 gold", description)
        self.assertIn("seed", description)
        self.assertIn("silver_index_daily", description)
        self.assertIn("首页", description)
        self.assertNotIn("selection", description.lower())

    def test_stdout_events_are_small_and_named(self) -> None:
        expected_events = {
            "gold_market_major_indices_started",
            "gold_market_major_indices_completed",
        }
        observed_events = set()
        forbidden_stdout_fields = {
            "sql",
            "query",
            "dataframe",
            "df",
            "active_seed_codes",
            "seed_codes",
            "sample_rows",
            "partition_metadata",
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
            partition_keys=("2026-06-15",),
            partition_metadata={
                "2026-06-15": {
                    "active_seed_row_count": 6,
                    "output_row_count": 6,
                }
            },
            seed_count=7,
            total_row_count=6,
        )

        self.assertIn("主要指数日线 gold", metadata["summary"])
        self.assertIn("blocking checks", metadata["next_action"])
        self.assertEqual(metadata["result_status"], "written")
        self.assertEqual(metadata["input_summary"]["source_asset"], "silver_index_daily")
        self.assertEqual(metadata["metric_summary"]["output_row_count"], 6)
        self.assertEqual(
            metadata["metric_summary"]["active_seed_row_counts"],
            {"2026-06-15": 6},
        )
        self.assertIn("run stdout", metadata["diagnostic_ref"])


if __name__ == "__main__":
    unittest.main()
