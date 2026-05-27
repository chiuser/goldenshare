import unittest

from orchestrator.defs.run_contracts.configs import (
    build_index_daily_update_job_run_config,
)
from orchestrator.defs.run_contracts.requests import build_run_request


class RunContractConfigTests(unittest.TestCase):
    def test_index_daily_update_job_run_config_maps_trade_date_to_raw_window(self) -> None:
        self.assertEqual(
            build_index_daily_update_job_run_config(
                trade_date="2026-05-26",
                write_mode="replace",
            ),
            {
                "ops": {
                    "raw_tushare_index_daily_by_code": {
                        "config": {
                            "start_date": "2026-05-26",
                            "end_date": "2026-05-26",
                            "write_mode": "replace",
                        }
                    }
                }
            },
        )

    def test_index_daily_update_job_run_config_rejects_invalid_trade_date(self) -> None:
        with self.assertRaisesRegex(ValueError, "trade_date must use YYYY-MM-DD format"):
            build_index_daily_update_job_run_config(
                trade_date="20260526",
                write_mode="replace",
            )

    def test_build_run_request_does_not_write_project_run_tags(self) -> None:
        request = build_run_request(
            partition_key="000001.SH",
            run_key="index_daily:2026-05-26:000001.SH",
            run_config=build_index_daily_update_job_run_config(
                trade_date="2026-05-26",
                write_mode="replace",
            ),
        )

        self.assertEqual(request.tags, {})
        self.assertEqual(request.partition_key, "000001.SH")
        self.assertEqual(
            request.run_config["ops"]["raw_tushare_index_daily_by_code"]["config"][
                "start_date"
            ],
            "2026-05-26",
        )
