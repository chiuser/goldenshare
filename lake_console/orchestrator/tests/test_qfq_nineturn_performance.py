from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from orchestrator.defs.bootstrap.qfq_nineturn_history import (
    build_qfq_nineturn_history,
    plan_qfq_nineturn_history,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.qfq_nineturn import (
    QFQ_NINETURN_COMPARISON_LAG,
)
from tests.qfq_nineturn_history_fixture import (
    build_qfq_nineturn_history_fixture,
)


class QfqNineturnPerformanceTests(unittest.TestCase):
    def test_annual_batches_scan_each_business_row_once_and_bound_state(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dates = build_qfq_nineturn_history_fixture(root)
            resource = DuckDBResource()
            plan = plan_qfq_nineturn_history(
                lake_root=root,
                duckdb_resource=resource,
                output_dir=root / "reports",
            )

            self.assertEqual(plan.report["performance"]["historical_rescan_multiplier"], 1)
            self.assertEqual(
                plan.report["performance"]["source_business_rows_scanned"],
                len(dates) * 2 * 5,
            )
            report = build_qfq_nineturn_history(
                plan=plan,
                expected_plan_fingerprint=plan.plan_fingerprint,
                duckdb_resource=resource,
                output_dir=root / "reports",
            )
            for result in report.batch_results:
                self.assertLessEqual(
                    result.context_row_count,
                    result.seed_row_count * QFQ_NINETURN_COMPARISON_LAG,
                )


if __name__ == "__main__":
    unittest.main()
