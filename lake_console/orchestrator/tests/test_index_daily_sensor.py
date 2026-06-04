import json
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.sensors.index_daily_raw_file_readiness import (
    IndexDailyRawFileReadiness,
    IndexDailyRawGapAudit,
)
from orchestrator.defs.sensors.index_daily_sensor import index_daily_sensor


CN_TZ = ZoneInfo("Asia/Shanghai")


def _ready_gap_audit_with_no_raw_history(
    trade_dates: tuple[str, ...],
) -> IndexDailyRawGapAudit:
    return IndexDailyRawGapAudit(
        trade_dates=trade_dates,
        registered_code_count=2,
        trade_date_count=len(trade_dates),
        expected_pair_count=len(trade_dates),
        ready_pair_count=len(trade_dates),
        missing_file_codes=(),
        missing_trade_date_pair_count=0,
        missing_pair_count=0,
        first_missing_trade_date=None,
        first_missing_code_count=0,
        first_missing_codes=(),
        missing_pair_samples=(),
        raw_started_code_count=1,
        no_raw_history_codes=("950228.SH",),
    )


def _gap_audit_with_middle_gap(trade_dates: tuple[str, ...]) -> IndexDailyRawGapAudit:
    return IndexDailyRawGapAudit(
        trade_dates=trade_dates,
        registered_code_count=1,
        trade_date_count=len(trade_dates),
        expected_pair_count=len(trade_dates),
        ready_pair_count=len(trade_dates) - 1,
        missing_file_codes=(),
        missing_trade_date_pair_count=1,
        missing_pair_count=1,
        first_missing_trade_date="2026-06-01",
        first_missing_code_count=1,
        first_missing_codes=("000001.SH",),
        missing_pair_samples=(("2026-06-01", "000001.SH"),),
        raw_started_code_count=1,
    )


def _missing_latest_raw_status(trade_date: str) -> IndexDailyRawFileReadiness:
    return IndexDailyRawFileReadiness(
        trade_date=trade_date,
        registered_code_count=1,
        ready_code_count=0,
        missing_file_codes=("950228.SH",),
        missing_trade_date_codes=(),
    )


class _FakeLakeRoot:
    def root(self):
        return Path("/fake/lake")

    def ensure_available_for_run(self):
        return None


class _FakeInstance:
    def __init__(self):
        self.dynamic_partitions = {
            cn_a_index_trade_days.name: {"2026-06-01", "2026-06-02"},
            cn_a_index_ts_codes.name: {"000001.SH", "950228.SH"},
        }

    def get_dynamic_partitions(self, name):
        return self.dynamic_partitions[name]


class _FakeContext:
    def __init__(self, *, cursor: str | None = None):
        self.instance = _FakeInstance()
        self.resources = SimpleNamespace(
            lake_root=_FakeLakeRoot(),
            duckdb=object(),
            tushare=object(),
        )
        self.cursor = cursor


def _fixed_datetime(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 4, hour, minute, tzinfo=CN_TZ)


def _previous_base_run_cursor(*, evaluated_at: datetime, code: str) -> str:
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=SensorCursorDecision.REQUEST_RUNS,
        target_date="2026-06-02",
        selected_count=1,
        sample_keys=(code,),
        details={
            "selected_codes": [code],
            "next_pending_offset": 0,
        },
    )


def _repair_state_cursor(
    *,
    evaluated_at: datetime,
    code: str,
    attempt: int,
    next_retry_at: datetime | None,
) -> str:
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=SensorCursorDecision.REQUEST_RUNS,
        target_date="2026-06-02",
        selected_count=1,
        sample_keys=(code,),
        details={
            "selected_codes": [code],
            "next_pending_offset": 0,
            "repair_state": {
                "target_trade_date": "2026-06-02",
                "evaluation_date": "20260604",
                "codes": {
                    code: {
                        "attempt": attempt,
                        "last_run_key": f"index_daily:2026-06-02:{code}",
                        "last_launched_at": evaluated_at.isoformat(),
                        "next_retry_at": next_retry_at.isoformat()
                        if next_retry_at
                        else None,
                    }
                },
            },
        },
    )


class IndexDailySensorTests(unittest.TestCase):
    def test_no_raw_history_uses_latest_target_presence_for_raw_update(self) -> None:
        with (
            patch(
                "orchestrator.defs.sensors.index_daily_sensor."
                "audit_index_daily_raw_gaps",
                return_value=_ready_gap_audit_with_no_raw_history(
                    ("2026-06-01", "2026-06-02")
                ),
            ),
            patch(
                "orchestrator.defs.sensors.index_daily_sensor."
                "check_index_daily_raw_files_for_trade_date",
                return_value=_missing_latest_raw_status("2026-06-02"),
            ),
            patch(
                "orchestrator.defs.sensors.index_daily_sensor."
                "check_index_daily_source_readiness",
                return_value=SimpleNamespace(is_ready=True, row_count=1),
            ),
        ):
            result = index_daily_sensor._raw_fn(_FakeContext())

        self.assertIsNone(result.skip_reason)
        self.assertEqual(len(result.run_requests), 1)
        self.assertEqual(result.run_requests[0].partition_key, "950228.SH")
        self.assertEqual(result.run_requests[0].run_key, "index_daily:2026-06-02:950228.SH")

    def test_middle_continuity_gap_is_repaired_before_latest_presence(self) -> None:
        with (
            patch(
                "orchestrator.defs.sensors.index_daily_sensor."
                "audit_index_daily_raw_gaps",
                return_value=_gap_audit_with_middle_gap(("2026-06-01", "2026-06-02")),
            ),
            patch(
                "orchestrator.defs.sensors.index_daily_sensor."
                "check_index_daily_raw_files_for_trade_date",
            ) as target_presence_check,
            patch(
                "orchestrator.defs.sensors.index_daily_sensor."
                "check_index_daily_source_readiness",
                return_value=SimpleNamespace(is_ready=True, row_count=1),
            ),
        ):
            result = index_daily_sensor._raw_fn(_FakeContext())

        self.assertIsNone(result.skip_reason)
        self.assertEqual(len(result.run_requests), 1)
        self.assertEqual(result.run_requests[0].partition_key, "000001.SH")
        self.assertEqual(result.run_requests[0].run_key, "index_daily:2026-06-01:000001.SH")
        target_presence_check.assert_not_called()

    def test_due_late_arrival_uses_repair_run_key(self) -> None:
        cursor = _previous_base_run_cursor(
            evaluated_at=_fixed_datetime(16),
            code="950228.SH",
        )
        with (
            patch(
                "orchestrator.defs.sensors.index_daily_sensor.datetime"
            ) as patched_datetime,
            patch(
                "orchestrator.defs.sensors.index_daily_sensor."
                "audit_index_daily_raw_gaps",
                return_value=_ready_gap_audit_with_no_raw_history(
                    ("2026-06-01", "2026-06-02")
                ),
            ),
            patch(
                "orchestrator.defs.sensors.index_daily_sensor."
                "check_index_daily_raw_files_for_trade_date",
                return_value=_missing_latest_raw_status("2026-06-02"),
            ),
            patch(
                "orchestrator.defs.sensors.index_daily_sensor."
                "check_index_daily_source_readiness",
                return_value=SimpleNamespace(is_ready=True, row_count=1),
            ),
        ):
            patched_datetime.now.return_value = _fixed_datetime(16, 20)
            result = index_daily_sensor._raw_fn(_FakeContext(cursor=cursor))

        self.assertIsNone(result.skip_reason)
        self.assertEqual(len(result.run_requests), 1)
        self.assertEqual(result.run_requests[0].partition_key, "950228.SH")
        self.assertEqual(
            result.run_requests[0].run_key,
            "index_daily:2026-06-02:950228.SH:repair:20260604:1",
        )
        cursor_payload = json.loads(result.cursor)
        self.assertEqual(cursor_payload["details"]["repair_selected_count"], 1)

    def test_late_arrival_waits_until_backoff_is_due(self) -> None:
        cursor = _repair_state_cursor(
            evaluated_at=_fixed_datetime(16, 10),
            code="950228.SH",
            attempt=0,
            next_retry_at=_fixed_datetime(16, 25),
        )
        with (
            patch(
                "orchestrator.defs.sensors.index_daily_sensor.datetime"
            ) as patched_datetime,
            patch(
                "orchestrator.defs.sensors.index_daily_sensor."
                "audit_index_daily_raw_gaps",
                return_value=_ready_gap_audit_with_no_raw_history(
                    ("2026-06-01", "2026-06-02")
                ),
            ),
            patch(
                "orchestrator.defs.sensors.index_daily_sensor."
                "check_index_daily_raw_files_for_trade_date",
                return_value=_missing_latest_raw_status("2026-06-02"),
            ),
            patch(
                "orchestrator.defs.sensors.index_daily_sensor."
                "check_index_daily_source_readiness",
                return_value=SimpleNamespace(is_ready=True, row_count=1),
            ),
        ):
            patched_datetime.now.return_value = _fixed_datetime(16, 20)
            result = index_daily_sensor._raw_fn(_FakeContext(cursor=cursor))

        self.assertEqual(result.run_requests, [])
        self.assertEqual(
            result.skip_reason.skip_message,
            "指数日线 raw 缺失代码尚未到达补缺 backoff 时间。",
        )
        cursor_payload = json.loads(result.cursor)
        self.assertEqual(cursor_payload["details"]["repair_waiting_count"], 1)

    def test_source_not_ready_does_not_launch_due_repair(self) -> None:
        cursor = _repair_state_cursor(
            evaluated_at=_fixed_datetime(16),
            code="950228.SH",
            attempt=0,
            next_retry_at=_fixed_datetime(16, 15),
        )
        with (
            patch(
                "orchestrator.defs.sensors.index_daily_sensor.datetime"
            ) as patched_datetime,
            patch(
                "orchestrator.defs.sensors.index_daily_sensor."
                "audit_index_daily_raw_gaps",
                return_value=_ready_gap_audit_with_no_raw_history(
                    ("2026-06-01", "2026-06-02")
                ),
            ),
            patch(
                "orchestrator.defs.sensors.index_daily_sensor."
                "check_index_daily_raw_files_for_trade_date",
                return_value=_missing_latest_raw_status("2026-06-02"),
            ),
            patch(
                "orchestrator.defs.sensors.index_daily_sensor."
                "check_index_daily_source_readiness",
                return_value=SimpleNamespace(is_ready=False, row_count=0),
            ),
        ):
            patched_datetime.now.return_value = _fixed_datetime(16, 20)
            result = index_daily_sensor._raw_fn(_FakeContext(cursor=cursor))

        self.assertEqual(result.run_requests, [])
        self.assertEqual(
            result.skip_reason.skip_message,
            "Tushare 指数日线源站还没有返回有效数据。",
        )
        cursor_payload = json.loads(result.cursor)
        self.assertEqual(cursor_payload["details"]["repair_due_count"], 1)
        self.assertEqual(cursor_payload["details"]["repair_selected_count"], 0)


if __name__ == "__main__":
    unittest.main()
