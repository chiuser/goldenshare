import unittest

from orchestrator.defs.run_contracts.configs import (
    DcBoardSourceFreezeConfig,
    build_gold_stock_daily_qfq_factor_repair_run_config,
    build_raw_dc_board_update_job_run_config,
    build_raw_index_daily_update_job_run_config,
    build_silver_dc_industry_hierarchy_update_job_run_config,
    build_stock_daily_raw_repair_run_config,
    build_stock_mins_silver_reuse_existing_run_config,
    parse_stock_daily_raw_config,
    parse_stock_mins_silver_config,
)
from orchestrator.defs.run_contracts.requests import build_run_request


class RunContractConfigTests(unittest.TestCase):
    def test_dc_industry_hierarchy_run_config_accepts_only_explicit_iso_reference_date(
        self,
    ) -> None:
        self.assertEqual(
            build_silver_dc_industry_hierarchy_update_job_run_config(
                reference_trade_date="2026-07-31"
            ),
            {
                "ops": {
                    "silver_dc_industry_hierarchy": {
                        "config": {"reference_trade_date": "2026-07-31"}
                    }
                }
            },
        )
        with self.assertRaisesRegex(ValueError, "reference_trade_date"):
            build_silver_dc_industry_hierarchy_update_job_run_config(
                reference_trade_date="20260731"
            )

    def test_dc_source_proof_builder_requires_matching_asset_and_partition(self):
        proof = DcBoardSourceFreezeConfig(
            policy_version="dc_board_quote_coverage_v1", trade_date="2026-07-14",
            target_asset="raw_tushare_dc_index", prod_observed_at_second="2026-07-14T13:25:00+00:00",
            prod_fingerprint_second="a" * 64, source_observed_at_second="2026-07-14T13:35:00+00:00",
            source_fingerprint_second="b" * 64, history_start="2024-01-02",
            history_file_count=0, history_evidence_digest="c" * 64, coverage_gap_count=0)
        config = build_raw_dc_board_update_job_run_config(asset_name=proof.target_asset,
            partition_key=proof.trade_date, proof=proof)
        self.assertEqual(config["ops"][proof.target_asset]["config"], {"source_proof": proof.model_dump(), "recovery_identity": None})
        for asset, day in (("raw_tushare_dc_daily", proof.trade_date), (proof.target_asset, "2026-07-15")):
            with self.assertRaises(ValueError):
                build_raw_dc_board_update_job_run_config(asset_name=asset, partition_key=day, proof=proof)
        with self.assertRaises(TypeError):
            build_raw_dc_board_update_job_run_config(partition_key=proof.trade_date,
                prod_completion_fingerprint="a" * 64)

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

    def test_raw_index_daily_update_job_run_config_rejects_invalid_partition(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "partition_key must use YYYY-MM-DD format",
        ):
            build_raw_index_daily_update_job_run_config(
                partition_key="20260526",
                write_mode="replace",
            )

    def test_stock_mins_silver_reuse_existing_run_config_is_explicit_and_complete(
        self,
    ) -> None:
        config = build_stock_mins_silver_reuse_existing_run_config()

        self.assertEqual(
            tuple(config["ops"]),
            (
                "silver_stk_mins_1m",
                "silver_stk_mins_5m",
                "silver_stk_mins_15m",
                "silver_stk_mins_30m",
                "silver_stk_mins_60m",
            ),
        )
        for op_config in config["ops"].values():
            parsed = parse_stock_mins_silver_config(op_config["config"])
            self.assertEqual(parsed.write_mode, "reuse_existing")
        self.assertEqual(
            parse_stock_mins_silver_config({}).write_mode,
            "write_new",
        )

    def test_stock_mins_silver_config_rejects_ambiguous_or_unknown_modes(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one branch"):
            parse_stock_mins_silver_config(
                {"write_mode": {"write_new": {}, "reuse_existing": {}}}
            )
        with self.assertRaisesRegex(ValueError, "exactly one branch"):
            parse_stock_mins_silver_config({"write_mode": {"replace": {}}})

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

    def test_gold_stock_daily_qfq_factor_repair_run_config_has_no_stock_codes(
        self,
    ) -> None:
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

    def test_gold_stock_daily_qfq_factor_repair_run_config_rejects_invalid_inputs(
        self,
    ) -> None:
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
