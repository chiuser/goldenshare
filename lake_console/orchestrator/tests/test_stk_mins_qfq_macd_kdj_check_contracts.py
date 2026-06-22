import unittest

from orchestrator.defs.assets.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS,
)
from orchestrator.defs.checks import stk_mins_qfq_macd_kdj_checks as checks
from orchestrator.defs.jobs.gold_stk_mins_qfq_macd_kdj_daily_update import (
    gold_stk_mins_qfq_macd_kdj_check_refresh_job,
    gold_stk_mins_qfq_macd_kdj_daily_update_job,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days


def _macd_kdj_asset_keys() -> set:
    return {
        asset_key
        for asset_definition in GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS
        for asset_key in asset_definition.keys
    }


class StkMinsQfqMacdKdjCheckContractTests(unittest.TestCase):
    def test_macd_kdj_indicator_and_state_checks_are_partitioned(self) -> None:
        for freq in (1, 5, 15, 30, 60, 90, 120):
            for check_name in checks.GOLD_STK_MINS_QFQ_MACD_KDJ_CHECK_NAMES:
                with self.subTest(freq=freq, check_name=check_name):
                    check_definition = getattr(
                        checks,
                        f"gold_stk_mins_qfq_macd_kdj_{freq}m_{check_name}",
                    )
                    self.assertEqual(
                        check_definition.partitions_def,
                        cn_a_stock_mins_silver_trade_days,
                    )

            for check_name in checks.GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECK_NAMES:
                with self.subTest(freq=freq, check_name=check_name):
                    check_definition = getattr(
                        checks,
                        f"gold_stk_mins_qfq_macd_kdj_state_{freq}m_{check_name}",
                    )
                    self.assertEqual(
                        check_definition.partitions_def,
                        cn_a_stock_mins_silver_trade_days,
                    )

    def test_check_refresh_job_selects_checks_only(self) -> None:
        selected_assets = gold_stk_mins_qfq_macd_kdj_check_refresh_job.selection.resolve(
            GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS
        )

        self.assertEqual(
            gold_stk_mins_qfq_macd_kdj_check_refresh_job.name,
            "gold_stk_mins_qfq_macd_kdj_check_refresh_job",
        )
        self.assertEqual(
            gold_stk_mins_qfq_macd_kdj_check_refresh_job.partitions_def,
            cn_a_stock_mins_silver_trade_days,
        )
        self.assertEqual(selected_assets, set())
        self.assertIn(
            "AssetChecksForAssetKeysSelection",
            repr(gold_stk_mins_qfq_macd_kdj_check_refresh_job.selection),
        )
        self.assertNotIn(
            "KeysAssetSelection",
            repr(gold_stk_mins_qfq_macd_kdj_check_refresh_job.selection),
        )

    def test_daily_job_still_selects_assets_and_checks(self) -> None:
        selected_assets = gold_stk_mins_qfq_macd_kdj_daily_update_job.selection.resolve(
            GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS
        )

        self.assertEqual(
            selected_assets,
            _macd_kdj_asset_keys(),
        )
        self.assertIn(
            "AssetChecksForAssetKeysSelection",
            repr(gold_stk_mins_qfq_macd_kdj_daily_update_job.selection),
        )
        self.assertIn(
            "KeysAssetSelection",
            repr(gold_stk_mins_qfq_macd_kdj_daily_update_job.selection),
        )


if __name__ == "__main__":
    unittest.main()
