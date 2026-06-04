import unittest

from orchestrator.defs.assets.stk_mins import GOLD_STK_MINS_QFQ_ASSETS
from orchestrator.defs.jobs.stock_mins_qfq_daily_update import (
    stock_mins_qfq_daily_update_job,
)
from orchestrator.defs.stk_mins_qfq import GOLD_STK_MINS_QFQ_WRITER_POOL


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

    def test_gold_qfq_assets_use_writer_concurrency_pool(self) -> None:
        for asset in GOLD_STK_MINS_QFQ_ASSETS:
            self.assertEqual(asset.node_def.pool, GOLD_STK_MINS_QFQ_WRITER_POOL)


if __name__ == "__main__":
    unittest.main()
