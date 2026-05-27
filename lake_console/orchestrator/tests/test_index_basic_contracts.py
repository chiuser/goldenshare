import unittest

import dagster as dg

from orchestrator.defs.assets.index_basic import (
    _latest_registered_index_trade_date,
    raw_tushare_index_basic,
    silver_index_basic,
)
from orchestrator.defs.jobs.index_basic_update import index_basic_update_job
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)


class IndexBasicContractTests(unittest.TestCase):
    def test_latest_registered_index_trade_date_selects_latest_not_after_today(
        self,
    ) -> None:
        self.assertEqual(
            _latest_registered_index_trade_date(
                ("2026-05-25", "2026-05-27", "2026-05-26"),
                "2026-05-26",
            ),
            "2026-05-26",
        )

    def test_latest_registered_index_trade_date_returns_none_without_eligible_day(
        self,
    ) -> None:
        self.assertIsNone(_latest_registered_index_trade_date((), "2026-05-26"))
        self.assertIsNone(
            _latest_registered_index_trade_date(("2026-05-27",), "2026-05-26")
        )

    def test_silver_index_basic_no_longer_exposes_required_config(self) -> None:
        self.assertFalse(silver_index_basic.node_def.compute_fn.has_config_arg())

    def test_index_basic_update_job_accepts_empty_run_config(self) -> None:
        job_def = self._index_basic_update_job_def()
        validated_config = dg.validate_run_config(job_def, {})

        self.assertIn("ops", validated_config)

    def test_index_basic_update_job_rejects_old_ready_for_trade_date_config(
        self,
    ) -> None:
        job_def = self._index_basic_update_job_def()

        with self.assertRaises(dg.DagsterInvalidConfigError):
            dg.validate_run_config(
                job_def,
                {
                    "ops": {
                        "silver_index_basic": {
                            "config": {"ready_for_trade_date": "2026-05-26"}
                        }
                    }
                },
            )

    def _index_basic_update_job_def(self) -> dg.JobDefinition:
        defs = dg.Definitions(
            assets=[raw_tushare_index_basic, silver_index_basic],
            jobs=[index_basic_update_job],
            resources={
                "lake_root": LakeRootResource(root_path="/tmp/goldenshare-test-lake"),
                "duckdb": DuckDBResource(),
                "tushare": TushareResource(token="dummy"),
            },
        )
        return defs.resolve_job_def("index_basic_update_job")


if __name__ == "__main__":
    unittest.main()
