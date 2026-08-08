import unittest

from orchestrator.defs.assets.qfq_nineturn import (
    GOLD_STK_MINS_QFQ_NINETURN_ASSETS,
    gold_stock_daily_qfq_nineturn,
)
from orchestrator.defs.jobs.stk_mins_qfq_nineturn_update import (
    gold_stk_mins_qfq_nineturn_update_job,
)
from orchestrator.defs.jobs.stock_daily_qfq_nineturn_update import (
    gold_stock_daily_qfq_nineturn_update_job,
)


class QfqNineturnJobTests(unittest.TestCase):
    def test_daily_job_selects_only_daily_nineturn_asset(self) -> None:
        selected = gold_stock_daily_qfq_nineturn_update_job.selection.resolve(
            [gold_stock_daily_qfq_nineturn]
        )

        self.assertEqual(
            gold_stock_daily_qfq_nineturn_update_job.name,
            "gold_stock_daily_qfq_nineturn_update_job",
        )
        self.assertEqual(selected, {gold_stock_daily_qfq_nineturn.key})

    def test_minute_job_selects_exactly_four_nineturn_assets(self) -> None:
        selected = gold_stk_mins_qfq_nineturn_update_job.selection.resolve(
            GOLD_STK_MINS_QFQ_NINETURN_ASSETS
        )

        self.assertEqual(
            gold_stk_mins_qfq_nineturn_update_job.name,
            "gold_stk_mins_qfq_nineturn_update_job",
        )
        self.assertEqual(
            selected,
            {asset.key for asset in GOLD_STK_MINS_QFQ_NINETURN_ASSETS},
        )
        self.assertIsNotNone(gold_stk_mins_qfq_nineturn_update_job.executor_def)


if __name__ == "__main__":
    unittest.main()
