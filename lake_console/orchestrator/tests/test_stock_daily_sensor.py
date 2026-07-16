import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityExpectedDateWindow,
    build_registered_gap_status,
)
from orchestrator.defs.jobs import stock_daily_update as stock_daily_jobs
from orchestrator.defs.run_contracts.cursors import load_sensor_cursor
from orchestrator.defs.sensors import stock_daily_sensor as stock_daily_sensor_module
from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    DatasetReadinessStatus,
    RAW_STOCK_DAILY_CHECKS,
    SILVER_STOCK_DAILY_BLOCKING_CHECKS,
)
from orchestrator.defs.sensors.stock_daily_raw_repair import (
    StockDailyMissingCodeLocatorResult,
)
from orchestrator.defs.sensors.stock_daily_sensor import (
    raw_stock_daily_update_job_sensor,
    silver_stock_daily_update_job_sensor,
)
from orchestrator.source_readiness.tushare.stock_daily import (
    StockDailySourceReadiness,
)


class _FakeInstance:
    def __init__(self, partitions: tuple[str, ...]) -> None:
        self._partitions = partitions

    def get_dynamic_partitions(self, _name: str) -> list[str]:
        return list(self._partitions)


class _FakeContext:
    def __init__(
        self,
        *,
        partitions: tuple[str, ...],
        cursor: str | None = None,
    ) -> None:
        self.instance = _FakeInstance(partitions)
        self.cursor = cursor
        self.resources = SimpleNamespace(
            tushare=object(),
            duckdb=object(),
            lake_root=SimpleNamespace(root=lambda: object()),
        )


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
        window_limit=10,
    )
    return expected_window, build_registered_gap_status(
        expected_trade_dates=expected_trade_dates,
        registered_trade_dates=registered_trade_dates,
    )


def _asset_status(
    *,
    ready: bool,
    materialized: bool = True,
    partition_key: str = "2026-06-05",
    reason: str = "ready",
) -> AssetReadinessStatus:
    return AssetReadinessStatus(
        asset_key="raw_tushare_stock_daily",
        partition_key=partition_key,
        ready=ready,
        materialized=materialized,
        checks_passed=ready,
        freshness_passed=True,
        materialization_storage_id=1 if materialized else None,
        materialization_date=partition_key if materialized else None,
        missing_check_names=() if ready else ("raw_stock_daily_covers_expected_tradable_universe",),
        failed_check_names=(),
        reason=reason,
    )


def _dataset_status(*, ready: bool, reason: str = "ready") -> DatasetReadinessStatus:
    return DatasetReadinessStatus(
        ready=ready,
        statuses=(
            AssetReadinessStatus(
                asset_key="support",
                partition_key="2026-06-05",
                ready=ready,
                materialized=ready,
                checks_passed=ready,
                freshness_passed=ready,
                materialization_storage_id=1 if ready else None,
                materialization_date="2026-06-05" if ready else None,
                missing_check_names=() if ready else ("support_check",),
                failed_check_names=(),
                reason=reason,
            ),
        ),
    )


def _source_ready(*, ready: bool = True) -> StockDailySourceReadiness:
    return StockDailySourceReadiness(
        is_ready=ready,
        trade_date="2026-06-05",
        row_count=1 if ready else 0,
        checked_at="2026-06-07T10:00:00+08:00",
        reason="ready" if ready else "not ready",
    )


def _raw_sensor_result(context: _FakeContext):
    return raw_stock_daily_update_job_sensor._raw_fn(context)


def _silver_sensor_result(context: _FakeContext):
    return silver_stock_daily_update_job_sensor._raw_fn(context)


class StockDailySensorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._registered_gap_patcher = patch(
            "orchestrator.defs.sensors.stock_daily_sensor._stock_trade_day_registered_gap",
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
        self.assertTrue(hasattr(stock_daily_jobs, "raw_stock_daily_update_job"))
        self.assertTrue(hasattr(stock_daily_jobs, "silver_stock_daily_update_job"))
        self.assertFalse(hasattr(stock_daily_jobs, "stock_daily_update_job"))
        self.assertFalse(hasattr(stock_daily_sensor_module, "stock_daily_sensor"))
        self.assertEqual(
            stock_daily_jobs.raw_stock_daily_update_job.name,
            "raw_stock_daily_update_job",
        )
        self.assertEqual(
            stock_daily_jobs.silver_stock_daily_update_job.name,
            "silver_stock_daily_update_job",
        )
        self.assertEqual(
            raw_stock_daily_update_job_sensor.name,
            "raw_stock_daily_update_job_sensor",
        )
        self.assertEqual(
            silver_stock_daily_update_job_sensor.name,
            "silver_stock_daily_update_job_sensor",
        )
        self.assertEqual(
            raw_stock_daily_update_job_sensor.job_name,
            "raw_stock_daily_update_job",
        )
        self.assertEqual(
            silver_stock_daily_update_job_sensor.job_name,
            "silver_stock_daily_update_job",
        )
        raw_selection = repr(stock_daily_jobs.raw_stock_daily_update_job.selection)
        silver_selection = repr(stock_daily_jobs.silver_stock_daily_update_job.selection)
        self.assertIn("raw_tushare_stock_daily", raw_selection)
        self.assertNotIn("silver_stock_daily", raw_selection)
        self.assertIn("silver_stock_daily", silver_selection)
        self.assertNotIn("raw_tushare_stock_daily", silver_selection)

    def test_existing_stock_daily_check_names_are_not_renamed(self) -> None:
        self.assertIn(
            "raw_stock_daily_tradable_universe_check",
            RAW_STOCK_DAILY_CHECKS,
        )
        self.assertIn(
            "raw_stock_daily_key_integrity_check",
            RAW_STOCK_DAILY_CHECKS,
        )
        self.assertIn(
            "silver_stock_daily_tradable_universe_check",
            SILVER_STOCK_DAILY_BLOCKING_CHECKS,
        )
        self.assertIn(
            "silver_stock_daily_key_integrity_check",
            SILVER_STOCK_DAILY_BLOCKING_CHECKS,
        )
        self.assertIn(
            "silver_stock_daily_lifecycle_coverage_check",
            SILVER_STOCK_DAILY_BLOCKING_CHECKS,
        )
        self.assertNotIn(
            "silver_stock_daily_current_listed_only",
            SILVER_STOCK_DAILY_BLOCKING_CHECKS,
        )

    def test_raw_sensor_submits_full_day_run_when_raw_missing_and_gates_ready(
        self,
    ) -> None:
        context = _FakeContext(partitions=("2026-06-05",))
        with patch(
            "orchestrator.defs.sensors.stock_daily_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.materialized_partition_keys",
            return_value=set(),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.stock_basic_ready_for_trade_date",
            return_value=_dataset_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.suspend_d_ready_for_trade_date",
            return_value=_dataset_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.check_stock_daily_source_readiness",
            return_value=_source_ready(),
        ):
            result = _raw_sensor_result(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, "2026-06-05")
        self.assertEqual(request.run_key, "raw_stock_daily_update:2026-06-05")
        self.assertEqual(request.run_config, {})
        cursor_payload = load_sensor_cursor(result.cursor)
        details = cursor_payload["details"]
        self.assertEqual(details["blocked_component"], "none")
        self.assertIn("已触发", details["summary"])
        self.assertIn("raw 全量更新", details["summary"])
        self.assertIn("raw blocking checks", details["next_action"])
        self.assertLess(len(result.cursor.encode("utf-8")), 2048)

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
            "orchestrator.defs.sensors.stock_daily_sensor.datetime",
            _FixedDateTimeAfterGap,
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.materialized_partition_keys",
        ) as materialized_mock, patch(
            "orchestrator.defs.sensors.stock_daily_sensor.stock_basic_ready_for_trade_date",
        ) as stock_basic_mock, patch(
            "orchestrator.defs.sensors.stock_daily_sensor.check_stock_daily_source_readiness",
        ) as source_mock:
            result = _raw_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("最早内部缺失日期为 2026-06-15", result.skip_reason.skip_message)
        materialized_mock.assert_not_called()
        stock_basic_mock.assert_not_called()
        source_mock.assert_not_called()
        cursor_payload = load_sensor_cursor(result.cursor)
        continuity = cursor_payload["details"]["frontier"]
        self.assertEqual(continuity["first_missing_registered_date"], "2026-06-15")
        self.assertEqual(
            cursor_payload["details"]["blocked_component"],
            "cn_a_stock_trade_days",
        )

    def test_raw_sensor_skips_when_source_not_ready(self) -> None:
        context = _FakeContext(partitions=("2026-06-05",))
        with patch(
            "orchestrator.defs.sensors.stock_daily_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.materialized_partition_keys",
            return_value=set(),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.stock_basic_ready_for_trade_date",
            return_value=_dataset_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.suspend_d_ready_for_trade_date",
            return_value=_dataset_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.check_stock_daily_source_readiness",
            return_value=_source_ready(ready=False),
        ):
            result = _raw_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("raw 缺失", result.skip_reason.skip_message)
        cursor_payload = load_sensor_cursor(result.cursor)
        details = cursor_payload["details"]
        self.assertEqual(details["blocked_component"], "tushare_daily_source")
        self.assertIn("等待 Tushare daily 源站数据", details["summary"])
        self.assertNotIn("repair_details", result.cursor)

    def test_raw_sensor_submits_missing_code_repair_for_recent_trade_date(
        self,
    ) -> None:
        context = _FakeContext(partitions=("2026-06-04", "2026-06-05"))
        locator = StockDailyMissingCodeLocatorResult(
            trade_date="2026-06-05",
            raw_file_exists=True,
            missing_codes=("000002.SZ",),
        )

        def raw_status(_instance, trade_date):  # noqa: ANN001
            return _asset_status(
                ready=trade_date == "2026-06-04",
                partition_key=trade_date,
                reason="ready" if trade_date == "2026-06-04" else "coverage failed",
            )

        with patch(
            "orchestrator.defs.sensors.stock_daily_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.materialized_partition_keys",
            return_value={"2026-06-04", "2026-06-05"},
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.raw_tushare_stock_daily_ready_for_trade_date",
            side_effect=raw_status,
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.stock_basic_ready_for_trade_date",
            return_value=_dataset_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.suspend_d_ready_for_trade_date",
            return_value=_dataset_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.check_stock_daily_source_readiness",
            return_value=_source_ready(),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.locate_stock_daily_missing_codes",
            return_value=locator,
        ):
            result = _raw_sensor_result(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, "2026-06-05")
        self.assertIn("missing_code_repair", request.run_key)
        repair_config = request.run_config["ops"]["raw_tushare_stock_daily"]["config"]
        self.assertEqual(
            repair_config["write_mode"]["missing_code_repair"]["ts_codes"],
            ["000002.SZ"],
        )
        cursor_payload = load_sensor_cursor(result.cursor)
        repair_state = cursor_payload["details"]["runtime_state"][
            "stock_daily_missing_code_repair"
        ]
        self.assertEqual(
            repair_state["dates"]["2026-06-05"]["attempt_count"],
            1,
        )
        evidence = cursor_payload["details"]["evidence"]
        self.assertEqual(evidence["repair_trade_date_count"], 1)
        self.assertEqual(evidence["first_repair_trade_date"], "2026-06-05")
        self.assertEqual(evidence["first_repair_missing_count"], 1)
        self.assertEqual(evidence["first_repair_attempt"], 1)
        self.assertNotIn("repair_details", result.cursor)
        self.assertLess(len(result.cursor.encode("utf-8")), 3072)

    def test_raw_sensor_repair_locator_only_scans_recent_two_trade_dates(self) -> None:
        context = _FakeContext(
            partitions=("2026-06-03", "2026-06-04", "2026-06-05")
        )
        locator_calls: list[str] = []

        def raw_status(_instance, trade_date):  # noqa: ANN001
            return _asset_status(
                ready=False,
                partition_key=trade_date,
                reason="coverage failed",
            )

        def locator_side_effect(*, trade_date, **_kwargs):  # noqa: ANN001
            locator_calls.append(trade_date)
            return StockDailyMissingCodeLocatorResult(
                trade_date=trade_date,
                raw_file_exists=True,
                missing_codes=(f"{trade_date[-2:]}0001.SZ",),
            )

        with patch(
            "orchestrator.defs.sensors.stock_daily_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.materialized_partition_keys",
            return_value={"2026-06-03", "2026-06-04", "2026-06-05"},
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.raw_tushare_stock_daily_ready_for_trade_date",
            side_effect=raw_status,
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.stock_basic_ready_for_trade_date",
            return_value=_dataset_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.suspend_d_ready_for_trade_date",
            return_value=_dataset_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.check_stock_daily_source_readiness",
            return_value=_source_ready(),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.locate_stock_daily_missing_codes",
            side_effect=locator_side_effect,
        ):
            result = _raw_sensor_result(context)

        self.assertEqual(locator_calls, ["2026-06-04", "2026-06-05"])
        self.assertEqual(len(result.run_requests), 2)

    def test_silver_sensor_skips_when_raw_not_ready(self) -> None:
        context = _FakeContext(partitions=("2026-06-05",))
        with patch(
            "orchestrator.defs.sensors.stock_daily_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.materialized_partition_keys",
            return_value=set(),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.stock_basic_ready_for_trade_date",
            return_value=_dataset_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.suspend_d_ready_for_trade_date",
            return_value=_dataset_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.raw_tushare_stock_daily_ready_for_trade_date",
            return_value=_asset_status(ready=False, materialized=False),
        ):
            result = _silver_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("readiness 门禁未满足", result.skip_reason.skip_message)
        cursor_payload = load_sensor_cursor(result.cursor)
        details = cursor_payload["details"]
        self.assertEqual(details["blocked_component"], "raw_tushare_stock_daily")
        self.assertIn("等待 raw_tushare_stock_daily", details["summary"])

    def test_silver_sensor_skips_registered_gap_before_materialization_scan(self) -> None:
        context = _FakeContext(partitions=("2026-06-13", "2026-06-16"))
        self.registered_gap_mock.side_effect = (
            lambda _context, evaluated_at, registered_keys: _registered_gap(
                expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
                registered_trade_dates=tuple(registered_keys),
                evaluated_at=evaluated_at,
            )
        )
        with patch(
            "orchestrator.defs.sensors.stock_daily_sensor.datetime",
            _FixedDateTimeAfterGap,
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.materialized_partition_keys",
        ) as materialized_mock, patch(
            "orchestrator.defs.sensors.stock_daily_sensor.stock_basic_ready_for_trade_date",
        ) as stock_basic_mock, patch(
            "orchestrator.defs.sensors.stock_daily_sensor.raw_tushare_stock_daily_ready_for_trade_date",
        ) as raw_readiness_mock:
            result = _silver_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("最早内部缺失日期为 2026-06-15", result.skip_reason.skip_message)
        materialized_mock.assert_not_called()
        stock_basic_mock.assert_not_called()
        raw_readiness_mock.assert_not_called()
        cursor_payload = load_sensor_cursor(result.cursor)
        continuity = cursor_payload["details"]["frontier"]
        self.assertEqual(continuity["first_missing_registered_date"], "2026-06-15")
        self.assertEqual(
            cursor_payload["details"]["blocked_component"],
            "cn_a_stock_trade_days",
        )

    def test_silver_sensor_submits_only_when_raw_ready_and_silver_missing(
        self,
    ) -> None:
        context = _FakeContext(partitions=("2026-06-05",))
        with patch(
            "orchestrator.defs.sensors.stock_daily_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.materialized_partition_keys",
            return_value=set(),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.stock_basic_ready_for_trade_date",
            return_value=_dataset_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.suspend_d_ready_for_trade_date",
            return_value=_dataset_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.raw_tushare_stock_daily_ready_for_trade_date",
            return_value=_asset_status(ready=True),
        ):
            result = _silver_sensor_result(context)

        self.assertEqual(len(result.run_requests), 1)
        self.assertEqual(
            result.run_requests[0].run_key,
            "silver_stock_daily_update:2026-06-05",
        )
        cursor_payload = load_sensor_cursor(result.cursor)
        details = cursor_payload["details"]
        self.assertEqual(details["blocked_component"], "none")
        self.assertIn("已触发", details["summary"])
        self.assertIn("silver run", details["next_action"])
        self.assertLess(len(result.cursor.encode("utf-8")), 2048)

    def test_silver_sensor_does_not_rerun_materialized_failed_check_partition(
        self,
    ) -> None:
        context = _FakeContext(partitions=("2026-06-05",))
        with patch(
            "orchestrator.defs.sensors.stock_daily_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.materialized_partition_keys",
            return_value={"2026-06-05"},
        ):
            result = _silver_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("都已经生成完成", result.skip_reason.skip_message)

    def test_raw_sensor_cursor_points_to_stock_basic_blocker(self) -> None:
        context = _FakeContext(partitions=("2026-06-05",))
        with patch(
            "orchestrator.defs.sensors.stock_daily_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.materialized_partition_keys",
            return_value=set(),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.stock_basic_ready_for_trade_date",
            return_value=_dataset_status(ready=False, reason="freshness_failed"),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.suspend_d_ready_for_trade_date",
        ) as suspend_mock, patch(
            "orchestrator.defs.sensors.stock_daily_sensor.check_stock_daily_source_readiness",
        ) as source_mock:
            result = _raw_sensor_result(context)

        suspend_mock.assert_not_called()
        source_mock.assert_not_called()
        details = load_sensor_cursor(result.cursor)["details"]
        self.assertEqual(details["blocked_component"], "stock_basic")
        self.assertIn("stock_basic 阻断", details["summary"])

    def test_silver_sensor_cursor_points_to_suspend_blocker(self) -> None:
        context = _FakeContext(partitions=("2026-06-05",))
        with patch(
            "orchestrator.defs.sensors.stock_daily_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.materialized_partition_keys",
            return_value=set(),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.stock_basic_ready_for_trade_date",
            return_value=_dataset_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.suspend_d_ready_for_trade_date",
            return_value=_dataset_status(ready=False, reason="missing_check"),
        ), patch(
            "orchestrator.defs.sensors.stock_daily_sensor.raw_tushare_stock_daily_ready_for_trade_date",
        ) as raw_readiness_mock:
            result = _silver_sensor_result(context)

        raw_readiness_mock.assert_not_called()
        details = load_sensor_cursor(result.cursor)["details"]
        self.assertEqual(details["blocked_component"], "suspend_d")
        self.assertIn("suspend_d 阻断", details["summary"])


if __name__ == "__main__":
    unittest.main()
