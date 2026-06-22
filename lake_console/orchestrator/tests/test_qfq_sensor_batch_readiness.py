import unittest
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import dagster as dg
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)

from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    partition_dataset_readiness_status_from_latest_checks,
)


PARTITION_KEY = "2026-05-29"
ASSET_KEY = dg.AssetKey("gold_stk_mins_qfq_90m")
CHECK_NAMES = (
    "gold_stk_mins_qfq_file_exists_and_row_count_positive",
    "gold_stk_mins_qfq_derived_formula_matches_source",
)
SPEC = AssetReadinessSpec(ASSET_KEY, CHECK_NAMES)


class _FakeFetchResult:
    def __init__(self, records):
        self.records = records


class _FakeMaterializationRecord:
    def __init__(self, storage_id: int):
        self.storage_id = storage_id
        self.timestamp = datetime(
            2026,
            5,
            29,
            23,
            0,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ).timestamp()


class _FakeEventLogStorage:
    def __init__(self, records_by_check_key):
        self.records_by_check_key = records_by_check_key
        self.latest_call_count = 0
        self.history_call_count = 0
        self.latest_check_keys = ()
        self.partition_filter_key = None

    def get_latest_asset_check_execution_by_key(
        self,
        check_keys,
        *,
        partition_filter=None,
    ):
        self.latest_call_count += 1
        self.latest_check_keys = tuple(check_keys)
        self.partition_filter_key = getattr(partition_filter, "key", None)
        records_by_key = {}
        for check_key in check_keys:
            record_or_records = self.records_by_check_key.get(check_key)
            if record_or_records is None:
                continue
            records = (
                tuple(record_or_records)
                if isinstance(record_or_records, (list, tuple))
                else (record_or_records,)
            )
            for record in records:
                if (
                    partition_filter is None
                    or getattr(record, "partition", None) == self.partition_filter_key
                ):
                    records_by_key[check_key] = record
                    break
        return records_by_key

    def get_asset_check_execution_history(self, *args, **kwargs):
        self.history_call_count += 1
        raise AssertionError("batch qfq readiness must not scan check history")


class _FakeInstance:
    def __init__(self, materializations_by_asset_key, records_by_check_key):
        self.materializations_by_asset_key = materializations_by_asset_key
        self.event_log_storage = _FakeEventLogStorage(records_by_check_key)

    def fetch_materializations(self, records_filter, limit):
        self.assert_limit = limit
        materialization = self.materializations_by_asset_key.get(
            records_filter.asset_key
        )
        return _FakeFetchResult([materialization] if materialization else [])


def _check_key(check_name: str) -> dg.AssetCheckKey:
    return dg.AssetCheckKey(ASSET_KEY, check_name)


def _check_record(
    *,
    storage_id: int = 100,
    status: AssetCheckExecutionRecordStatus = AssetCheckExecutionRecordStatus.SUCCEEDED,
    passed: bool = True,
    blocking: bool = True,
    run_id: str = "",
    partition: str | None = PARTITION_KEY,
):
    target = SimpleNamespace(storage_id=storage_id)
    evaluation = SimpleNamespace(
        target_materialization_data=target,
        blocking=blocking,
        passed=passed,
    )
    dagster_event = SimpleNamespace(event_specific_data=evaluation)
    event = SimpleNamespace(dagster_event=dagster_event, run_id=run_id)
    return SimpleNamespace(status=status, event=event, partition=partition)


def _instance_with_records(records_by_check_key, *, storage_id: int = 100):
    return _FakeInstance(
        {ASSET_KEY: _FakeMaterializationRecord(storage_id)},
        records_by_check_key,
    )


class QfqSensorBatchReadinessTests(unittest.TestCase):
    def test_latest_materialization_and_latest_checks_all_green_returns_ready(self):
        instance = _instance_with_records(
            {
                _check_key(CHECK_NAMES[0]): _check_record(),
                _check_key(CHECK_NAMES[1]): _check_record(),
            }
        )

        status = partition_dataset_readiness_status_from_latest_checks(
            instance,
            (SPEC,),
            partition_key=PARTITION_KEY,
        )

        self.assertTrue(status.ready)
        self.assertEqual(instance.event_log_storage.latest_call_count, 1)
        self.assertEqual(instance.event_log_storage.history_call_count, 0)
        self.assertEqual(instance.event_log_storage.partition_filter_key, PARTITION_KEY)
        self.assertEqual(len(instance.event_log_storage.latest_check_keys), 2)

    def test_check_records_without_partition_fail_closed_for_partition_readiness(self):
        instance = _instance_with_records(
            {
                _check_key(CHECK_NAMES[0]): _check_record(partition=None),
                _check_key(CHECK_NAMES[1]): _check_record(partition=None),
            }
        )

        status = partition_dataset_readiness_status_from_latest_checks(
            instance,
            (SPEC,),
            partition_key=PARTITION_KEY,
        )

        self.assertFalse(status.ready)
        self.assertEqual(instance.event_log_storage.partition_filter_key, PARTITION_KEY)
        self.assertEqual(instance.event_log_storage.history_call_count, 0)
        self.assertEqual(status.statuses[0].missing_check_names, CHECK_NAMES)

    def test_partition_filter_prevents_later_partition_from_shadowing_target(self):
        later_partition = "2026-05-30"
        instance = _instance_with_records(
            {
                _check_key(CHECK_NAMES[0]): (
                    _check_record(storage_id=999, partition=later_partition),
                    _check_record(storage_id=100, partition=PARTITION_KEY),
                ),
                _check_key(CHECK_NAMES[1]): (
                    _check_record(storage_id=999, partition=later_partition),
                    _check_record(storage_id=100, partition=PARTITION_KEY),
                ),
            }
        )

        status = partition_dataset_readiness_status_from_latest_checks(
            instance,
            (SPEC,),
            partition_key=PARTITION_KEY,
        )

        self.assertTrue(status.ready)
        self.assertEqual(instance.event_log_storage.partition_filter_key, PARTITION_KEY)
        self.assertEqual(instance.event_log_storage.history_call_count, 0)

    def test_missing_materialization_fails_closed_without_check_lookup(self):
        instance = _FakeInstance({}, {})

        status = partition_dataset_readiness_status_from_latest_checks(
            instance,
            (SPEC,),
            partition_key=PARTITION_KEY,
        )

        self.assertFalse(status.ready)
        self.assertFalse(status.statuses[0].materialized)
        self.assertEqual(instance.event_log_storage.latest_call_count, 0)
        self.assertEqual(instance.event_log_storage.history_call_count, 0)

    def test_check_targeting_old_materialization_fails_closed(self):
        instance = _instance_with_records(
            {
                _check_key(CHECK_NAMES[0]): _check_record(storage_id=99),
                _check_key(CHECK_NAMES[1]): _check_record(storage_id=99),
            },
            storage_id=100,
        )

        status = partition_dataset_readiness_status_from_latest_checks(
            instance,
            (SPEC,),
            partition_key=PARTITION_KEY,
        )

        self.assertFalse(status.ready)
        self.assertEqual(status.statuses[0].missing_check_names, CHECK_NAMES)
        self.assertEqual(instance.event_log_storage.history_call_count, 0)

    def test_missing_failed_and_non_blocking_checks_fail_closed(self):
        failed_instance = _instance_with_records(
            {
                _check_key(CHECK_NAMES[0]): _check_record(),
                _check_key(CHECK_NAMES[1]): _check_record(
                    status=AssetCheckExecutionRecordStatus.FAILED,
                    passed=False,
                ),
            }
        )
        non_blocking_instance = _instance_with_records(
            {
                _check_key(CHECK_NAMES[0]): _check_record(),
                _check_key(CHECK_NAMES[1]): _check_record(blocking=False),
            }
        )
        missing_instance = _instance_with_records(
            {
                _check_key(CHECK_NAMES[0]): _check_record(),
            }
        )

        failed_status = partition_dataset_readiness_status_from_latest_checks(
            failed_instance,
            (SPEC,),
            partition_key=PARTITION_KEY,
        )
        non_blocking_status = partition_dataset_readiness_status_from_latest_checks(
            non_blocking_instance,
            (SPEC,),
            partition_key=PARTITION_KEY,
        )
        missing_status = partition_dataset_readiness_status_from_latest_checks(
            missing_instance,
            (SPEC,),
            partition_key=PARTITION_KEY,
        )

        self.assertFalse(failed_status.ready)
        self.assertEqual(failed_status.statuses[0].failed_check_names, (CHECK_NAMES[1],))
        self.assertFalse(non_blocking_status.ready)
        self.assertEqual(
            non_blocking_status.statuses[0].failed_check_names,
            (CHECK_NAMES[1],),
        )
        self.assertFalse(missing_status.ready)
        self.assertEqual(missing_status.statuses[0].missing_check_names, (CHECK_NAMES[1],))

    def test_runless_check_record_is_accepted_when_target_matches(self):
        instance = _instance_with_records(
            {
                _check_key(CHECK_NAMES[0]): _check_record(
                    run_id="",
                    partition=PARTITION_KEY,
                ),
                _check_key(CHECK_NAMES[1]): _check_record(
                    run_id="",
                    partition=PARTITION_KEY,
                ),
            }
        )

        status = partition_dataset_readiness_status_from_latest_checks(
            instance,
            (SPEC,),
            partition_key=PARTITION_KEY,
        )

        self.assertTrue(status.ready)
        self.assertEqual(instance.event_log_storage.history_call_count, 0)


if __name__ == "__main__":
    unittest.main()
