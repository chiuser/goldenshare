import ast
import unittest
from pathlib import Path

import dagster as dg

from orchestrator.defs.assets.clickhouse_serving import (
    _serving_materialization_metadata,
    ch_share_fact_market_breadth_daily,
    prod_ch_share_fact_market_breadth_daily,
)
from orchestrator.defs.checks import clickhouse_serving_checks
from orchestrator.defs.checks import prod_clickhouse_serving_checks
from orchestrator.defs.run_contracts.metadata import CheckScope


ASSET_PATH = Path("src/orchestrator/defs/assets/clickhouse_serving.py")


def _asset_description(asset_definition) -> str:  # noqa: ANN001
    descriptions = tuple(asset_definition.descriptions_by_key.values())
    return descriptions[0] if descriptions else ""


def _metadata_value(value):  # noqa: ANN001
    return getattr(value, "value", value)


def _stdout_events() -> set[str]:
    tree = ast.parse(ASSET_PATH.read_text(), filename=str(ASSET_PATH))
    events: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "stdout"):
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            events.add(node.args[0].value)
    return events


class ClickHouseMarketBreadthHumanReadableContractTests(unittest.TestCase):
    def test_asset_descriptions_explain_serving_target(self) -> None:
        local_description = _asset_description(ch_share_fact_market_breadth_daily)
        prod_description = _asset_description(prod_ch_share_fact_market_breadth_daily)

        self.assertIn("本机 ClickHouse 市场宽度 serving", local_description)
        self.assertIn("市场宽度 gold", local_description)
        self.assertIn("Prod ClickHouse 市场宽度 serving", prod_description)
        self.assertIn("本机 ClickHouse serving", prod_description)
        self.assertNotIn("selection", local_description.lower())
        self.assertNotIn("selection", prod_description.lower())

    def test_stdout_events_are_named_and_small(self) -> None:
        events = _stdout_events()
        self.assertTrue(
            {
                "ch_share_fact_market_breadth_started",
                "ch_share_fact_market_breadth_completed",
                "prod_ch_share_fact_market_breadth_started",
                "prod_ch_share_fact_market_breadth_completed",
            }.issubset(events)
        )

    def test_serving_materialization_metadata_names_target_and_inputs(self) -> None:
        metadata = _serving_materialization_metadata(
            partition_key="2026-06-24",
            target_system="prod_clickhouse",
            source_summary={"source_asset": "ch_share_fact_market_breadth_daily"},
        )

        self.assertIn("prod_clickhouse", metadata["summary"])
        self.assertEqual(
            metadata["input_summary"]["source_asset"],
            "ch_share_fact_market_breadth_daily",
        )
        self.assertEqual(metadata["serving_summary"]["target_system"], "prod_clickhouse")
        self.assertEqual(metadata["serving_summary"]["row_count"], 1)

    def test_check_metadata_is_human_readable(self) -> None:
        local_result = clickhouse_serving_checks._combined_check_result(
            check_scope=CheckScope.RECONCILIATION,
            rule_results=(
                ("total_count_matches_gold", dg.AssetCheckResult(passed=True)),
                ("breadth_fields_match_gold", dg.AssetCheckResult(passed=False)),
            ),
        )
        prod_metadata = prod_clickhouse_serving_checks._base_metadata(
            check_scope=CheckScope.RECONCILIATION,
            partition_keys=("2026-06-24",),
        )

        self.assertFalse(local_result.passed)
        self.assertIn(
            "失败",
            _metadata_value(local_result.metadata["goldenshare/summary"]),
        )
        self.assertEqual(
            _metadata_value(local_result.metadata["goldenshare/failed_rule_names"]),
            ["breadth_fields_match_gold"],
        )
        self.assertIn("goldenshare/summary", prod_metadata)
        self.assertIn("goldenshare/next_action", prod_metadata)
        self.assertIn("goldenshare/rule_summary", prod_metadata)


if __name__ == "__main__":
    unittest.main()
