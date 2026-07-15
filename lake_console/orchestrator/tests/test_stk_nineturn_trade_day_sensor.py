import unittest
from datetime import time
from unittest.mock import patch

from dagster._core.errors import DagsterInvalidDefinitionError
from orchestrator.defs.partitions import cn_a_stk_nineturn_trade_days
from orchestrator.defs.sensors.stk_nineturn_trade_day_sensor import (
    STK_NINETURN_TRADE_DAY_REGISTER_START,
    stk_nineturn_trade_day_sensor,
)
from orchestrator.defs.stk_nineturn_contract import STK_NINETURN_HISTORY_START_DATE


class StkNineturnTradeDaySensorTests(unittest.TestCase):
    def test_sensor_delegates_only_partition_registration_to_shared_helper(self) -> None:
        sentinel_result = object()
        with patch(
            "orchestrator.defs.sensors.stk_nineturn_trade_day_sensor."
            "build_trade_day_partition_registration_result",
            return_value=sentinel_result,
        ) as registration_helper:
            result = stk_nineturn_trade_day_sensor._raw_fn(object())

        self.assertIs(result, sentinel_result)
        kwargs = registration_helper.call_args.kwargs
        self.assertIs(kwargs["dynamic_partitions"], cn_a_stk_nineturn_trade_days)
        self.assertEqual(kwargs["min_trade_date"], STK_NINETURN_HISTORY_START_DATE)
        self.assertEqual(kwargs["partition_set_label"], "神奇九转")
        self.assertEqual(kwargs["same_day_register_start"], time(17, 0))
        self.assertEqual(kwargs["sensor_name"], "stk_nineturn_trade_day_sensor")
        self.assertEqual(
            kwargs["cursor_partition_set"],
            cn_a_stk_nineturn_trade_days.name,
        )
        self.assertEqual(STK_NINETURN_TRADE_DAY_REGISTER_START, time(17, 0))

    def test_sensor_is_stopped_and_has_no_job_target(self) -> None:
        self.assertEqual(stk_nineturn_trade_day_sensor.default_status.value, "STOPPED")
        with self.assertRaises(DagsterInvalidDefinitionError):
            _ = stk_nineturn_trade_day_sensor.job_name
        self.assertEqual(stk_nineturn_trade_day_sensor.minimum_interval_seconds, 600)


if __name__ == "__main__":
    unittest.main()
