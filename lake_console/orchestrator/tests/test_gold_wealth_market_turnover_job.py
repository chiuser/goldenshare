import unittest

from orchestrator.defs.jobs.gold_wealth_market_turnover_update import (
    gold_wealth_market_turnover_update_job,
)


class GoldWealthMarketTurnoverJobTests(unittest.TestCase):
    def test_job_selection_is_gold_turnover_only(self) -> None:
        self.assertEqual(
            gold_wealth_market_turnover_update_job.name,
            "gold_wealth_market_turnover_update_job",
        )

        selection_text = repr(gold_wealth_market_turnover_update_job.selection)

        self.assertIn("gold_wealth_market_turnover", selection_text)
        self.assertIn("AssetChecksForAssetKeysSelection", selection_text)
        for forbidden_fragment in (
            "silver_stk_mins",
            "raw_stk_mins",
            "core_serving",
            "wealth_market_turnover_snapshot",
            "Tushare",
            "ProdPostgres",
        ):
            self.assertNotIn(forbidden_fragment, selection_text)

    def test_job_uses_in_process_executor(self) -> None:
        self.assertEqual(
            gold_wealth_market_turnover_update_job.executor_def.name,
            "in_process",
        )


if __name__ == "__main__":
    unittest.main()
