import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from orchestrator.defs.sensors.market_major_indices_daily_sensor import (
    _cursor_payload,
    _latest_registered_trade_date,
)


class MarketMajorIndicesDailySensorTests(unittest.TestCase):
    def test_latest_registered_trade_date_selects_latest_not_after_today(self) -> None:
        evaluated_at = datetime(2026, 5, 26, 16, 5, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertEqual(
            _latest_registered_trade_date(
                ("2026-05-25", "2026-05-26", "2026-05-27"),
                evaluated_at,
            ),
            "2026-05-26",
        )

    def test_latest_registered_trade_date_returns_none_without_eligible_day(self) -> None:
        evaluated_at = datetime(2026, 5, 26, 16, 5, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertIsNone(_latest_registered_trade_date((), evaluated_at))
        self.assertIsNone(
            _latest_registered_trade_date(("2026-05-27",), evaluated_at)
        )

    def test_cursor_payload_uses_standard_sensor_cursor_contract(self) -> None:
        evaluated_at = datetime(2026, 5, 26, 16, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
        payload = json.loads(
            _cursor_payload(
                evaluated_at=evaluated_at,
                target_trade_date="2026-05-26",
                registered_trade_day_count=1,
                registered_code_count=10,
                selected_trade_date="2026-05-26",
                reason="ready",
            )
        )

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["decision"], "request_runs")
        self.assertEqual(payload["target_date"], "2026-05-26")
        self.assertEqual(payload["selected_count"], 1)
        self.assertEqual(payload["blocked_count"], 0)
        self.assertEqual(payload["sample_keys"], ["2026-05-26"])
        self.assertEqual(payload["details"]["selected_trade_date"], "2026-05-26")


if __name__ == "__main__":
    unittest.main()
