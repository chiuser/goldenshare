from datetime import date
import unittest

from orchestrator.defs.asset_guards.dc_daily_technical_clickhouse_readiness import (
    batch_ch_dc_daily_technical_lake_readiness,
    batch_prod_ch_dc_daily_technical_lake_readiness,
)


class _FakeClient:
    def __init__(self, rows=None, error: Exception | None = None) -> None:
        self.rows = rows or []
        self.error = error
        self.calls = 0

    def execute(self, query: str, params=None):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.rows


class DcDailyTechnicalClickHouseReadinessTests(unittest.TestCase):
    def test_missing_partition_is_not_materialized_and_can_be_selected(self) -> None:
        client = _FakeClient([])
        result = batch_ch_dc_daily_technical_lake_readiness(
            client=client,
            expected_trade_dates=("2026-07-14",),
            registered_trade_days=("2026-07-14",),
        )
        status = result.status_for_trade_date("2026-07-14")
        self.assertEqual(client.calls, 1)
        self.assertFalse(status.materialized)
        self.assertFalse(status.ready)
        self.assertEqual(status.reason, "missing_clickhouse_partition")

    def test_existing_bad_partition_is_materialized_but_not_ready(self) -> None:
        client = _FakeClient(
            [
                (date(2026, 7, 14), 10, 9, 0, 0, 1, 0),
            ]
        )
        result = batch_ch_dc_daily_technical_lake_readiness(
            client=client,
            expected_trade_dates=("2026-07-14",),
            registered_trade_days=("2026-07-14",),
        )
        status = result.status_for_trade_date("2026-07-14")
        self.assertTrue(status.materialized)
        self.assertFalse(status.checks_passed)
        self.assertEqual(status.reason, "core_check_failed")
        self.assertIn("business_key_unique", status.summary["failed_rules"])

    def test_missing_table_is_not_reported_as_a_check_failure(self) -> None:
        client = _FakeClient(error=RuntimeError("UNKNOWN_TABLE board_fact_technical_daily"))
        result = batch_ch_dc_daily_technical_lake_readiness(
            client=client,
            expected_trade_dates=("2026-07-14",),
            registered_trade_days=("2026-07-14",),
        )
        status = result.status_for_trade_date("2026-07-14")
        self.assertFalse(status.materialized)
        self.assertEqual(status.reason, "missing_clickhouse_table")

    def test_window_is_bounded(self) -> None:
        client = _FakeClient()
        with self.assertRaisesRegex(ValueError, "exceeds"):
            batch_ch_dc_daily_technical_lake_readiness(
                client=client,
                expected_trade_dates=tuple(f"2026-07-{day:02d}" for day in range(1, 12)),
                registered_trade_days=(),
            )

    def test_prod_readiness_waits_for_local_before_prod(self) -> None:
        local_client = _FakeClient([])
        prod_client = _FakeClient(
            [(date(2026, 7, 14), 10, 10, 0, 0, 0, 0)]
        )
        result = batch_prod_ch_dc_daily_technical_lake_readiness(
            local_client=local_client,
            prod_client=prod_client,
            expected_trade_dates=("2026-07-14",),
            registered_trade_days=("2026-07-14",),
        )
        status = result.status_for_trade_date("2026-07-14")
        self.assertEqual(local_client.calls, 1)
        self.assertEqual(prod_client.calls, 1)
        self.assertFalse(status.materialized)
        self.assertEqual(status.reason, "local_not_ready")

    def test_prod_readiness_selects_missing_prod_partition_after_local_ready(self) -> None:
        row = [(date(2026, 7, 14), 10, 10, 0, 0, 0, 0)]
        result = batch_prod_ch_dc_daily_technical_lake_readiness(
            local_client=_FakeClient(row),
            prod_client=_FakeClient([]),
            expected_trade_dates=("2026-07-14",),
            registered_trade_days=("2026-07-14",),
        )
        status = result.status_for_trade_date("2026-07-14")
        self.assertFalse(status.materialized)
        self.assertEqual(status.reason, "missing_prod_clickhouse_partition")

    def test_prod_readiness_preserves_prod_check_failure_as_manual_block(self) -> None:
        local_row = [(date(2026, 7, 14), 10, 10, 0, 0, 0, 0)]
        prod_row = [(date(2026, 7, 14), 10, 9, 0, 0, 0, 0)]
        result = batch_prod_ch_dc_daily_technical_lake_readiness(
            local_client=_FakeClient(local_row),
            prod_client=_FakeClient(prod_row),
            expected_trade_dates=("2026-07-14",),
            registered_trade_days=("2026-07-14",),
        )
        status = result.status_for_trade_date("2026-07-14")
        self.assertTrue(status.materialized)
        self.assertFalse(status.checks_passed)
        self.assertEqual(status.reason, "prod_materialized_check_failed")
