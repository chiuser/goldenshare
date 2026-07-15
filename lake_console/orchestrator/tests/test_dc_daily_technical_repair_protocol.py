from __future__ import annotations

from pathlib import Path
import unittest

from orchestrator.defs.asset_guards.dc_daily_silver_repair import (
    build_dc_daily_silver_repair_batch,
    parse_dc_daily_silver_repair_batch,
)
from orchestrator.defs.run_contracts.silver_repair import (
    SilverRepairBatchValidationError,
    hash_affected_series,
    parse_silver_repair_batch,
)


EXPECTED_DATES = (
    "2024-01-02",
    "2024-01-03",
    "2024-01-04",
    "2024-01-05",
    "2024-01-08",
)
SERIES_HASH = hash_affected_series(("BK0001.DC|行业", "BK0002.DC|概念"))


def _batch(**overrides: object):
    values: dict[str, object] = {
        "producer_run_id": "silver-run-42",
        "source_revision": "silver-dc-daily:run-42",
        "source_repair_start_trade_date": "2024-01-03",
        "source_repair_end_trade_date": "2024-01-04",
        "indicator_recompute_start_trade_date": "2024-01-02",
        "indicator_recompute_end_trade_date": "2024-01-05",
        "context_start_trade_date": "2024-01-02",
        "target_frontier_trade_date": "2024-01-05",
        "affected_date_count": 2,
        "affected_series_count": 2,
        "affected_series_hash": SERIES_HASH,
        "truncated": False,
        "selected_partition_count": 4,
        "expected_trade_dates": EXPECTED_DATES,
        "registered_trade_dates": EXPECTED_DATES,
    }
    values.update(overrides)
    return build_dc_daily_silver_repair_batch(**values)


class DcDailyTechnicalRepairProtocolTests(unittest.TestCase):
    def test_producer_batch_has_explicit_identity_and_separate_ranges(self) -> None:
        batch = _batch()

        self.assertEqual(batch.source_asset, "silver_dc_daily")
        self.assertEqual(batch.status, "ready")
        self.assertTrue(batch.upstream_batch_id.startswith("silver_dc_daily_repair:"))
        self.assertEqual(batch.source_revision, "silver-dc-daily:run-42")
        self.assertEqual(batch.affected_date_count, 2)
        self.assertEqual(batch.selected_partition_count, 4)
        self.assertEqual(batch.context_start_trade_date, "2024-01-02")

    def test_round_trip_supports_plain_and_namespaced_metadata(self) -> None:
        batch = _batch()

        plain = parse_dc_daily_silver_repair_batch(
            batch.to_payload(),
            expected_trade_dates=EXPECTED_DATES,
            registered_trade_dates=EXPECTED_DATES,
        )
        namespaced = parse_dc_daily_silver_repair_batch(
            batch.to_metadata(),
            expected_trade_dates=EXPECTED_DATES,
            registered_trade_dates=EXPECTED_DATES,
        )

        self.assertEqual(plain, batch)
        self.assertEqual(namespaced, batch)

    def test_source_revision_is_required(self) -> None:
        with self.assertRaisesRegex(SilverRepairBatchValidationError, "source_revision"):
            _batch(source_revision="")

    def test_source_and_indicator_ranges_are_distinct_but_source_is_covered(self) -> None:
        with self.assertRaisesRegex(
            SilverRepairBatchValidationError,
            "indicator recompute range must cover the source repair start",
        ):
            _batch(
                indicator_recompute_start_trade_date="2024-01-04",
                selected_partition_count=2,
            )

        with self.assertRaisesRegex(
            SilverRepairBatchValidationError,
            "indicator recompute range must cover the source repair end",
        ):
            _batch(
                indicator_recompute_end_trade_date="2024-01-03",
                selected_partition_count=2,
            )

    def test_counts_must_match_expected_calendar(self) -> None:
        with self.assertRaisesRegex(
            SilverRepairBatchValidationError,
            "affected_date_count does not match",
        ):
            _batch(affected_date_count=1)

        with self.assertRaisesRegex(
            SilverRepairBatchValidationError,
            "selected_partition_count does not match",
        ):
            _batch(selected_partition_count=2)

    def test_ranges_must_be_expected_and_registered(self) -> None:
        with self.assertRaisesRegex(
            SilverRepairBatchValidationError,
            "outside expected calendar",
        ):
            _batch(target_frontier_trade_date="2024-01-09")

        with self.assertRaisesRegex(
            SilverRepairBatchValidationError,
            "unregistered dates",
        ):
            _batch(registered_trade_dates=EXPECTED_DATES[:3])

    def test_context_start_cannot_be_later_than_recompute_start(self) -> None:
        with self.assertRaisesRegex(
            SilverRepairBatchValidationError,
            "context_start_trade_date",
        ):
            _batch(context_start_trade_date="2024-01-03")

    def test_ready_batch_rejects_truncation_and_budget_overflow(self) -> None:
        with self.assertRaisesRegex(
            SilverRepairBatchValidationError,
            "truncated",
        ):
            _batch(truncated=True)

        batch = _batch()
        with self.assertRaisesRegex(
            SilverRepairBatchValidationError,
            "bounded budget",
        ):
            parse_silver_repair_batch(
                batch.to_payload(),
                expected_trade_dates=EXPECTED_DATES,
                max_indicator_recompute_dates=3,
            )

    def test_non_ready_status_is_fail_closed(self) -> None:
        with self.assertRaisesRegex(SilverRepairBatchValidationError, "not ready"):
            _batch(status="failed")

    def test_source_asset_is_fixed_by_dc_daily_adapter(self) -> None:
        payload = _batch().to_payload()
        payload["source_asset"] = "silver_other_asset"

        with self.assertRaisesRegex(ValueError, "silver_dc_daily"):
            parse_dc_daily_silver_repair_batch(payload)

    def test_series_hash_is_stable_and_does_not_require_metadata_series_list(self) -> None:
        self.assertEqual(
            hash_affected_series(("bk0002.dc|概念", "BK0001.DC|行业")),
            SERIES_HASH,
        )
        self.assertNotIn("BK0001.DC|行业", _batch().to_payload().values())

    def test_protocol_modules_do_not_scan_dagster_history_or_define_repair_sensor(self) -> None:
        source_root = Path(__file__).parents[1] / "src" / "orchestrator" / "defs"
        protocol_source = (
            source_root / "run_contracts" / "silver_repair.py"
        ).read_text()
        adapter_source = (
            source_root / "asset_guards" / "dc_daily_silver_repair.py"
        ).read_text()

        for source in (protocol_source, adapter_source):
            self.assertNotIn("get_event_records", source)
            self.assertNotIn("DagsterInstance", source)
            self.assertNotIn("@dg.sensor", source)
        self.assertFalse(
            (source_root / "sensors" / "dc_daily_technical_repair_sensor.py").exists()
        )


if __name__ == "__main__":
    unittest.main()
