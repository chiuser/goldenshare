import unittest

from orchestrator.defs.assets.qfq_nineturn import (
    GOLD_STK_MINS_QFQ_NINETURN_ASSETS,
    gold_stock_daily_qfq_nineturn,
)
from orchestrator.defs.catalog.lake_assets import get_lake_asset_catalog_entry
from orchestrator.defs.checks.qfq_nineturn_checks import GOLD_QFQ_NINETURN_CHECKS
from orchestrator.defs.partitions import (
    cn_a_stock_mins_silver_trade_days,
    cn_a_stock_trade_days,
)


class QfqNineturnAssetContractTests(unittest.TestCase):
    def test_assets_use_expected_keys_partitions_and_human_descriptions(self) -> None:
        expected_minute_keys = tuple(
            f"gold_stk_mins_qfq_nineturn_{freq}m" for freq in (30, 60, 90, 120)
        )
        self.assertEqual(
            gold_stock_daily_qfq_nineturn.key.to_user_string(),
            "gold_stock_daily_qfq_nineturn",
        )
        self.assertEqual(
            gold_stock_daily_qfq_nineturn.partitions_def,
            cn_a_stock_trade_days,
        )
        self.assertRegex(
            tuple(gold_stock_daily_qfq_nineturn.descriptions_by_key.values())[0],
            r"[\u4e00-\u9fff]",
        )
        self.assertEqual(
            tuple(
                asset.key.to_user_string()
                for asset in GOLD_STK_MINS_QFQ_NINETURN_ASSETS
            ),
            expected_minute_keys,
        )
        for asset in GOLD_STK_MINS_QFQ_NINETURN_ASSETS:
            self.assertEqual(asset.partitions_def, cn_a_stock_mins_silver_trade_days)
            self.assertRegex(
                tuple(asset.descriptions_by_key.values())[0],
                r"[\u4e00-\u9fff]",
            )

    def test_one_blocking_check_and_catalog_entry_per_asset(self) -> None:
        check_pairs = {
            (
                tuple(check_definition.check_specs)[0].asset_key.to_user_string(),
                tuple(check_definition.check_specs)[0].name,
            )
            for check_definition in GOLD_QFQ_NINETURN_CHECKS
        }
        asset_keys = ("gold_stock_daily_qfq_nineturn",) + tuple(
            f"gold_stk_mins_qfq_nineturn_{freq}m" for freq in (30, 60, 90, 120)
        )
        self.assertEqual(len(check_pairs), 5)
        for asset_key in asset_keys:
            entry = get_lake_asset_catalog_entry(asset_key)
            expected_check = (
                "gold_stock_daily_qfq_nineturn_integrity_check"
                if asset_key == "gold_stock_daily_qfq_nineturn"
                else f"{asset_key}_integrity_check"
            )
            self.assertEqual(entry.blocking_check_names, (expected_check,))
            self.assertIn((asset_key, expected_check), check_pairs)
            self.assertEqual(entry.source_system.value, "derived")


if __name__ == "__main__":
    unittest.main()
