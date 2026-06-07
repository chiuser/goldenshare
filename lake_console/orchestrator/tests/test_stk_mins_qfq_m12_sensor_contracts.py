from datetime import datetime
import unittest

import dagster as dg

from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_DAILY_UPDATE_JOB_NAME,
    _already_submitted_for_target_date,
    _cursor_payload,
    _run_request_for_trade_date,
    build_gold_stk_mins_qfq_macd_kdj_daily_update_decision,
    gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor,
)


PARTITION_KEY = "2026-06-05"


class StkMinsQfqM12SensorContractTests(unittest.TestCase):
    def test_daily_sensor_definition_contract(self) -> None:
        self.assertEqual(
            gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.name,
            "gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor",
        )
        self.assertEqual(
            gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.default_status,
            dg.DefaultSensorStatus.STOPPED,
        )
        self.assertIn(
            GOLD_STK_MINS_QFQ_MACD_KDJ_DAILY_UPDATE_JOB_NAME,
            gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.job_name,
        )

    def test_run_request_key_is_stable(self) -> None:
        request = _run_request_for_trade_date(PARTITION_KEY)

        self.assertEqual(
            request.run_key,
            f"gold_stk_mins_qfq_macd_kdj_daily_update:{PARTITION_KEY}",
        )
        self.assertEqual(request.partition_key, PARTITION_KEY)
        self.assertEqual(request.run_config, {})

    def test_cursor_fast_path_accepts_new_cursor_shape(self) -> None:
        decision = build_gold_stk_mins_qfq_macd_kdj_daily_update_decision(
            target_trade_date=PARTITION_KEY,
            previous_trade_date="2026-06-04",
            run_window_started=True,
            qfq_ready=True,
            previous_state_ready=True,
            target_ready=False,
        )
        cursor = _cursor_payload(
            decision=decision,
            evaluated_at=datetime(2026, 6, 5, 23, 31),
            registered_trade_day_count=1,
            already_submitted_for_trade_date=True,
        )

        self.assertTrue(_already_submitted_for_target_date(cursor, PARTITION_KEY))

    def test_cursor_fast_path_accepts_legacy_cursor_shape(self) -> None:
        legacy_cursor = build_sensor_cursor(
            evaluated_at=datetime(2026, 6, 5, 23, 31),
            decision=SensorCursorDecision.REQUEST_RUNS,
            target_date=PARTITION_KEY,
            selected_count=1,
            blocked_count=0,
            sample_keys=(PARTITION_KEY,),
            details={"reason": "legacy submitted cursor"},
        )

        self.assertTrue(_already_submitted_for_target_date(legacy_cursor, PARTITION_KEY))

    def test_cursor_fast_path_rejects_skip_cursor(self) -> None:
        skip_cursor = build_sensor_cursor(
            evaluated_at=datetime(2026, 6, 5, 23, 31),
            decision=SensorCursorDecision.SKIP,
            target_date=PARTITION_KEY,
            selected_count=0,
            blocked_count=1,
            sample_keys=(),
            details={"reason": "not ready"},
        )

        self.assertFalse(_already_submitted_for_target_date(skip_cursor, PARTITION_KEY))


if __name__ == "__main__":
    unittest.main()
