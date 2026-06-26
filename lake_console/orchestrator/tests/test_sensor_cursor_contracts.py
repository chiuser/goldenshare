import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from orchestrator.defs.run_contracts.cursors import (
    MAX_CURSOR_SAMPLE_KEYS,
    MAX_SENSOR_CURSOR_BYTES,
    SENSOR_CURSOR_SCHEMA_VERSION,
    SensorCursorDecision,
    build_sensor_cursor,
    load_sensor_cursor,
)


class SensorCursorContractTests(unittest.TestCase):
    def test_build_sensor_cursor_writes_versioned_top_level_fields(self) -> None:
        evaluated_at = datetime(2026, 5, 26, 16, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
        cursor = build_sensor_cursor(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.REQUEST_RUNS,
            target_date="2026-05-26",
            selected_count=2,
            blocked_count=1,
            sample_keys=tuple(str(index) for index in range(25)),
            details={
                "reason_code": "request_run",
                "summary": "已触发：提交 2 个分区。",
                "next_action": "等待本次 run 完成。",
                "runtime_state": {"next_pending_offset": 2},
            },
        )

        payload = json.loads(cursor)

        self.assertEqual(payload["schema_version"], SENSOR_CURSOR_SCHEMA_VERSION)
        self.assertEqual(payload["evaluated_at"], evaluated_at.isoformat())
        self.assertEqual(payload["decision"], "request_runs")
        self.assertEqual(payload["target_date"], "2026-05-26")
        self.assertEqual(payload["selected_count"], 2)
        self.assertEqual(payload["blocked_count"], 1)
        self.assertEqual(len(payload["sample_keys"]), MAX_CURSOR_SAMPLE_KEYS)
        self.assertEqual(payload["details"]["reason_code"], "request_run")
        self.assertEqual(payload["details"]["summary"], "已触发：提交 2 个分区。")
        self.assertEqual(payload["details"]["next_action"], "等待本次 run 完成。")
        self.assertEqual(payload["details"]["runtime_state"]["next_pending_offset"], 2)

    def test_build_sensor_cursor_rejects_negative_counts(self) -> None:
        evaluated_at = datetime(2026, 5, 26, tzinfo=ZoneInfo("Asia/Shanghai"))

        with self.assertRaisesRegex(ValueError, "selected_count must be non-negative"):
            build_sensor_cursor(
                evaluated_at=evaluated_at,
                decision=SensorCursorDecision.SKIP,
                selected_count=-1,
            )

        with self.assertRaisesRegex(ValueError, "blocked_count must be non-negative"):
            build_sensor_cursor(
                evaluated_at=evaluated_at,
                decision=SensorCursorDecision.SKIP,
                blocked_count=-1,
            )

    def test_load_sensor_cursor_accepts_only_v1_dict_payload(self) -> None:
        evaluated_at = datetime(2026, 5, 26, tzinfo=ZoneInfo("Asia/Shanghai"))
        valid_cursor = build_sensor_cursor(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            details={
                "reason": "ready",
                "summary": "未触发：当前已就绪。",
                "next_action": "等待下一次 tick。",
            },
        )

        self.assertEqual(load_sensor_cursor(None), {})
        self.assertEqual(load_sensor_cursor("not-json"), {})
        self.assertEqual(load_sensor_cursor("[1, 2, 3]"), {})
        self.assertEqual(
            load_sensor_cursor('{"target_trade_date":"2026-05-26"}'),
            {},
        )
        self.assertEqual(
            load_sensor_cursor(
                json.dumps(
                    {
                        "schema_version": SENSOR_CURSOR_SCHEMA_VERSION,
                        "details": [],
                    }
                )
            ),
            {},
        )
        self.assertEqual(load_sensor_cursor(valid_cursor)["details"]["reason"], "ready")

    def test_build_sensor_cursor_requires_human_summary_and_next_action(self) -> None:
        evaluated_at = datetime(2026, 5, 26, tzinfo=ZoneInfo("Asia/Shanghai"))

        with self.assertRaisesRegex(ValueError, "summary and next_action"):
            build_sensor_cursor(
                evaluated_at=evaluated_at,
                decision=SensorCursorDecision.SKIP,
                details={"reason_code": "ready"},
            )

    def test_build_sensor_cursor_rejects_non_ascii_reason_values(self) -> None:
        evaluated_at = datetime(2026, 5, 26, tzinfo=ZoneInfo("Asia/Shanghai"))

        with self.assertRaisesRegex(ValueError, "details.reason must be ASCII"):
            build_sensor_cursor(
                evaluated_at=evaluated_at,
                decision=SensorCursorDecision.SKIP,
                details={
                    "reason": "中文原因",
                    "summary": "未触发：当前已就绪。",
                    "next_action": "等待下一次 tick。",
                },
            )

        with self.assertRaisesRegex(ValueError, "details.reason_code must be ASCII"):
            build_sensor_cursor(
                evaluated_at=evaluated_at,
                decision=SensorCursorDecision.SKIP,
                details={
                    "reason_code": "中文原因",
                    "summary": "未触发：当前已就绪。",
                    "next_action": "等待下一次 tick。",
                },
            )

        cursor = build_sensor_cursor(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.SKIP,
            details={
                "reason_code": "run_window_not_started",
                "summary": "未触发：运行窗口未开始。",
                "next_action": "等到运行窗口后自动重试。",
            },
        )
        self.assertEqual(
            load_sensor_cursor(cursor)["details"]["reason_code"],
            "run_window_not_started",
        )

    def test_build_sensor_cursor_rejects_report_style_details(self) -> None:
        evaluated_at = datetime(2026, 5, 26, tzinfo=ZoneInfo("Asia/Shanghai"))

        for forbidden_key in (
            "status_samples",
            "readiness_details",
            "raw_batch_status",
            "upstream_batch_statuses",
            "batch_status",
        ):
            with self.subTest(forbidden_key=forbidden_key):
                with self.assertRaisesRegex(ValueError, "not allowed"):
                    build_sensor_cursor(
                        evaluated_at=evaluated_at,
                        decision=SensorCursorDecision.SKIP,
                        details={
                            "summary": "未触发：测试。",
                            "next_action": "查看 asset check metadata。",
                            "evidence": {forbidden_key: []},
                        },
                    )

    def test_build_sensor_cursor_enforces_hard_size_cap(self) -> None:
        evaluated_at = datetime(2026, 5, 26, tzinfo=ZoneInfo("Asia/Shanghai"))

        with self.assertRaisesRegex(ValueError, str(MAX_SENSOR_CURSOR_BYTES)):
            build_sensor_cursor(
                evaluated_at=evaluated_at,
                decision=SensorCursorDecision.SKIP,
                details={
                    "summary": "未触发：测试。",
                    "next_action": "查看 asset check metadata。",
                    "evidence": {"large": "x" * (MAX_SENSOR_CURSOR_BYTES + 1)},
                },
            )

if __name__ == "__main__":
    unittest.main()
