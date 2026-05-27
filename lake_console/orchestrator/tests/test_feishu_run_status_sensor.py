import unittest

from orchestrator.defs.sensors.feishu_run_status_sensor import _trigger_value


class FeishuRunStatusSensorTests(unittest.TestCase):
    def test_trigger_value_uses_sensor_system_tag_first(self) -> None:
        self.assertEqual(
            _trigger_value(
                {
                    "dagster/sensor_name": "stock_daily_sensor",
                    "dagster/schedule_name": "daily_schedule",
                }
            ),
            "stock_daily_sensor",
        )

    def test_trigger_value_uses_schedule_system_tag(self) -> None:
        self.assertEqual(
            _trigger_value({"dagster/schedule_name": "daily_schedule"}),
            "daily_schedule",
        )

    def test_trigger_value_uses_ui_system_tag(self) -> None:
        self.assertEqual(_trigger_value({"dagster/from_ui": "true"}), "ui")

    def test_trigger_value_ignores_legacy_triggered_by(self) -> None:
        self.assertEqual(_trigger_value({"triggered_by": "legacy_sensor"}), "-")

    def test_trigger_value_defaults_to_dash(self) -> None:
        self.assertEqual(_trigger_value({}), "-")
