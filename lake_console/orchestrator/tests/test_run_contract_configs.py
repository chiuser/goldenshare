import unittest

from orchestrator.defs.run_contracts.configs import (
    build_gold_stock_daily_qfq_factor_repair_run_config,
    build_raw_dc_index_update_job_run_config,
    build_raw_index_daily_update_job_run_config,
    build_stock_daily_raw_repair_run_config,
    parse_stock_daily_raw_config,
)
from orchestrator.defs.run_contracts.requests import build_run_request


class RunContractConfigTests(unittest.TestCase):
    def test_raw_dc_index_run_config_keeps_only_frozen_reference_summary(self) -> None:
        config = build_raw_dc_index_update_job_run_config(
            partition_key="2026-07-14",
            reference_trade_date="2026-07-14",
            reference_observed_at="2026-07-14T21:25:00+08:00",
            reference_fingerprint="a" * 64,
        )
        self.assertEqual(
            config,
            {
                "ops": {
                    "raw_tushare_dc_index": {
                        "config": {
                            "reference_trade_date": "2026-07-14",
                            "reference_observed_at": "2026-07-14T21:25:00+08:00",
                            "reference_fingerprint": "a" * 64,
                        }
                    }
                }
            },
        )

    def test_raw_dc_index_run_config_rejects_incomplete_or_misaligned_reference(self) -> None:
        with self.assertRaisesRegex(ValueError, "must equal partition_key"):
            build_raw_dc_index_update_job_run_config(
                partition_key="2026-07-14",
                reference_trade_date="2026-07-15",
                reference_observed_at="2026-07-14T21:25:00+08:00",
                reference_fingerprint="a" * 64,
            )
        with self.assertRaisesRegex(ValueError, "timezone"):
            build_raw_dc_index_update_job_run_config(
                partition_key="2026-07-14",
                reference_trade_date="2026-07-14",
                reference_observed_at="2026-07-14T21:25:00",
                reference_fingerprint="a" * 64,
            )

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

    def test_gold_stock_daily_qfq_factor_repair_run_config_has_no_stock_codes(self) -> None:
        config = build_gold_stock_daily_qfq_factor_repair_run_config(
            qfq_factor_trade_date="2026-06-18",
            repair_required_codes_hash="a" * 64,
            upstream_batch_id="gold_stock_daily_qfq_update:2026-06-18:abc123",
        )

        self.assertEqual(
            config,
            {
                "ops": {
                    "gold_stock_daily_qfq_factor_repair_op": {
                        "config": {
                            "qfq_factor_trade_date": "2026-06-18",
                            "repair_required_codes_hash": "a" * 64,
                            "upstream_batch_id": (
                                "gold_stock_daily_qfq_update:2026-06-18:abc123"
                            ),
                        }
                    }
                }
            },
        )
        self.assertNotIn(
            "stock_codes",
            config["ops"]["gold_stock_daily_qfq_factor_repair_op"]["config"],
        )

    def test_gold_stock_daily_qfq_factor_repair_run_config_rejects_invalid_inputs(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "qfq_factor_trade_date must use YYYY-MM-DD format",
        ):
            build_gold_stock_daily_qfq_factor_repair_run_config(
                qfq_factor_trade_date="20260618",
                repair_required_codes_hash="a" * 64,
                upstream_batch_id="gold_stock_daily_qfq_update:2026-06-18:abc123",
            )

        with self.assertRaisesRegex(ValueError, "SHA-256 hex string"):
            build_gold_stock_daily_qfq_factor_repair_run_config(
                qfq_factor_trade_date="2026-06-18",
                repair_required_codes_hash="abc",
                upstream_batch_id="gold_stock_daily_qfq_update:2026-06-18:abc123",
            )

        with self.assertRaisesRegex(ValueError, "upstream_batch_id is required"):
            build_gold_stock_daily_qfq_factor_repair_run_config(
                qfq_factor_trade_date="2026-06-18",
                repair_required_codes_hash="a" * 64,
                upstream_batch_id="",
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
