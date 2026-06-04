import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
    load_sensor_cursor,
)
from orchestrator.defs.sensors.index_daily_late_arrival_repair import (
    MAX_REPAIR_ATTEMPTS_PER_CODE_PER_DAY,
    select_index_daily_pending_code_runs,
)


CN_TZ = ZoneInfo("Asia/Shanghai")


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 4, hour, minute, tzinfo=CN_TZ)


def _cursor_with_repair_state(
    *,
    evaluated_at: datetime,
    target_trade_date: str,
    evaluation_date: str = "20260604",
    codes: dict[str, dict[str, object]],
) -> str:
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=SensorCursorDecision.REQUEST_RUNS,
        target_date=target_trade_date,
        details={
            "repair_state": {
                "target_trade_date": target_trade_date,
                "evaluation_date": evaluation_date,
                "codes": codes,
            }
        },
    )


class IndexDailyLateArrivalRepairTests(unittest.TestCase):
    def test_initial_pending_code_uses_base_run_key_and_records_backoff(self) -> None:
        evaluated_at = _dt(16)

        selection = select_index_daily_pending_code_runs(
            cursor_payload={},
            evaluated_at=evaluated_at,
            target_trade_date="2026-06-02",
            pending_codes=("000001.SH",),
            max_initial_run_requests=500,
        )

        self.assertEqual(len(selection.runs), 1)
        self.assertFalse(selection.runs[0].is_repair)
        self.assertEqual(selection.runs[0].run_key, "index_daily:2026-06-02:000001.SH")
        code_state = selection.repair_state["codes"]["000001.SH"]
        self.assertEqual(code_state["attempt"], 0)
        self.assertEqual(
            code_state["next_retry_at"],
            (evaluated_at + timedelta(minutes=15)).isoformat(),
        )

    def test_due_pending_code_uses_repair_run_key(self) -> None:
        evaluated_at = _dt(16, 20)
        cursor = _cursor_with_repair_state(
            evaluated_at=_dt(16),
            target_trade_date="2026-06-02",
            codes={
                "000001.SH": {
                    "attempt": 0,
                    "last_run_key": "index_daily:2026-06-02:000001.SH",
                    "last_launched_at": _dt(16).isoformat(),
                    "next_retry_at": _dt(16, 15).isoformat(),
                }
            },
        )

        selection = select_index_daily_pending_code_runs(
            cursor_payload=load_sensor_cursor(cursor),
            evaluated_at=evaluated_at,
            target_trade_date="2026-06-02",
            pending_codes=("000001.SH",),
            max_initial_run_requests=500,
        )

        self.assertEqual(len(selection.runs), 1)
        self.assertTrue(selection.runs[0].is_repair)
        self.assertEqual(selection.runs[0].repair_attempt, 1)
        self.assertEqual(
            selection.runs[0].run_key,
            "index_daily:2026-06-02:000001.SH:repair:20260604:1",
        )
        self.assertEqual(selection.repair_selected_count, 1)

    def test_not_due_pending_code_waits_for_backoff(self) -> None:
        cursor = _cursor_with_repair_state(
            evaluated_at=_dt(16),
            target_trade_date="2026-06-02",
            codes={
                "000001.SH": {
                    "attempt": 0,
                    "last_run_key": "index_daily:2026-06-02:000001.SH",
                    "last_launched_at": _dt(16).isoformat(),
                    "next_retry_at": _dt(16, 30).isoformat(),
                }
            },
        )

        selection = select_index_daily_pending_code_runs(
            cursor_payload=load_sensor_cursor(cursor),
            evaluated_at=_dt(16, 20),
            target_trade_date="2026-06-02",
            pending_codes=("000001.SH",),
            max_initial_run_requests=500,
        )

        self.assertEqual(selection.runs, ())
        self.assertEqual(selection.repair_waiting_count, 1)

    def test_repair_selection_is_capped_per_tick(self) -> None:
        due_codes = {
            f"{index:06d}.SH": {
                "attempt": 0,
                "last_run_key": f"index_daily:2026-06-02:{index:06d}.SH",
                "last_launched_at": _dt(16).isoformat(),
                "next_retry_at": _dt(16, 15).isoformat(),
            }
            for index in range(60)
        }
        cursor = _cursor_with_repair_state(
            evaluated_at=_dt(16),
            target_trade_date="2026-06-02",
            codes=due_codes,
        )

        selection = select_index_daily_pending_code_runs(
            cursor_payload=load_sensor_cursor(cursor),
            evaluated_at=_dt(16, 20),
            target_trade_date="2026-06-02",
            pending_codes=tuple(sorted(due_codes)),
            max_initial_run_requests=500,
        )

        self.assertEqual(len(selection.runs), 50)
        self.assertEqual(selection.repair_due_count, 60)
        self.assertEqual(selection.repair_budget_limited_count, 10)

    def test_max_attempts_exhausted_code_does_not_retry(self) -> None:
        cursor = _cursor_with_repair_state(
            evaluated_at=_dt(16),
            target_trade_date="2026-06-02",
            codes={
                "000001.SH": {
                    "attempt": MAX_REPAIR_ATTEMPTS_PER_CODE_PER_DAY,
                    "last_run_key": "index_daily:2026-06-02:000001.SH:repair:20260604:8",
                    "last_launched_at": _dt(16).isoformat(),
                    "next_retry_at": None,
                }
            },
        )

        selection = select_index_daily_pending_code_runs(
            cursor_payload=load_sensor_cursor(cursor),
            evaluated_at=_dt(18),
            target_trade_date="2026-06-02",
            pending_codes=("000001.SH",),
            max_initial_run_requests=500,
        )

        self.assertEqual(selection.runs, ())
        self.assertEqual(selection.repair_exhausted_count, 1)

    def test_attempt_budget_resets_by_evaluation_date_without_base_rerun(self) -> None:
        cursor = _cursor_with_repair_state(
            evaluated_at=datetime(2026, 6, 3, 18, tzinfo=CN_TZ),
            target_trade_date="2026-06-02",
            evaluation_date="20260603",
            codes={
                "000001.SH": {
                    "attempt": MAX_REPAIR_ATTEMPTS_PER_CODE_PER_DAY,
                    "last_run_key": "index_daily:2026-06-02:000001.SH:repair:20260603:8",
                    "last_launched_at": datetime(2026, 6, 3, 18, tzinfo=CN_TZ).isoformat(),
                    "next_retry_at": None,
                }
            },
        )

        selection = select_index_daily_pending_code_runs(
            cursor_payload=load_sensor_cursor(cursor),
            evaluated_at=_dt(16),
            target_trade_date="2026-06-02",
            pending_codes=("000001.SH",),
            max_initial_run_requests=500,
        )

        self.assertEqual(len(selection.runs), 1)
        self.assertTrue(selection.runs[0].is_repair)
        self.assertEqual(selection.runs[0].repair_attempt, 1)
        self.assertEqual(
            selection.runs[0].run_key,
            "index_daily:2026-06-02:000001.SH:repair:20260604:1",
        )


if __name__ == "__main__":
    unittest.main()
