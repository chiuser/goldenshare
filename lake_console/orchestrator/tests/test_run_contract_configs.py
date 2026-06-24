import unittest

from orchestrator.defs.run_contracts.configs import (
    build_raw_index_daily_update_job_run_config,
    build_stock_daily_raw_repair_run_config,
    parse_stock_daily_raw_config,
)
from orchestrator.defs.run_contracts.requests import build_run_request


class RunContractConfigTests(unittest.TestCase):
    def test_raw_index_daily_update_job_run_config_uses_partition_schema(self) -> None:
        self.assertEqual(
            build_raw_index_daily_update_job_run_config(
                partition_key="2026-05-26",
                write_mode="replace",
            ),
            {
                "ops": {
                    "raw_index_daily": {
                        "config": {
                            "write_mode": "replace",
                        }
                    }
                }
            },
        )

    def test_raw_index_daily_update_job_run_config_rejects_invalid_partition(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "partition_key must use YYYY-MM-DD format",
        ):
            build_raw_index_daily_update_job_run_config(
                partition_key="20260526",
                write_mode="replace",
            )

    def test_build_run_request_does_not_write_project_run_tags(self) -> None:
        request = build_run_request(
            partition_key="2026-05-26",
            run_key="raw_index_daily:2026-05-26",
            run_config=build_raw_index_daily_update_job_run_config(
                partition_key="2026-05-26",
                write_mode="replace",
            ),
        )

        self.assertEqual(request.tags, {})
        self.assertEqual(request.partition_key, "2026-05-26")
        self.assertEqual(
            request.run_config["ops"]["raw_index_daily"]["config"]["write_mode"],
            "replace",
        )

    def test_stock_daily_raw_repair_run_config_uses_single_op_config(self) -> None:
        config = build_stock_daily_raw_repair_run_config(
            ts_codes=["000001.SZ", "600000.SH"],
            missing_codes_hash="a" * 64,
            repair_attempt=2,
        )

        self.assertEqual(
            config,
            {
                "ops": {
                    "raw_tushare_stock_daily": {
                        "config": {
                            "write_mode": {
                                "missing_code_repair": {
                                    "ts_codes": ["000001.SZ", "600000.SH"],
                                    "missing_codes_hash": "a" * 64,
                                    "repair_attempt": 2,
                                }
                            }
                        }
                    }
                }
            },
        )
        parsed = parse_stock_daily_raw_config(
            config["ops"]["raw_tushare_stock_daily"]["config"]
        )
        self.assertEqual(parsed.write_mode, "missing_code_repair")
        self.assertEqual(
            parsed.missing_code_repair.ts_codes,
            ("000001.SZ", "600000.SH"),
        )

    def test_stock_daily_raw_repair_run_config_rejects_invalid_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not contain duplicates"):
            build_stock_daily_raw_repair_run_config(
                ts_codes=["000001.SZ", "000001.SZ"],
                missing_codes_hash="a" * 64,
                repair_attempt=1,
            )

        with self.assertRaisesRegex(ValueError, "more than 100 codes"):
            build_stock_daily_raw_repair_run_config(
                ts_codes=[f"{index:06d}.SZ" for index in range(101)],
                missing_codes_hash="a" * 64,
                repair_attempt=1,
            )

        with self.assertRaisesRegex(ValueError, "SHA-256 hex string"):
            build_stock_daily_raw_repair_run_config(
                ts_codes=["000001.SZ"],
                missing_codes_hash="abc",
                repair_attempt=1,
            )

        with self.assertRaisesRegex(ValueError, "repair_attempt must be positive"):
            build_stock_daily_raw_repair_run_config(
                ts_codes=["000001.SZ"],
                missing_codes_hash="a" * 64,
                repair_attempt=0,
            )
