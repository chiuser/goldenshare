import inspect
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityExpectedDateWindow,
)
from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    StkMinsBatchReadiness,
    StkMinsDateReadiness,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.run_contracts.cursors import load_sensor_cursor
from orchestrator.defs.run_contracts.sensor_tags import (
    SENSOR_DOMAIN_TAG,
    SENSOR_ROLE_TAG,
    SENSOR_TARGET_LAYER_TAG,
)
from orchestrator.defs.sensors import stock_daily_qfq_nineturn_sensor as sensor_module
from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    DatasetReadinessStatus,
)
from orchestrator.defs.sensors.stock_daily_qfq_nineturn_sensor import (
    gold_stock_daily_qfq_nineturn_update_job_sensor,
)

EVALUATED_AT = datetime(2026, 8, 7, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
EXPECTED_DATES = ("2026-08-05", "2026-08-06", "2026-08-07")


class _FakeInstance:
    def __init__(self, partitions: tuple[str, ...]) -> None:
        self._partitions = partitions

    def get_dynamic_partitions(self, name: str) -> list[str]:
        return list(self._partitions) if name == cn_a_stock_trade_days.name else []


class _FakeContext:
    def __init__(self, partitions: tuple[str, ...] = EXPECTED_DATES) -> None:
        self.instance = _FakeInstance(partitions)
        self.resources = SimpleNamespace(
            lake_root=SimpleNamespace(root=lambda: "/tmp/not-used"),
            duckdb=_FakeDuckDB(),
        )


class _FakeDuckDB:
    class _ConnectionContext:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    def connect(self):
        return self._ConnectionContext()


def _window() -> ContinuityExpectedDateWindow:
    return ContinuityExpectedDateWindow(
        expected_trade_dates=EXPECTED_DATES,
        min_trade_date=EXPECTED_DATES[0],
        max_trade_date=EXPECTED_DATES[-1],
        evaluated_at=EVALUATED_AT,
        window_limit=10,
    )


def _date_status(
    trade_date: str,
    *,
    ready: bool,
    materialized: bool | None = None,
    checks_passed: bool | None = None,
) -> StkMinsDateReadiness:
    return StkMinsDateReadiness(
        trade_date=trade_date,
        ready=ready,
        materialized=ready if materialized is None else materialized,
        checks_passed=ready if checks_passed is None else checks_passed,
        reason="ready" if ready else "not_ready",
        failed_check_names=() if ready else ("integrity_check",),
        missing_file_paths=(),
        expected_file_count=1,
        existing_file_count=1 if ready or materialized else 0,
    )


def _batch(
    statuses: dict[str, StkMinsDateReadiness],
) -> StkMinsBatchReadiness:
    return StkMinsBatchReadiness(
        dataset="gold_stock_daily_qfq_nineturn",
        expected_start_date=EXPECTED_DATES[0],
        expected_end_date=EXPECTED_DATES[-1],
        expected_count=len(EXPECTED_DATES),
        freq_count=1,
        elapsed_ms=3.5,
        statuses_by_trade_date=statuses,
    )


def _upstream_status(trade_date: str, *, ready: bool) -> DatasetReadinessStatus:
    return DatasetReadinessStatus(
        ready=ready,
        statuses=(
            AssetReadinessStatus(
                asset_key="gold_stock_daily_qfq",
                partition_key=trade_date,
                ready=ready,
                materialized=ready,
                checks_passed=ready,
                freshness_passed=ready,
                materialization_storage_id=1 if ready else None,
                materialization_date=trade_date if ready else None,
                missing_check_names=() if ready else ("contract_check",),
                failed_check_names=(),
                reason="ready" if ready else "not_ready",
            ),
        ),
    )


class StockDailyQfqNineturnSensorTests(unittest.TestCase):
    def test_definition_is_stopped_bounded_and_tagged(self) -> None:
        sensor = gold_stock_daily_qfq_nineturn_update_job_sensor
        self.assertEqual(sensor.default_status, dg.DefaultSensorStatus.STOPPED)
        self.assertEqual(sensor.minimum_interval_seconds, 600)
        self.assertEqual(sensor.tags[SENSOR_DOMAIN_TAG], "quote_data")
        self.assertEqual(sensor.tags[SENSOR_TARGET_LAYER_TAG], "gold")
        self.assertEqual(sensor.tags[SENSOR_ROLE_TAG], "asset_update")

    def test_registered_gap_stops_before_target_readiness(self) -> None:
        target_readiness = Mock()
        context = _FakeContext((EXPECTED_DATES[0], EXPECTED_DATES[2]))
        with (
            patch.object(sensor_module, "_load_expected_window", return_value=_window()),
            patch.object(
                sensor_module,
                "batch_gold_stock_daily_qfq_nineturn_readiness",
                target_readiness,
            ),
        ):
            result = gold_stock_daily_qfq_nineturn_update_job_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        target_readiness.assert_not_called()
        details = load_sensor_cursor(result.cursor)["details"]
        self.assertEqual(details["reason_code"], "missing_registered_partition")
        self.assertEqual(details["blocked_component"], cn_a_stock_trade_days.name)

    def test_materialized_failed_target_does_not_auto_rerun(self) -> None:
        failed = _date_status(
            EXPECTED_DATES[0], ready=False, materialized=True, checks_passed=False
        )
        upstream = Mock()
        with (
            patch.object(sensor_module, "_load_expected_window", return_value=_window()),
            patch.object(
                sensor_module,
                "batch_gold_stock_daily_qfq_nineturn_readiness",
                return_value=_batch({EXPECTED_DATES[0]: failed}),
            ),
            patch.object(
                sensor_module,
                "partition_dataset_readiness_status_from_latest_checks",
                upstream,
            ),
        ):
            result = gold_stock_daily_qfq_nineturn_update_job_sensor._raw_fn(
                _FakeContext()
            )

        self.assertEqual(result.run_requests, [])
        upstream.assert_not_called()
        details = load_sensor_cursor(result.cursor)["details"]
        self.assertEqual(details["reason_code"], "target_check_failed")

    def test_upstream_not_ready_blocks_before_previous_partition_lookup(self) -> None:
        previous_partition_status = Mock()
        target = _date_status(EXPECTED_DATES[0], ready=False)
        with (
            patch.object(sensor_module, "_load_expected_window", return_value=_window()),
            patch.object(
                sensor_module,
                "batch_gold_stock_daily_qfq_nineturn_readiness",
                return_value=_batch({EXPECTED_DATES[0]: target}),
            ),
            patch.object(
                sensor_module,
                "partition_dataset_readiness_status_from_latest_checks",
                return_value=_upstream_status(EXPECTED_DATES[0], ready=False),
            ),
            patch.object(
                sensor_module,
                "_previous_partition_status",
                previous_partition_status,
            ),
        ):
            result = gold_stock_daily_qfq_nineturn_update_job_sensor._raw_fn(
                _FakeContext()
            )

        self.assertEqual(result.run_requests, [])
        previous_partition_status.assert_not_called()
        details = load_sensor_cursor(result.cursor)["details"]
        self.assertEqual(details["blocked_component"], "gold_stock_daily_qfq")

    def test_ready_upstream_submits_one_run_without_factor_repair_dependency(
        self,
    ) -> None:
        target = _date_status(EXPECTED_DATES[0], ready=False)
        with (
            patch.object(sensor_module, "_load_expected_window", return_value=_window()),
            patch.object(
                sensor_module,
                "batch_gold_stock_daily_qfq_nineturn_readiness",
                return_value=_batch({EXPECTED_DATES[0]: target}),
            ),
            patch.object(
                sensor_module,
                "partition_dataset_readiness_status_from_latest_checks",
                return_value=_upstream_status(EXPECTED_DATES[0], ready=True),
            ),
            patch.object(sensor_module, "_previous_partition_status", return_value=None),
        ):
            result = gold_stock_daily_qfq_nineturn_update_job_sensor._raw_fn(
                _FakeContext()
            )

        self.assertEqual(len(result.run_requests), 1)
        self.assertEqual(result.run_requests[0].partition_key, EXPECTED_DATES[0])
        self.assertEqual(
            result.run_requests[0].run_key,
            f"gold_stock_daily_qfq_nineturn_update:{EXPECTED_DATES[0]}",
        )
        cursor = load_sensor_cursor(result.cursor)
        self.assertEqual(cursor["details"]["reason_code"], "request_run")
        self.assertLess(len(result.cursor.encode("utf-8")), 2048)
        for forbidden in (
            "status_samples",
            "to_cursor_details",
            "repair_required",
            "factor_repair",
        ):
            self.assertNotIn(forbidden, result.cursor)

    def test_sensor_source_has_no_factor_repair_dependency(self) -> None:
        source = inspect.getsource(sensor_module)
        for forbidden in (
            "stock_daily_qfq_factor_repair",
            "silver_adj_factor",
            "factor_repair",
            "_repair_plan",
            "repair_required",
        ):
            self.assertNotIn(forbidden, source)

    def test_previous_partition_must_be_ready(self) -> None:
        statuses = {
            EXPECTED_DATES[0]: _date_status(EXPECTED_DATES[0], ready=True),
            EXPECTED_DATES[1]: _date_status(EXPECTED_DATES[1], ready=False),
        }
        with (
            patch.object(sensor_module, "_load_expected_window", return_value=_window()),
            patch.object(
                sensor_module,
                "batch_gold_stock_daily_qfq_nineturn_readiness",
                return_value=_batch(statuses),
            ),
            patch.object(
                sensor_module,
                "partition_dataset_readiness_status_from_latest_checks",
                return_value=_upstream_status(EXPECTED_DATES[1], ready=True),
            ),
            patch.object(
                sensor_module,
                "_previous_partition_status",
                return_value=_date_status(EXPECTED_DATES[0], ready=False),
            ),
        ):
            result = gold_stock_daily_qfq_nineturn_update_job_sensor._raw_fn(
                _FakeContext()
            )

        self.assertEqual(result.run_requests, [])
        details = load_sensor_cursor(result.cursor)["details"]
        self.assertEqual(details["reason_code"], "previous_partition_not_ready")

    def test_all_ready_skips_without_upstream_queries(self) -> None:
        statuses = {
            trade_date: _date_status(trade_date, ready=True)
            for trade_date in EXPECTED_DATES
        }
        upstream = Mock()
        with (
            patch.object(sensor_module, "_load_expected_window", return_value=_window()),
            patch.object(
                sensor_module,
                "batch_gold_stock_daily_qfq_nineturn_readiness",
                return_value=_batch(statuses),
            ),
            patch.object(
                sensor_module,
                "partition_dataset_readiness_status_from_latest_checks",
                upstream,
            ),
        ):
            result = gold_stock_daily_qfq_nineturn_update_job_sensor._raw_fn(
                _FakeContext()
            )

        self.assertEqual(result.run_requests, [])
        upstream.assert_not_called()
        self.assertEqual(
            load_sensor_cursor(result.cursor)["details"]["reason_code"], "all_ready"
        )


if __name__ == "__main__":
    unittest.main()
