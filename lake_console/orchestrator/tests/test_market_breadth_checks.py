import unittest

import dagster as dg

from orchestrator.defs.checks import market_breadth_checks
from orchestrator.defs.checks import stock_return_distribution_checks


def _metadata_value(value):  # noqa: ANN001
    return getattr(value, "value", value)


class MarketBreadthCheckMetadataTests(unittest.TestCase):
    def test_market_breadth_combined_metadata_is_human_readable(self) -> None:
        result = market_breadth_checks._combined_check_result(
            check_scope=market_breadth_checks.CheckScope.RECONCILIATION,
            rule_results=(
                ("total_count_matches_silver", dg.AssetCheckResult(passed=False)),
                ("matches_silver_recompute", dg.AssetCheckResult(passed=True)),
            ),
        )

        self.assertFalse(result.passed)
        self.assertEqual(
            _metadata_value(result.metadata["goldenshare/failed_rule_names"]),
            ["total_count_matches_silver"],
        )
        self.assertIn("失败", _metadata_value(result.metadata["goldenshare/summary"]))
        self.assertIn(
            "silver_stock_daily",
            _metadata_value(result.metadata["goldenshare/next_action"]),
        )
        self.assertEqual(
            _metadata_value(result.metadata["goldenshare/rule_summary"])[0],
            {"rule_name": "total_count_matches_silver", "passed": False},
        )

    def test_return_distribution_combined_metadata_is_human_readable(self) -> None:
        result = stock_return_distribution_checks._combined_check_result(
            check_scope=stock_return_distribution_checks.CheckScope.RECONCILIATION,
            rule_results=(
                ("total_count_matches_silver", dg.AssetCheckResult(passed=True)),
                ("recomputed_from_silver", dg.AssetCheckResult(passed=False)),
            ),
        )

        self.assertFalse(result.passed)
        self.assertEqual(
            _metadata_value(result.metadata["goldenshare/failed_rule_names"]),
            ["recomputed_from_silver"],
        )
        self.assertIn("失败", _metadata_value(result.metadata["goldenshare/summary"]))
        self.assertIn(
            "分桶口径",
            _metadata_value(result.metadata["goldenshare/next_action"]),
        )
        self.assertEqual(
            _metadata_value(result.metadata["goldenshare/rule_summary"])[1],
            {"rule_name": "recomputed_from_silver", "passed": False},
        )


if __name__ == "__main__":
    unittest.main()
