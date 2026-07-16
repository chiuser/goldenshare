import unittest
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
    build_registered_gap_status,
)
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.sensors.silver_index_daily_sensor import (
    silver_index_daily_sensor,
)


def _batch_status(
    trade_dates: tuple[str, ...],
    *,
    ready_dates: tuple[str, ...],
    failed_dates: tuple[str, ...] = (),
    dataset_check_name: str,
    missing_reason: str,
    failed_reason: str,
) -> ContinuityBatchReadiness:
    ready_set = set(ready_dates)
    failed_set = set(failed_dates)
    statuses = {}
    for trade_date in trade_dates:
        if trade_date in ready_set:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            )
        elif trade_date in failed_set:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=True,
                checks_passed=False,
                reason=failed_reason,
                failed_check_names=(dataset_check_name,),
            )
        else:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason=missing_reason,
                missing_check_names=(dataset_check_name,),
            )
    return ContinuityBatchReadiness(
        expected_trade_dates=trade_dates,
        statuses_by_trade_date=statuses,
        elapsed_ms=1,
        scanned_file_count=len(ready_dates) + len(failed_dates),
    )


def _raw_batch_status(
    trade_dates: tuple[str, ...],
    *,
    ready_dates: tuple[str, ...],
    failed_dates: tuple[str, ...] = (),
) -> ContinuityBatchReadiness:
    return _batch_status(
        trade_dates,
        ready_dates=ready_dates,
        failed_dates=failed_dates,
        dataset_check_name="raw_index_daily_code_coverage_check",
        missing_reason="missing_raw_index_daily_file",
        failed_reason="code_coverage_failed",
    )


def _silver_batch_status(
    trade_dates: tuple[str, ...],
    *,
    ready_dates: tuple[str, ...],
    failed_dates: tuple[str, ...] = (),
) -> ContinuityBatchReadiness:
    return _batch_status(
        trade_dates,
        ready_dates=ready_dates,
        failed_dates=failed_dates,
        dataset_check_name="silver_index_daily_registered_code_coverage_check",
        missing_reason="missing_silver_index_daily_file",
        failed_reason="silver_index_daily_checks_failed",
    )


class _FakeLakeRoot:
    def root(self):
        return Path("/fake/lake")

    def ensure_available_for_run(self):
        return None


class _FakeConnection:
    def __enter__(self):
        return object()

    def __exit__(self, *_args):
        return None


class _FakeDuckDB:
    def connect(self):
        return _FakeConnection()


class _FakeInstance:
    def __init__(
        self,
        *,
        trade_days: tuple[str, ...] = ("2026-06-01", "2026-06-02"),
        index_codes: tuple[str, ...] = ("000001.SH",),
    ):
        self.dynamic_partitions = {
            cn_a_index_trade_days.name: set(trade_days),
            cn_a_index_ts_codes.name: set(index_codes),
        }

    def get_dynamic_partitions(self, name):
        return self.dynamic_partitions[name]


class _FakeContext:
    def __init__(
        self,
        *,
        trade_days: tuple[str, ...] = ("2026-06-01", "2026-06-02"),
        index_codes: tuple[str, ...] = ("000001.SH",),
    ):
        self.instance = _FakeInstance(trade_days=trade_days, index_codes=index_codes)
        self.resources = SimpleNamespace(lake_root=_FakeLakeRoot(), duckdb=_FakeDuckDB())
        self.log = SimpleNamespace(warning=lambda *_args, **_kwargs: None)


def _registered_gap(
    *,
    expected_trade_dates: tuple[str, ...],
    registered_trade_dates: tuple[str, ...],
):
    expected_window = ContinuityExpectedDateWindow(
        expected_trade_dates=expected_trade_dates,
        min_trade_date="2000-01-01",
        max_trade_date=expected_trade_dates[-1] if expected_trade_dates else None,
        evaluated_at=datetime.now(),
        window_limit=10,
    )
    return expected_window, build_registered_gap_status(
        expected_trade_dates=expected_trade_dates,
        registered_trade_dates=registered_trade_dates,
    )


class SilverIndexDailySensorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._registered_gap_patcher = patch(
            "orchestrator.defs.sensors.silver_index_daily_sensor._index_trade_day_registered_gap",
            side_effect=lambda _context, evaluated_at, registered_trade_days: _registered_gap(
                expected_trade_dates=tuple(registered_trade_days),
                registered_trade_dates=tuple(registered_trade_days),
            ),
        )
        self.registered_gap_mock = self._registered_gap_patcher.start()

    def tearDown(self) -> None:
        self._registered_gap_patcher.stop()

    def test_registered_gap_skips_before_raw_readiness_and_silver_batch(self) -> None:
        context = _FakeContext(trade_days=("2026-06-13", "2026-06-16"))
        self.registered_gap_mock.side_effect = (
            lambda _context, evaluated_at, registered_trade_days: _registered_gap(
                expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
                registered_trade_dates=tuple(registered_trade_days),
            )
        )
        with (
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "raw_index_daily_lake_readiness_for_trade_dates",
            ) as raw_readiness,
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "batch_silver_index_daily_lake_readiness",
            ) as silver_batch,
        ):
            result = silver_index_daily_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("最早内部缺失日期为 2026-06-15", result.skip_reason.skip_message)
        raw_readiness.assert_not_called()
        silver_batch.assert_not_called()
        cursor = json.loads(result.cursor)
        self.assertEqual(
            cursor["details"]["reason_code"],
            "missing_registered_partition",
        )
        self.assertEqual(
            cursor["details"]["blocked_component"],
            "cn_a_index_trade_days",
        )
        self.assertIn("分区存在内部缺口", cursor["details"]["summary"])
        self.assertIn("cn_a_index_trade_days", cursor["details"]["next_action"])

    def test_raw_not_ready_skips_before_silver_batch(self) -> None:
        trade_dates = ("2026-06-01", "2026-06-02")
        with (
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "raw_index_daily_lake_readiness_for_trade_dates",
                return_value=_raw_batch_status(
                    trade_dates,
                    ready_dates=("2026-06-01",),
                ),
            ),
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "batch_silver_index_daily_lake_readiness",
            ) as silver_batch,
        ):
            result = silver_index_daily_sensor._raw_fn(_FakeContext())

        self.assertEqual(result.run_requests, [])
        self.assertIn("等待 raw_index_daily", result.skip_reason.skip_message)
        silver_batch.assert_not_called()
        self.assertLess(len(result.cursor), 2500)
        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["details"]["blocked_component"], "raw_index_daily")
        self.assertIn("raw_index_daily 还没有 ready", cursor["details"]["summary"])
        self.assertIn("raw_index_daily", cursor["details"]["next_action"])
        self.assertNotIn("raw_batch_status", result.cursor)
        self.assertNotIn("silver_batch_status", result.cursor)
        self.assertNotIn("status_samples", result.cursor)

    def test_raw_check_failed_does_not_submit_silver_run(self) -> None:
        trade_dates = ("2026-06-01", "2026-06-02")
        with (
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "raw_index_daily_lake_readiness_for_trade_dates",
                return_value=_raw_batch_status(
                    trade_dates,
                    ready_dates=("2026-06-01",),
                    failed_dates=("2026-06-02",),
                ),
            ),
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "batch_silver_index_daily_lake_readiness",
            ) as silver_batch,
        ):
            result = silver_index_daily_sensor._raw_fn(_FakeContext())

        self.assertEqual(result.run_requests, [])
        self.assertIn("blocking checks 未全绿", result.skip_reason.skip_message)
        silver_batch.assert_not_called()
        cursor = json.loads(result.cursor)
        self.assertEqual(
            cursor["details"]["reason_code"],
            "raw_materialized_check_failed",
        )
        self.assertEqual(cursor["details"]["blocked_component"], "raw_index_daily")
        self.assertIn("已生成但 blocking checks 未全绿", cursor["details"]["summary"])
        self.assertIn("raw_index_daily checks", cursor["details"]["next_action"])

    def test_raw_ready_and_missing_silver_submits_run(self) -> None:
        trade_dates = ("2026-06-01", "2026-06-02")
        with (
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "raw_index_daily_lake_readiness_for_trade_dates",
                return_value=_raw_batch_status(
                    trade_dates,
                    ready_dates=trade_dates,
                ),
            ),
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "batch_silver_index_daily_lake_readiness",
                return_value=_silver_batch_status(
                    trade_dates,
                    ready_dates=("2026-06-01",),
                ),
            ),
        ):
            result = silver_index_daily_sensor._raw_fn(_FakeContext())

        self.assertEqual(len(result.run_requests), 1)
        self.assertEqual(result.run_requests[0].partition_key, "2026-06-02")
        self.assertEqual(result.run_requests[0].run_key, "silver_index_daily:2026-06-02")
        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["details"]["reason_code"], "request_run")
        self.assertEqual(cursor["details"]["blocked_component"], "none")
        self.assertIn("已触发", cursor["details"]["summary"])
        self.assertIn("silver_index_daily blocking checks", cursor["details"]["next_action"])
        self.assertNotIn("raw_batch_status", result.cursor)
        self.assertNotIn("silver_batch_status", result.cursor)

    def test_all_ready_cursor_is_not_blocked(self) -> None:
        trade_dates = ("2026-06-01", "2026-06-02")
        with (
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "raw_index_daily_lake_readiness_for_trade_dates",
                return_value=_raw_batch_status(
                    trade_dates,
                    ready_dates=trade_dates,
                ),
            ),
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "batch_silver_index_daily_lake_readiness",
                return_value=_silver_batch_status(
                    trade_dates,
                    ready_dates=trade_dates,
                ),
            ),
        ):
            result = silver_index_daily_sensor._raw_fn(_FakeContext())

        self.assertEqual(result.run_requests, [])
        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["blocked_count"], 0)
        self.assertEqual(cursor["details"]["reason_code"], "all_ready")
        self.assertEqual(cursor["details"]["blocked_component"], "none")
        self.assertIn("都已 ready", cursor["details"]["summary"])
        self.assertIn("无需处理", cursor["details"]["next_action"])

    def test_failed_silver_check_status_does_not_submit_run(self) -> None:
        trade_dates = ("2026-06-01", "2026-06-02")

        with (
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "raw_index_daily_lake_readiness_for_trade_dates",
                return_value=_raw_batch_status(
                    trade_dates,
                    ready_dates=trade_dates,
                ),
            ),
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "batch_silver_index_daily_lake_readiness",
                return_value=_silver_batch_status(
                    trade_dates,
                    ready_dates=(),
                    failed_dates=("2026-06-01",),
                ),
            ),
        ):
            result = silver_index_daily_sensor._raw_fn(_FakeContext())

        self.assertEqual(result.run_requests, [])
        self.assertIn("blocking checks 未全绿", result.skip_reason.skip_message)
        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["details"]["blocked_component"], "silver_index_daily")
        self.assertIn("silver_index_daily 已生成但 blocking checks 未全绿", cursor["details"]["summary"])
        self.assertIn("silver_index_daily checks", cursor["details"]["next_action"])


if __name__ == "__main__":
    unittest.main()
