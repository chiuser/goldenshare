import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from orchestrator.defs.run_contracts.cursors import (
    MAX_CURSOR_SAMPLE_KEYS,
    SENSOR_CURSOR_SCHEMA_VERSION,
    SensorCursorDecision,
    build_sensor_cursor,
    load_sensor_cursor,
)
from orchestrator.defs.sensors.index_daily_sensor import (
    _cursor_payload as build_index_daily_cursor,
)
from orchestrator.defs.sensors.index_daily_sensor import _select_pending_codes


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
            details={"next_pending_offset": 2},
        )

        payload = json.loads(cursor)

        self.assertEqual(payload["schema_version"], SENSOR_CURSOR_SCHEMA_VERSION)
        self.assertEqual(payload["evaluated_at"], evaluated_at.isoformat())
        self.assertEqual(payload["decision"], "request_runs")
        self.assertEqual(payload["target_date"], "2026-05-26")
        self.assertEqual(payload["selected_count"], 2)
        self.assertEqual(payload["blocked_count"], 1)
        self.assertEqual(len(payload["sample_keys"]), MAX_CURSOR_SAMPLE_KEYS)
        self.assertEqual(payload["details"]["next_pending_offset"], 2)

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
            details={"reason": "ready"},
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

    def test_index_daily_cursor_offset_reads_only_v1_details(self) -> None:
        evaluated_at = datetime(2026, 5, 26, tzinfo=ZoneInfo("Asia/Shanghai"))
        pending_codes = ("000001.SH", "000016.SH", "000300.SH")
        versioned_cursor = build_sensor_cursor(
            evaluated_at=evaluated_at,
            decision=SensorCursorDecision.REQUEST_RUNS,
            target_date="2026-05-26",
            details={"next_pending_offset": 1},
        )

        selected_codes, next_offset = _select_pending_codes(
            cursor_payload=load_sensor_cursor(versioned_cursor),
            target_trade_date="2026-05-26",
            pending_codes=pending_codes,
        )

        self.assertEqual(selected_codes, ("000016.SH", "000300.SH", "000001.SH"))
        self.assertEqual(next_offset, 1)

        legacy_cursor = json.dumps(
            {
                "target_trade_date": "2026-05-26",
                "next_pending_offset": 1,
            }
        )
        selected_codes, next_offset = _select_pending_codes(
            cursor_payload=load_sensor_cursor(legacy_cursor),
            target_trade_date="2026-05-26",
            pending_codes=pending_codes,
        )

        self.assertEqual(selected_codes, pending_codes)
        self.assertEqual(next_offset, 0)

    def test_index_daily_cursor_writes_offset_only_in_details(self) -> None:
        evaluated_at = datetime(2026, 5, 26, tzinfo=ZoneInfo("Asia/Shanghai"))
        payload = json.loads(
            build_index_daily_cursor(
                evaluated_at=evaluated_at,
                today="2026-05-26",
                registered_trade_day_count=1,
                registered_code_count=3,
                target_trade_date="2026-05-26",
                source_ready=True,
                source_row_count=3,
                pending_count=3,
                selected_codes=("000001.SH",),
                next_pending_offset=1,
            )
        )

        self.assertNotIn("target_trade_date", payload)
        self.assertNotIn("next_pending_offset", payload)
        self.assertEqual(payload["target_date"], "2026-05-26")
        self.assertEqual(payload["details"]["next_pending_offset"], 1)


if __name__ == "__main__":
    unittest.main()
