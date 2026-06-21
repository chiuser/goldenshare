import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityExpectedDateWindow,
    build_registered_gap_status,
)
from orchestrator.defs.jobs import suspend_update as suspend_jobs
from orchestrator.defs.run_contracts.cursors import load_sensor_cursor
from orchestrator.defs.run_contracts.sensor_tags import (
    SENSOR_DOMAIN_TAG,
    SENSOR_ROLE_TAG,
    SENSOR_TARGET_LAYER_TAG,
)
from orchestrator.defs.sensors import suspend_d_sensor as suspend_sensor_module
from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    RAW_SUSPEND_D_CHECKS,
    SILVER_SUSPEND_D_CHECKS,
)
from orchestrator.defs.sensors.suspend_d_sensor import (
    raw_suspend_d_update_job_sensor,
    silver_suspend_d_update_job_sensor,
)


class _FakeInstance:
    def __init__(self, partitions: tuple[str, ...]) -> None:
        self._partitions = partitions

    def get_dynamic_partitions(self, _name: str) -> list[str]:
        return list(self._partitions)


class _FakeContext:
    def __init__(self, *, partitions: tuple[str, ...]) -> None:
        self.instance = _FakeInstance(partitions)


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ANN001
        return datetime(2026, 6, 7, 10, 0, tzinfo=tz or UTC)


class _FixedDateTimeAfterGap(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ANN001
        return datetime(2026, 6, 17, 10, 0, tzinfo=tz or UTC)


def _registered_gap(
    *,
    expected_trade_dates: tuple[str, ...],
    registered_trade_dates: tuple[str, ...],
    evaluated_at: datetime | None = None,
):
    expected_window = ContinuityExpectedDateWindow(
        expected_trade_dates=expected_trade_dates,
        min_trade_date="2014-01-01",
        max_trade_date=expected_trade_dates[-1] if expected_trade_dates else None,
        evaluated_at=evaluated_at or _FixedDateTime.now(UTC),
        window_limit=60,
    )
    return expected_window, build_registered_gap_status(
        expected_trade_dates=expected_trade_dates,
        registered_trade_dates=registered_trade_dates,
    )


def _raw_status(
    *,
    ready: bool,
    materialized: bool = True,
    partition_key: str = "2026-06-05",
    missing_check_names: tuple[str, ...] = (),
    failed_check_names: tuple[str, ...] = (),
    reason: str = "ready",
) -> AssetReadinessStatus:
    checks_passed = ready or (not missing_check_names and not failed_check_names)
    return AssetReadinessStatus(
        asset_key="raw_tushare_suspend_d",
        partition_key=partition_key,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        freshness_passed=ready,
        materialization_storage_id=1 if materialized else None,
        materialization_date=partition_key if materialized else None,
        missing_check_names=missing_check_names,
        failed_check_names=failed_check_names,
        reason=reason,
    )


def _raw_sensor_result(context: _FakeContext):
    return raw_suspend_d_update_job_sensor._raw_fn(context)


def _silver_sensor_result(context: _FakeContext):
    return silver_suspend_d_update_job_sensor._raw_fn(context)


class SuspendDSensorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._registered_gap_patcher = patch(
            "orchestrator.defs.sensors.suspend_d_sensor._stock_trade_day_registered_gap",
            side_effect=lambda _context, evaluated_at, registered_keys: _registered_gap(
                expected_trade_dates=tuple(registered_keys),
                registered_trade_dates=tuple(registered_keys),
                evaluated_at=evaluated_at,
            ),
        )
        self.registered_gap_mock = self._registered_gap_patcher.start()

    def tearDown(self) -> None:
        self._registered_gap_patcher.stop()

    def test_job_and_sensor_names_follow_split_rule(self) -> None:
        self.assertTrue(hasattr(suspend_jobs, "raw_suspend_d_update_job"))
        self.assertTrue(hasattr(suspend_jobs, "silver_suspend_d_update_job"))
        self.assertFalse(hasattr(suspend_jobs, "suspend_update_job"))
        self.assertFalse(hasattr(suspend_sensor_module, "suspend_d_sensor"))
        self.assertEqual(
            suspend_jobs.raw_suspend_d_update_job.name,
            "raw_suspend_d_update_job",
        )
        self.assertEqual(
            suspend_jobs.silver_suspend_d_update_job.name,
            "silver_suspend_d_update_job",
        )
        self.assertEqual(
            raw_suspend_d_update_job_sensor.name,
            "raw_suspend_d_update_job_sensor",
        )
        self.assertEqual(
            silver_suspend_d_update_job_sensor.name,
            "silver_suspend_d_update_job_sensor",
        )
        self.assertEqual(
            raw_suspend_d_update_job_sensor.job_name,
            "raw_suspend_d_update_job",
        )
        self.assertEqual(
            silver_suspend_d_update_job_sensor.job_name,
            "silver_suspend_d_update_job",
        )
        raw_selection = repr(suspend_jobs.raw_suspend_d_update_job.selection)
        silver_selection = repr(suspend_jobs.silver_suspend_d_update_job.selection)
        self.assertIn("raw_tushare_suspend_d", raw_selection)
        self.assertNotIn("silver_stock_suspend_daily", raw_selection)
        self.assertIn("silver_stock_suspend_daily", silver_selection)
        self.assertNotIn("raw_tushare_suspend_d", silver_selection)

    def test_sensor_tags_are_layer_specific(self) -> None:
        self.assertEqual(
            raw_suspend_d_update_job_sensor.tags,
            {
                SENSOR_DOMAIN_TAG: "quote_data",
                SENSOR_TARGET_LAYER_TAG: "raw",
                SENSOR_ROLE_TAG: "asset_update",
            },
        )
        self.assertEqual(
            silver_suspend_d_update_job_sensor.tags,
            {
                SENSOR_DOMAIN_TAG: "quote_data",
                SENSOR_TARGET_LAYER_TAG: "silver",
                SENSOR_ROLE_TAG: "asset_update",
            },
        )

    def test_existing_suspend_d_check_names_are_not_renamed(self) -> None:
        self.assertIn("raw_suspend_d_file_exists", RAW_SUSPEND_D_CHECKS)
        self.assertIn("raw_suspend_d_partition_date_matches", RAW_SUSPEND_D_CHECKS)
        self.assertIn("raw_suspend_d_required_columns", RAW_SUSPEND_D_CHECKS)
        self.assertIn(
            "raw_suspend_d_schema_matches_tushare_contract",
            RAW_SUSPEND_D_CHECKS,
        )
        self.assertIn(
            "raw_suspend_d_stock_partition_key_allowed",
            RAW_SUSPEND_D_CHECKS,
        )
        self.assertIn("silver_suspend_d_known_type_values", SILVER_SUSPEND_D_CHECKS)
        self.assertIn(
            "silver_suspend_d_stock_partition_key_allowed",
            SILVER_SUSPEND_D_CHECKS,
        )
        self.assertIn("silver_suspend_d_unique_business_key", SILVER_SUSPEND_D_CHECKS)
        self.assertNotIn("raw_suspend_d_row_count_positive", RAW_SUSPEND_D_CHECKS)

    def test_raw_sensor_submits_run_when_raw_missing(self) -> None:
        context = _FakeContext(partitions=("2026-06-05",))
        with patch(
            "orchestrator.defs.sensors.suspend_d_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.suspend_d_sensor.materialized_partition_keys",
            return_value=set(),
        ):
            result = _raw_sensor_result(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, "2026-06-05")
        self.assertEqual(request.run_key, "raw_suspend_d_update:2026-06-05")
        self.assertEqual(request.run_config, {})

    def test_raw_sensor_skips_registered_gap_before_materialization_scan(self) -> None:
        context = _FakeContext(partitions=("2026-06-13", "2026-06-16"))
        self.registered_gap_mock.side_effect = (
            lambda _context, evaluated_at, registered_keys: _registered_gap(
                expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
                registered_trade_dates=tuple(registered_keys),
                evaluated_at=evaluated_at,
            )
        )
        with patch(
            "orchestrator.defs.sensors.suspend_d_sensor.datetime",
            _FixedDateTimeAfterGap,
        ), patch(
            "orchestrator.defs.sensors.suspend_d_sensor.materialized_partition_keys",
        ) as materialized_mock:
            result = _raw_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("最早缺失日期为 2026-06-15", result.skip_reason.skip_message)
        materialized_mock.assert_not_called()
        cursor_payload = load_sensor_cursor(result.cursor)
        self.assertEqual(cursor_payload["target_date"], "2026-06-15")
        continuity = cursor_payload["details"]["continuity_status"]
        self.assertEqual(continuity["first_missing_registered_date"], "2026-06-15")

    def test_raw_sensor_does_not_rerun_materialized_partition(self) -> None:
        context = _FakeContext(partitions=("2026-06-05",))
        with patch(
            "orchestrator.defs.sensors.suspend_d_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.suspend_d_sensor.materialized_partition_keys",
            return_value={"2026-06-05"},
        ):
            result = _raw_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("raw 分区都已经生成完成", result.skip_reason.skip_message)

    def test_silver_sensor_submits_only_when_raw_ready_and_silver_missing(
        self,
    ) -> None:
        context = _FakeContext(partitions=("2026-06-05",))
        with patch(
            "orchestrator.defs.sensors.suspend_d_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.suspend_d_sensor.materialized_partition_keys",
            return_value=set(),
        ), patch(
            "orchestrator.defs.sensors.suspend_d_sensor.raw_tushare_suspend_d_ready_for_trade_date",
            return_value=_raw_status(ready=True),
        ):
            result = _silver_sensor_result(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, "2026-06-05")
        self.assertEqual(request.run_key, "silver_suspend_d_update:2026-06-05")

    def test_silver_sensor_skips_registered_gap_before_readiness_scan(self) -> None:
        context = _FakeContext(partitions=("2026-06-13", "2026-06-16"))
        self.registered_gap_mock.side_effect = (
            lambda _context, evaluated_at, registered_keys: _registered_gap(
                expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
                registered_trade_dates=tuple(registered_keys),
                evaluated_at=evaluated_at,
            )
        )
        with patch(
            "orchestrator.defs.sensors.suspend_d_sensor.datetime",
            _FixedDateTimeAfterGap,
        ), patch(
            "orchestrator.defs.sensors.suspend_d_sensor.materialized_partition_keys",
        ) as materialized_mock, patch(
            "orchestrator.defs.sensors.suspend_d_sensor.raw_tushare_suspend_d_ready_for_trade_date",
        ) as raw_readiness_mock:
            result = _silver_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("最早缺失日期为 2026-06-15", result.skip_reason.skip_message)
        materialized_mock.assert_not_called()
        raw_readiness_mock.assert_not_called()
        cursor_payload = load_sensor_cursor(result.cursor)
        self.assertEqual(cursor_payload["target_date"], "2026-06-15")
        continuity = cursor_payload["details"]["continuity_status"]
        self.assertEqual(continuity["first_missing_registered_date"], "2026-06-15")

    def test_silver_sensor_skips_when_raw_missing_or_checks_not_ready(self) -> None:
        cases = (
            _raw_status(
                ready=False,
                materialized=False,
                missing_check_names=RAW_SUSPEND_D_CHECKS,
                reason="raw_tushare_suspend_d has no materialization",
            ),
            _raw_status(
                ready=False,
                missing_check_names=("raw_suspend_d_required_columns",),
                reason="raw_tushare_suspend_d missing blocking checks",
            ),
            _raw_status(
                ready=False,
                failed_check_names=("raw_suspend_d_partition_date_matches",),
                reason="raw_tushare_suspend_d failed blocking checks",
            ),
        )
        for raw_status in cases:
            with self.subTest(reason=raw_status.reason):
                context = _FakeContext(partitions=("2026-06-05",))
                with patch(
                    "orchestrator.defs.sensors.suspend_d_sensor.datetime",
                    _FixedDateTime,
                ), patch(
                    "orchestrator.defs.sensors.suspend_d_sensor.materialized_partition_keys",
                    return_value=set(),
                ), patch(
                    "orchestrator.defs.sensors.suspend_d_sensor.raw_tushare_suspend_d_ready_for_trade_date",
                    return_value=raw_status,
                ):
                    result = _silver_sensor_result(context)

                self.assertEqual(result.run_requests, [])
                self.assertIn("raw readiness 门禁未满足", result.skip_reason.skip_message)
                cursor_payload = load_sensor_cursor(result.cursor)
                details = cursor_payload["details"]["readiness_details"]["2026-06-05"]
                self.assertFalse(details["raw_tushare_suspend_d"]["ready"])

    def test_silver_sensor_does_not_rerun_materialized_partition(self) -> None:
        context = _FakeContext(partitions=("2026-06-05",))
        with patch(
            "orchestrator.defs.sensors.suspend_d_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.suspend_d_sensor.materialized_partition_keys",
            return_value={"2026-06-05"},
        ), patch(
            "orchestrator.defs.sensors.suspend_d_sensor.raw_tushare_suspend_d_ready_for_trade_date",
        ) as raw_readiness:
            result = _silver_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("silver 分区都已经生成完成", result.skip_reason.skip_message)
        raw_readiness.assert_not_called()


if __name__ == "__main__":
    unittest.main()
