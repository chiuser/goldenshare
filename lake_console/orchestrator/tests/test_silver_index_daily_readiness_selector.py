import unittest
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator.defs.sensors.readiness import (
    CHECK_HISTORY_LIMIT,
    SILVER_INDEX_DAILY_BLOCKING_CHECKS,
    SILVER_INDEX_DAILY_READINESS_WINDOW_LIMIT,
    select_first_not_ready_silver_index_daily_partition,
)


TERMINAL_STATUS_VALUES = {"SUCCEEDED", "FAILED"}


class _FakeEventLogStorage:
    def __init__(self, records_by_check_name):
        self.records_by_check_name = records_by_check_name
        self.calls = []

    def get_asset_check_execution_history(self, check_key, *, limit, status=None):
        status_values = (
            tuple(sorted(record_status.value for record_status in status))
            if status
            else ()
        )
        self.calls.append((check_key.name, limit, status_values))
        return self.records_by_check_name[check_key.name]


class _FakeInstance:
    def __init__(self, *, materialized_trade_dates, event_log_storage):
        self.materialized_trade_dates = set(materialized_trade_dates)
        self.event_log_storage = event_log_storage

    def get_materialized_partitions(self, _asset_key):
        return self.materialized_trade_dates


def _materialization(storage_id: int, timestamp: float = 1_782_912_000.0):
    return SimpleNamespace(storage_id=storage_id, timestamp=timestamp)


def _check_record(storage_id: int, *, passed: bool = True, blocking: bool = True):
    return SimpleNamespace(
        status=SimpleNamespace(value="SUCCEEDED" if passed else "FAILED"),
        event=SimpleNamespace(
            dagster_event=SimpleNamespace(
                event_specific_data=SimpleNamespace(
                    target_materialization_data=SimpleNamespace(storage_id=storage_id),
                    blocking=blocking,
                    passed=passed,
                )
            )
        ),
    )


def _ready_records_for(storage_ids):
    return [_check_record(storage_id) for storage_id in storage_ids]


def _records_with_override(*, storage_ids, check_name, override_records):
    return {
        name: override_records if name == check_name else _ready_records_for(storage_ids)
        for name in SILVER_INDEX_DAILY_BLOCKING_CHECKS
    }


class SilverIndexDailyReadinessSelectorTests(unittest.TestCase):
    def test_first_day_missing_materialization_does_not_scan_check_history(self) -> None:
        event_log_storage = _FakeEventLogStorage({})
        instance = _FakeInstance(
            materialized_trade_dates={"2026-06-02"},
            event_log_storage=event_log_storage,
        )

        trade_date, status = select_first_not_ready_silver_index_daily_partition(
            instance,
            ("2026-06-01", "2026-06-02"),
        )

        self.assertEqual(trade_date, "2026-06-01")
        self.assertIsNotNone(status)
        self.assertFalse(status.materialized)
        self.assertEqual(event_log_storage.calls, [])

    def test_failed_check_before_missing_materialization_wins(self) -> None:
        trade_dates = ("2026-06-01", "2026-06-02", "2026-06-03")
        materializations = {
            "2026-06-01": _materialization(1),
            "2026-06-02": _materialization(2),
        }
        failed_check_name = SILVER_INDEX_DAILY_BLOCKING_CHECKS[0]
        event_log_storage = _FakeEventLogStorage(
            _records_with_override(
                storage_ids=(2, 1),
                check_name=failed_check_name,
                override_records=[_check_record(2, passed=False), _check_record(1)],
            )
        )
        instance = _FakeInstance(
            materialized_trade_dates={"2026-06-01", "2026-06-02"},
            event_log_storage=event_log_storage,
        )

        with patch(
            "orchestrator.defs.sensors.readiness._latest_materialization_record",
            lambda _instance, _asset_key, partition_key: materializations[
                partition_key
            ],
        ):
            trade_date, status = select_first_not_ready_silver_index_daily_partition(
                instance,
                trade_dates,
            )

        self.assertEqual(trade_date, "2026-06-02")
        self.assertIsNotNone(status)
        self.assertTrue(status.materialized)
        self.assertEqual(status.failed_check_names, (failed_check_name,))
        self.assertEqual(
            len(event_log_storage.calls),
            len(SILVER_INDEX_DAILY_BLOCKING_CHECKS),
        )

    def test_all_ready_window_scans_each_check_once(self) -> None:
        trade_dates = tuple(f"2026-06-{day:02d}" for day in range(1, 11))
        materializations = {
            trade_date: _materialization(index)
            for index, trade_date in enumerate(trade_dates, start=1)
        }
        storage_ids_newest_first = tuple(reversed(range(1, 11)))
        event_log_storage = _FakeEventLogStorage(
            {
                check_name: _ready_records_for(storage_ids_newest_first)
                for check_name in SILVER_INDEX_DAILY_BLOCKING_CHECKS
            }
        )
        instance = _FakeInstance(
            materialized_trade_dates=set(trade_dates),
            event_log_storage=event_log_storage,
        )

        with patch(
            "orchestrator.defs.sensors.readiness._latest_materialization_record",
            lambda _instance, _asset_key, partition_key: materializations[
                partition_key
            ],
        ):
            trade_date, status = select_first_not_ready_silver_index_daily_partition(
                instance,
                trade_dates,
            )

        self.assertIsNone(trade_date)
        self.assertIsNone(status)
        self.assertEqual(
            event_log_storage.calls,
            [
                (check_name, CHECK_HISTORY_LIMIT, tuple(sorted(TERMINAL_STATUS_VALUES)))
                for check_name in SILVER_INDEX_DAILY_BLOCKING_CHECKS
            ],
        )

    def test_non_blocking_check_event_is_failed(self) -> None:
        trade_date = "2026-06-01"
        materializations = {trade_date: _materialization(1)}
        check_name = SILVER_INDEX_DAILY_BLOCKING_CHECKS[0]
        event_log_storage = _FakeEventLogStorage(
            _records_with_override(
                storage_ids=(1,),
                check_name=check_name,
                override_records=[_check_record(1, passed=True, blocking=False)],
            )
        )
        instance = _FakeInstance(
            materialized_trade_dates={trade_date},
            event_log_storage=event_log_storage,
        )

        with patch(
            "orchestrator.defs.sensors.readiness._latest_materialization_record",
            lambda _instance, _asset_key, partition_key: materializations[
                partition_key
            ],
        ):
            selected_trade_date, status = (
                select_first_not_ready_silver_index_daily_partition(
                    instance,
                    (trade_date,),
                )
            )

        self.assertEqual(selected_trade_date, trade_date)
        self.assertIsNotNone(status)
        self.assertEqual(status.failed_check_names, (check_name,))

    def test_latest_check_event_for_materialization_wins(self) -> None:
        trade_date = "2026-06-01"
        materializations = {trade_date: _materialization(1)}
        check_name = SILVER_INDEX_DAILY_BLOCKING_CHECKS[0]
        event_log_storage = _FakeEventLogStorage(
            _records_with_override(
                storage_ids=(1,),
                check_name=check_name,
                override_records=[
                    _check_record(1, passed=True),
                    _check_record(1, passed=False),
                ],
            )
        )
        instance = _FakeInstance(
            materialized_trade_dates={trade_date},
            event_log_storage=event_log_storage,
        )

        with patch(
            "orchestrator.defs.sensors.readiness._latest_materialization_record",
            lambda _instance, _asset_key, partition_key: materializations[
                partition_key
            ],
        ):
            selected_trade_date, status = (
                select_first_not_ready_silver_index_daily_partition(
                    instance,
                    (trade_date,),
                )
            )

        self.assertIsNone(selected_trade_date)
        self.assertIsNone(status)

    def test_missing_latest_materialization_check_result_fails_closed(self) -> None:
        trade_date = "2026-06-01"
        materializations = {trade_date: _materialization(1)}
        missing_check_name = SILVER_INDEX_DAILY_BLOCKING_CHECKS[0]
        event_log_storage = _FakeEventLogStorage(
            _records_with_override(
                storage_ids=(1,),
                check_name=missing_check_name,
                override_records=[_check_record(999)],
            )
        )
        instance = _FakeInstance(
            materialized_trade_dates={trade_date},
            event_log_storage=event_log_storage,
        )

        with patch(
            "orchestrator.defs.sensors.readiness._latest_materialization_record",
            lambda _instance, _asset_key, partition_key: materializations[
                partition_key
            ],
        ):
            selected_trade_date, status = (
                select_first_not_ready_silver_index_daily_partition(
                    instance,
                    (trade_date,),
                )
            )

        self.assertEqual(selected_trade_date, trade_date)
        self.assertIsNotNone(status)
        self.assertEqual(status.missing_check_names, (missing_check_name,))
        self.assertIn("missing within latest check history window", status.reason)

    def test_selector_rejects_history_sized_windows(self) -> None:
        trade_dates = tuple(
            f"2026-06-{index:02d}"
            for index in range(1, SILVER_INDEX_DAILY_READINESS_WINDOW_LIMIT + 2)
        )
        instance = _FakeInstance(
            materialized_trade_dates=set(),
            event_log_storage=_FakeEventLogStorage({}),
        )

        with self.assertRaises(ValueError):
            select_first_not_ready_silver_index_daily_partition(instance, trade_dates)


if __name__ == "__main__":
    unittest.main()
