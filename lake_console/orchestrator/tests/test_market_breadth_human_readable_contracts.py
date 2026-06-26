import ast
import unittest
from pathlib import Path

from orchestrator.defs.assets.market_breadth import (
    _human_materialization_metadata as breadth_human_metadata,
    gold_market_breadth_daily,
)
from orchestrator.defs.assets.stock_return_distribution import (
    _human_materialization_metadata as distribution_human_metadata,
    gold_stock_return_distribution,
)


MARKET_BREADTH_ASSET_PATH = Path("src/orchestrator/defs/assets/market_breadth.py")
DISTRIBUTION_ASSET_PATH = Path(
    "src/orchestrator/defs/assets/stock_return_distribution.py"
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


class MarketBreadthHumanReadableContractTests(unittest.TestCase):
    def test_asset_descriptions_explain_metric_and_consumer(self) -> None:
        breadth_description = _asset_description(gold_market_breadth_daily)
        distribution_description = _asset_description(gold_stock_return_distribution)

        self.assertIn("市场宽度 gold", breadth_description)
        self.assertIn("silver_stock_daily", breadth_description)
        self.assertIn("红盘率", breadth_description)
        self.assertIn("收益率分布 gold", distribution_description)
        self.assertIn("十一段", distribution_description)
        self.assertIn("silver_stock_daily", distribution_description)
        self.assertNotIn("selection", breadth_description.lower())
        self.assertNotIn("selection", distribution_description.lower())

    def test_stdout_events_are_named_and_small(self) -> None:
        self.assertTrue(
            {
                "gold_market_breadth_started",
                "gold_market_breadth_completed",
            }.issubset(_stdout_events(MARKET_BREADTH_ASSET_PATH))
        )
        self.assertTrue(
            {
                "gold_stock_return_distribution_started",
                "gold_stock_return_distribution_completed",
            }.issubset(_stdout_events(DISTRIBUTION_ASSET_PATH))
        )

    def test_human_materialization_metadata_uses_metric_summary(self) -> None:
        breadth_metadata = breadth_human_metadata(
            partition_key="2026-06-15",
            silver_path=Path("/tmp/silver.parquet"),
            breadth_row={
                "up_count": 10,
                "down_count": 8,
                "flat_count": 2,
                "total_count": 20,
                "red_rate": 50.0,
            },
        )
        distribution_metadata = distribution_human_metadata(
            partition_key="2026-06-15",
            silver_path=Path("/tmp/silver.parquet"),
            distribution_row={"flat_count": 2, "total_count": 20},
        )

        self.assertIn("市场宽度 gold", breadth_metadata["summary"])
        self.assertEqual(breadth_metadata["metric_summary"]["total_count"], 20)
        self.assertEqual(breadth_metadata["metric_summary"]["red_rate"], 50.0)
        self.assertIn("收益率分布 gold", distribution_metadata["summary"])
        self.assertEqual(distribution_metadata["metric_summary"]["bucket_count"], 11)
        self.assertEqual(distribution_metadata["metric_summary"]["total_count"], 20)


if __name__ == "__main__":
    unittest.main()
