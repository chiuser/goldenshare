import unittest
from datetime import time
from unittest.mock import patch

from orchestrator.defs.sensors.stock_trade_day_sensor import (
    STOCK_TRADE_DAY_REGISTER_START,
    stock_trade_day_sensor,
)


class StockTradeDaySensorContractTests(unittest.TestCase):
    def test_stock_trade_day_sensor_uses_1700_same_day_registration(self) -> None:
        self.assertEqual(STOCK_TRADE_DAY_REGISTER_START, time(17, 0))

        sentinel_result = object()
        with patch(
            "orchestrator.defs.sensors.stock_trade_day_sensor.build_trade_day_partition_registration_result",
            return_value=sentinel_result,
        ) as registration_helper:
            result = stock_trade_day_sensor._raw_fn(object())

        self.assertIs(result, sentinel_result)
        kwargs = registration_helper.call_args.kwargs
        self.assertEqual(kwargs["same_day_register_start"], time(17, 0))
        self.assertEqual(kwargs["partition_set_label"], "股票资产族")


if __name__ == "__main__":
    unittest.main()
