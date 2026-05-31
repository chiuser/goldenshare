import unittest

from orchestrator.defs.jobs.stock_mins_silver_update import (
    stock_mins_silver_update_job,
)


class StkMinsSilverM5EJobContractTests(unittest.TestCase):
    def test_stock_mins_silver_update_job_selection_is_silver_only(self) -> None:
        self.assertEqual(stock_mins_silver_update_job.name, "stock_mins_silver_update_job")

        selection_text = repr(stock_mins_silver_update_job.selection)

        for freq in ("1m", "5m", "15m", "30m", "60m"):
            self.assertIn(f"silver_stk_mins_{freq}", selection_text)

        forbidden_selection_fragments = (
            "raw_stk_mins",
            "silver_stock_basic",
            "silver_stock_daily",
            "silver_stock_suspend_daily",
            "silver_stock_identity_map",
            "silver_namechange",
            "gold",
        )
        for fragment in forbidden_selection_fragments:
            self.assertNotIn(fragment, selection_text)

    def test_stock_mins_silver_update_job_uses_in_process_executor(self) -> None:
        self.assertEqual(stock_mins_silver_update_job.executor_def.name, "in_process")


if __name__ == "__main__":
    unittest.main()
