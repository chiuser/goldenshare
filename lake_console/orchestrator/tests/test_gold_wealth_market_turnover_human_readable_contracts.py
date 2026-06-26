import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

from orchestrator.defs.assets.wealth_market_turnover import (
    _human_materialization_metadata as gold_human_metadata,
    gold_wealth_market_turnover,
)
from orchestrator.defs.assets.wealth_market_turnover_prod_core import (
    _human_materialization_metadata as prod_core_human_metadata,
    prod_core_wealth_market_turnover,
)


GOLD_ASSET_PATH = Path("src/orchestrator/defs/assets/wealth_market_turnover.py")
PROD_CORE_ASSET_PATH = Path(
    "src/orchestrator/defs/assets/wealth_market_turnover_prod_core.py"
)


def _asset_description(asset_definition) -> str:  # noqa: ANN001
    descriptions = tuple(asset_definition.descriptions_by_key.values())
    return descriptions[0] if descriptions else ""


def _stdout_events(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    events: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "stdout"):
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            events.add(node.args[0].value)
    return events


class GoldWealthMarketTurnoverHumanReadableContractTests(unittest.TestCase):
    def test_asset_descriptions_explain_gold_and_prod_sync(self) -> None:
        gold_description = _asset_description(gold_wealth_market_turnover)
        prod_description = _asset_description(prod_core_wealth_market_turnover)

        self.assertIn("财富端市场成交额 gold", gold_description)
        self.assertIn("silver_stk_mins", gold_description)
        self.assertIn("points_json", gold_description)
        self.assertIn("prod PostgreSQL core serving", prod_description)
        self.assertIn("gold", prod_description)
        self.assertNotIn("selection", gold_description.lower())
        self.assertNotIn("selection", prod_description.lower())

    def test_stdout_events_are_named_and_small(self) -> None:
        self.assertTrue(
            {
                "gold_wealth_market_turnover_started",
                "gold_wealth_market_turnover_completed",
            }.issubset(_stdout_events(GOLD_ASSET_PATH))
        )
        self.assertTrue(
            {
                "prod_core_wealth_market_turnover_started",
                "prod_core_wealth_market_turnover_completed",
            }.issubset(_stdout_events(PROD_CORE_ASSET_PATH))
        )

    def test_human_metadata_summarizes_freqs_and_prod_target(self) -> None:
        gold_metadata = gold_human_metadata(
            partition_key="2026-06-23",
            input_path_count=5,
            audit=SimpleNamespace(
                row_count=5,
                source_row_count=100,
                total_amount="123.45",
                total_vol=678,
                security_count_by_freq={"1": 10},
            ),
        )
        prod_metadata = prod_core_human_metadata(
            partition_key="2026-06-23",
            source_path=Path("/tmp/gold.parquet"),
            row_count=5,
            read_back_row_count=5,
            points_json_hash="abc123",
        )

        self.assertIn("财富端市场成交额 gold", gold_metadata["summary"])
        self.assertEqual(gold_metadata["input_summary"]["freqs"], [1, 5, 15, 30, 60])
        self.assertEqual(gold_metadata["metric_summary"]["output_row_count"], 5)
        self.assertIn("prod PostgreSQL", prod_metadata["summary"])
        self.assertEqual(
            prod_metadata["serving_summary"]["target_table"],
            "core_serving.wealth_market_turnover_snapshot",
        )
        self.assertEqual(prod_metadata["serving_summary"]["read_back_row_count"], 5)


if __name__ == "__main__":
    unittest.main()
