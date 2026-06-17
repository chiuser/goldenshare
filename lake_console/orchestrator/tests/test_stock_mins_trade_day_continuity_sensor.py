import json
import unittest
from contextlib import contextmanager
from datetime import datetime, time
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

import duckdb

from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.partitions import cn_a_stock_mins_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_RAW_HISTORY_START_DATE
from orchestrator.defs.sensors.stock_mins_trade_day_sensor import (
    STOCK_MINS_TRADE_DAY_REGISTER_START,
    stock_mins_trade_day_sensor,
)


class _AfterRegisterWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 17, 18, 30, tzinfo=tz)


class _BeforeRegisterWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 17, 17, 59, tzinfo=tz)


class _LakeRoot:
    def __init__(self, root: Path) -> None:
        self._root = root

    def root(self) -> Path:
        return self._root

    def ensure_available_for_run(self) -> None:
        return None


class _DuckDBResource:
    @contextmanager
    def connect(self):
        with duckdb.connect(database=":memory:") as connection:
            yield connection


class _Log:
    def info(self, _message: str) -> None:
        return None


class _Instance:
    def __init__(self, registered_partitions: tuple[str, ...]) -> None:
        self._registered_partitions = registered_partitions

    def get_dynamic_partitions(self, _name: str) -> list[str]:
        return list(self._registered_partitions)


class _SensorContext:
    def __init__(
        self,
        *,
        lake_root: Path,
        registered_partitions: tuple[str, ...],
    ) -> None:
        self.resources = SimpleNamespace(
            lake_root=_LakeRoot(lake_root),
            duckdb=_DuckDBResource(),
        )
        self.instance = _Instance(registered_partitions)
        self.log = _Log()


def _write_calendar_parquet(lake_root: Path) -> None:
    calendar_path = silver_trade_calendar_path(lake_root)
    calendar_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (
                VALUES
                  ('SSE', true, DATE '2026-06-12'),
                  ('SSE', true, DATE '2026-06-13'),
                  ('SSE', false, DATE '2026-06-14'),
                  ('SSE', true, DATE '2026-06-15'),
                  ('SSE', true, DATE '2026-06-16'),
                  ('SSE', true, DATE '2026-06-17')
              ) AS calendar(exchange, is_open, trade_date)
            ) TO {duckdb_string(calendar_path)} (FORMAT PARQUET)
            """
        )


class StockMinsTradeDayContinuitySensorTests(unittest.TestCase):
    def test_stock_mins_trade_day_sensor_delegates_to_calendar_backed_catch_up(
        self,
    ) -> None:
        sentinel_result = object()
        with patch(
            "orchestrator.defs.sensors.stock_mins_trade_day_sensor."
            "build_trade_day_partition_registration_result",
            return_value=sentinel_result,
        ) as registration_helper:
            result = stock_mins_trade_day_sensor._raw_fn(object())

        self.assertIs(result, sentinel_result)
        kwargs = registration_helper.call_args.kwargs
        self.assertIs(kwargs["dynamic_partitions"], cn_a_stock_mins_trade_days)
        self.assertEqual(kwargs["min_trade_date"], STK_MINS_RAW_HISTORY_START_DATE)
        self.assertEqual(kwargs["partition_set_label"], "股票分钟线 raw")
        self.assertEqual(kwargs["same_day_register_start"], time(18, 0))
        self.assertEqual(STOCK_MINS_TRADE_DAY_REGISTER_START, time(18, 0))

    def test_stock_mins_trade_day_sensor_catches_up_missing_raw_trade_days(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_calendar_parquet(lake_root)
            context = _SensorContext(
                lake_root=lake_root,
                registered_partitions=("2026-06-12", "2026-06-13"),
            )

            with patch(
                "orchestrator.defs.sensors.cn_a_trade_day_sensor.datetime",
                _AfterRegisterWindowDateTime,
            ):
                result = stock_mins_trade_day_sensor._raw_fn(context)

        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["decision"], "register_partitions")
        self.assertEqual(cursor["selected_count"], 2)
        self.assertEqual(cursor["blocked_count"], 1)
        self.assertEqual(
            cursor["details"]["selected_keys"],
            ["2026-06-15", "2026-06-16"],
        )
        self.assertEqual(cursor["details"]["max_partition_keys_per_tick"], 2)
        self.assertEqual(len(result.dynamic_partitions_requests), 1)

    def test_stock_mins_trade_day_sensor_keeps_same_day_1800_window(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_calendar_parquet(lake_root)
            context = _SensorContext(
                lake_root=lake_root,
                registered_partitions=(
                    "2026-06-12",
                    "2026-06-13",
                    "2026-06-15",
                    "2026-06-16",
                ),
            )

            with patch(
                "orchestrator.defs.sensors.cn_a_trade_day_sensor.datetime",
                _BeforeRegisterWindowDateTime,
            ):
                result = stock_mins_trade_day_sensor._raw_fn(context)

        cursor = json.loads(result.cursor)
        self.assertEqual(result.dynamic_partitions_requests, [])
        self.assertIn("18:00", result.skip_reason.skip_message)
        self.assertEqual(cursor["decision"], "skip")
        self.assertEqual(cursor["details"]["selected_keys"], [])
        self.assertFalse(cursor["details"]["same_day_register_window_started"])


if __name__ == "__main__":
    unittest.main()
