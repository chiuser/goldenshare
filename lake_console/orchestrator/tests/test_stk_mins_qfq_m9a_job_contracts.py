import unittest

from orchestrator.defs.jobs.stock_mins_qfq_daily_update import (
    stock_mins_qfq_daily_update_job,
)


class StkMinsQfqM9AJobContractTests(unittest.TestCase):
    def test_stock_mins_qfq_daily_update_job_selection_is_gold_only(self) -> None:
        self.assertEqual(
            stock_mins_qfq_daily_update_job.name,
            "stock_mins_qfq_daily_update_job",
        )

        selection_text = repr(stock_mins_qfq_daily_update_job.selection)

        for freq in ("1m", "5m", "15m", "30m", "60m"):
            self.assertIn(f"gold_stk_mins_qfq_{freq}", selection_text)

        forbidden_selection_fragments = (
            "raw_stk_mins",
            "silver_stk_mins",
            "silver_adj_factor",
            "stock_basic",
            "stock_daily",
            "suspend",
            "identity_map",
            "namechange",
            "Tushare",
            "ProdPostgres",
            "repair",
            "summary",
        )
        for fragment in forbidden_selection_fragments:
            self.assertNotIn(fragment, selection_text)

    def test_stock_mins_qfq_daily_update_job_uses_in_process_executor(self) -> None:
        self.assertEqual(
            stock_mins_qfq_daily_update_job.executor_def.name,
            "in_process",
        )


if __name__ == "__main__":
    unittest.main()
