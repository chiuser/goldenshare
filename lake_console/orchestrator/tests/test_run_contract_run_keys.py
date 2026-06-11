import unittest

from orchestrator.defs.run_contracts.run_keys import (
    build_asset_update_run_key,
    build_batch_id,
    build_repair_attempt_run_key,
    build_upstream_triggered_run_key,
)


class RunContractRunKeyTests(unittest.TestCase):
    def test_asset_update_run_key_uses_subject_and_unit_id(self) -> None:
        self.assertEqual(
            build_asset_update_run_key(
                subject="raw_stock_daily_update",
                unit_id="2026-06-09",
            ),
            "raw_stock_daily_update:2026-06-09",
        )

    def test_repair_attempt_run_key_uses_repair_scope_and_attempt(self) -> None:
        self.assertEqual(
            build_repair_attempt_run_key(
                subject="raw_stock_daily_update",
                repair_scope_id="2026-06-09:missing_code_repair:abcdef",
                attempt=2,
            ),
            "raw_stock_daily_update:2026-06-09:missing_code_repair:abcdef:2",
        )

    def test_repair_attempt_run_key_uses_attempt_scope_when_present(self) -> None:
        self.assertEqual(
            build_repair_attempt_run_key(
                subject="index_daily",
                repair_scope_id="2026-06-02:000001.SH:repair",
                attempt_scope="20260604",
                attempt=3,
            ),
            "index_daily:2026-06-02:000001.SH:repair:20260604:3",
        )

    def test_upstream_triggered_run_key_uses_consumer_and_batch_id(self) -> None:
        self.assertEqual(
            build_upstream_triggered_run_key(
                consumer="gold_stk_mins_qfq_macd_kdj_repair",
                upstream_batch_id="qfq_factor_repair:2026-06-09:7f3a9c2d8b41",
            ),
            (
                "gold_stk_mins_qfq_macd_kdj_repair:"
                "qfq_factor_repair:2026-06-09:7f3a9c2d8b41"
            ),
        )

    def test_batch_id_is_stable_for_canonical_payload(self) -> None:
        first = build_batch_id(
            producer="qfq_factor_repair",
            scope="2026-06-09",
            payload={
                "producer_run_id": "run-1",
                "repair_required_codes_hash": "abc",
            },
        )
        second = build_batch_id(
            producer="qfq_factor_repair",
            scope="2026-06-09",
            payload={
                "repair_required_codes_hash": "abc",
                "producer_run_id": "run-1",
            },
        )

        self.assertEqual(first, second)
        self.assertRegex(first, r"^qfq_factor_repair:2026-06-09:[0-9a-f]{12}$")

    def test_batch_id_changes_when_payload_changes(self) -> None:
        first = build_batch_id(
            producer="qfq_factor_repair",
            scope="2026-06-09",
            payload={
                "producer_run_id": "run-1",
                "repair_required_codes_hash": "abc",
            },
        )
        second = build_batch_id(
            producer="qfq_factor_repair",
            scope="2026-06-09",
            payload={
                "producer_run_id": "run-2",
                "repair_required_codes_hash": "abc",
            },
        )

        self.assertNotEqual(first, second)

    def test_batch_id_supports_nested_canonical_payload(self) -> None:
        first = build_batch_id(
            producer="qfq_factor_repair",
            scope="2026-06-09",
            payload={
                "producer_run_id": "run-1",
                "nested": {
                    "codes": ("000001.SZ", "600000.SH"),
                    "counts": [1, 2],
                },
            },
        )
        second = build_batch_id(
            producer="qfq_factor_repair",
            scope="2026-06-09",
            payload={
                "nested": {
                    "counts": [1, 2],
                    "codes": ["000001.SZ", "600000.SH"],
                },
                "producer_run_id": "run-1",
            },
        )

        self.assertEqual(first, second)

    def test_existing_compatible_run_key_templates_are_exact(self) -> None:
        trade_date = "2026-06-09"
        missing_codes_hash = "b" * 12
        repair_attempt = 2
        index_code = "000001.SH"
        evaluation_date = "20260610"

        cases = (
            (
                build_asset_update_run_key(
                    subject="raw_stock_basic_update",
                    unit_id=trade_date,
                ),
                "raw_stock_basic_update:2026-06-09",
            ),
            (
                build_asset_update_run_key(
                    subject="silver_stock_basic_update",
                    unit_id=trade_date,
                ),
                "silver_stock_basic_update:2026-06-09",
            ),
            (
                build_asset_update_run_key(
                    subject="raw_namechange_update",
                    unit_id=f"{trade_date}:morning",
                ),
                "raw_namechange_update:2026-06-09:morning",
            ),
            (
                build_asset_update_run_key(
                    subject="silver_namechange_update",
                    unit_id=f"{trade_date}:evening",
                ),
                "silver_namechange_update:2026-06-09:evening",
            ),
            (
                build_asset_update_run_key(
                    subject="stock_identity_map",
                    unit_id=trade_date,
                ),
                "stock_identity_map:2026-06-09",
            ),
            (
                build_asset_update_run_key(
                    subject="raw_suspend_d_update",
                    unit_id=trade_date,
                ),
                "raw_suspend_d_update:2026-06-09",
            ),
            (
                build_asset_update_run_key(
                    subject="silver_suspend_d_update",
                    unit_id=trade_date,
                ),
                "silver_suspend_d_update:2026-06-09",
            ),
            (
                build_asset_update_run_key(
                    subject="raw_stock_daily_update",
                    unit_id=trade_date,
                ),
                "raw_stock_daily_update:2026-06-09",
            ),
            (
                build_repair_attempt_run_key(
                    subject="raw_stock_daily_update",
                    repair_scope_id=(
                        f"{trade_date}:missing_code_repair:{missing_codes_hash}"
                    ),
                    attempt=repair_attempt,
                ),
                (
                    "raw_stock_daily_update:2026-06-09:"
                    "missing_code_repair:bbbbbbbbbbbb:2"
                ),
            ),
            (
                build_asset_update_run_key(
                    subject="silver_stock_daily_update",
                    unit_id=trade_date,
                ),
                "silver_stock_daily_update:2026-06-09",
            ),
            (
                build_asset_update_run_key(
                    subject="raw_adj_factor_update",
                    unit_id=trade_date,
                ),
                "raw_adj_factor_update:2026-06-09",
            ),
            (
                build_asset_update_run_key(
                    subject="silver_adj_factor_update",
                    unit_id=trade_date,
                ),
                "silver_adj_factor_update:2026-06-09",
            ),
            (
                build_asset_update_run_key(
                    subject="stock_mins_raw_update_from_prod",
                    unit_id=trade_date,
                ),
                "stock_mins_raw_update_from_prod:2026-06-09",
            ),
            (
                build_asset_update_run_key(
                    subject="stock_mins_silver_update",
                    unit_id=trade_date,
                ),
                "stock_mins_silver_update:2026-06-09",
            ),
            (
                build_asset_update_run_key(
                    subject="stock_mins_qfq_daily_update",
                    unit_id=trade_date,
                ),
                "stock_mins_qfq_daily_update:2026-06-09",
            ),
            (
                build_asset_update_run_key(
                    subject="stock_mins_qfq_factor_repair",
                    unit_id=trade_date,
                ),
                "stock_mins_qfq_factor_repair:2026-06-09",
            ),
            (
                build_asset_update_run_key(
                    subject="gold_stk_mins_qfq_macd_kdj_daily_update",
                    unit_id=trade_date,
                ),
                "gold_stk_mins_qfq_macd_kdj_daily_update:2026-06-09",
            ),
            (
                build_asset_update_run_key(
                    subject="index_daily",
                    unit_id=f"{trade_date}:{index_code}",
                ),
                "index_daily:2026-06-09:000001.SH",
            ),
            (
                build_repair_attempt_run_key(
                    subject="index_daily",
                    repair_scope_id=f"{trade_date}:{index_code}:repair",
                    attempt_scope=evaluation_date,
                    attempt=repair_attempt,
                ),
                "index_daily:2026-06-09:000001.SH:repair:20260610:2",
            ),
            (
                build_asset_update_run_key(
                    subject="silver_index_daily",
                    unit_id=trade_date,
                ),
                "silver_index_daily:2026-06-09",
            ),
            (
                build_asset_update_run_key(
                    subject="market_major_indices_daily",
                    unit_id=trade_date,
                ),
                "market_major_indices_daily:2026-06-09",
            ),
        )

        for actual, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(actual, expected)

    def test_segment_validation_rejects_empty_segments(self) -> None:
        with self.assertRaisesRegex(ValueError, "subject must be a non-empty string"):
            build_asset_update_run_key(subject=" ", unit_id="2026-06-09")

        with self.assertRaisesRegex(ValueError, "unit_id must be a non-empty string"):
            build_asset_update_run_key(subject="raw_stock_daily_update", unit_id="")

        with self.assertRaisesRegex(ValueError, "consumer must be a non-empty string"):
            build_upstream_triggered_run_key(
                consumer="",
                upstream_batch_id="qfq_factor_repair:2026-06-09:abcdef",
            )

    def test_segment_validation_rejects_non_string_segments(self) -> None:
        with self.assertRaisesRegex(ValueError, "subject must be a string"):
            build_asset_update_run_key(
                subject=1,  # type: ignore[arg-type]
                unit_id="2026-06-09",
            )

    def test_segment_validation_does_not_rewrite_segments(self) -> None:
        self.assertEqual(
            build_asset_update_run_key(
                subject=" raw_stock_daily_update ",
                unit_id="2026-06-09",
            ),
            " raw_stock_daily_update :2026-06-09",
        )

    def test_repair_attempt_rejects_invalid_attempts(self) -> None:
        for attempt in (0, -1, True, False, 1.2):
            with self.subTest(attempt=attempt):
                with self.assertRaisesRegex(ValueError, "attempt must"):
                    build_repair_attempt_run_key(
                        subject="index_daily",
                        repair_scope_id="2026-06-09:000001.SH:repair",
                        attempt=attempt,  # type: ignore[arg-type]
                    )

    def test_repair_attempt_omits_blank_attempt_scope(self) -> None:
        self.assertEqual(
            build_repair_attempt_run_key(
                subject="index_daily",
                repair_scope_id="2026-06-09:000001.SH:repair",
                attempt_scope=" ",
                attempt=1,
            ),
            "index_daily:2026-06-09:000001.SH:repair:1",
        )

    def test_repair_attempt_rejects_non_string_attempt_scope(self) -> None:
        with self.assertRaisesRegex(ValueError, "attempt_scope must be a string"):
            build_repair_attempt_run_key(
                subject="index_daily",
                repair_scope_id="2026-06-09:000001.SH:repair",
                attempt_scope=1,  # type: ignore[arg-type]
                attempt=1,
            )

    def test_batch_id_rejects_invalid_digest_length(self) -> None:
        for digest_length in (0, -1, 65, True):
            with self.subTest(digest_length=digest_length):
                with self.assertRaisesRegex(ValueError, "digest_length must"):
                    build_batch_id(
                        producer="qfq_factor_repair",
                        scope="2026-06-09",
                        payload={"producer_run_id": "run-1"},
                        digest_length=digest_length,  # type: ignore[arg-type]
                    )

    def test_batch_id_rejects_missing_required_payload_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "payload must be non-empty"):
            build_batch_id(
                producer="qfq_factor_repair",
                scope="2026-06-09",
                payload={},
            )

        with self.assertRaisesRegex(
            ValueError,
            "payload must contain producer_run_id",
        ):
            build_batch_id(
                producer="qfq_factor_repair",
                scope="2026-06-09",
                payload={"repair_required_codes_hash": "abc"},
            )

    def test_batch_id_rejects_storage_id_payload_keys(self) -> None:
        for forbidden_key in (
            "event_storage_id",
            "event_storage_ids",
            "storage_id",
            "storage_ids",
        ):
            with self.subTest(forbidden_key=forbidden_key):
                with self.assertRaisesRegex(ValueError, forbidden_key):
                    build_batch_id(
                        producer="qfq_factor_repair",
                        scope="2026-06-09",
                        payload={
                            "producer_run_id": "run-1",
                            forbidden_key: 1,
                        },
                    )

    def test_batch_id_rejects_nested_storage_id_payload_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "storage_ids"):
            build_batch_id(
                producer="qfq_factor_repair",
                scope="2026-06-09",
                payload={
                    "producer_run_id": "run-1",
                    "nested": {"storage_ids": [1, 2]},
                },
            )

    def test_batch_id_rejects_invalid_payload_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "payload keys must be strings"):
            build_batch_id(
                producer="qfq_factor_repair",
                scope="2026-06-09",
                payload={
                    "producer_run_id": "run-1",
                    1: "bad",  # type: ignore[dict-item]
                },
            )

        with self.assertRaisesRegex(
            ValueError,
            "payload keys must be non-empty strings",
        ):
            build_batch_id(
                producer="qfq_factor_repair",
                scope="2026-06-09",
                payload={
                    "producer_run_id": "run-1",
                    " ": "bad",
                },
            )

    def test_batch_id_rejects_non_json_payload_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "payload.bad must be JSON serializable"):
            build_batch_id(
                producer="qfq_factor_repair",
                scope="2026-06-09",
                payload={
                    "producer_run_id": "run-1",
                    "bad": object(),
                },
            )
