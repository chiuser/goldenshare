import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    StkMinsBatchReadiness,
    StkMinsDateReadiness,
)
from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    GoldStkMinsQfqFactorRepairStatus,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.run_contracts.cursors import load_sensor_cursor
from orchestrator.defs.run_contracts.sensor_tags import (
    SENSOR_DOMAIN_TAG,
    SENSOR_ROLE_TAG,
    SENSOR_TARGET_LAYER_TAG,
)
from orchestrator.defs.sensors import stk_mins_qfq_nineturn_sensor as sensor_module
from orchestrator.defs.sensors.stk_mins_qfq_nineturn_sensor import (
    gold_stk_mins_qfq_nineturn_update_job_sensor,
)


EVALUATED_AT = datetime(2026, 8, 7, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
EXPECTED_DATES = ("2026-08-05", "2026-08-06", "2026-08-07")


class _FakeInstance:
    def __init__(self, partitions: tuple[str, ...]) -> None:
        self._partitions = partitions

    def get_dynamic_partitions(self, name: str) -> list[str]:
        return (
            list(self._partitions)
            if name == cn_a_stock_mins_silver_trade_days.name
            else []
        )


class _FakeDuckDB:
    class _ConnectionContext:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    def connect(self):
        return self._ConnectionContext()


class _FakeContext:
    def __init__(self, partitions: tuple[str, ...] = EXPECTED_DATES) -> None:
        self.instance = _FakeInstance(partitions)
        self.resources = SimpleNamespace(
            lake_root=SimpleNamespace(root=lambda: "/tmp/not-used"),
            duckdb=_FakeDuckDB(),
        )


def _date_status(
    trade_date: str,
    *,
    ready: bool,
    materialized: bool | None = None,
    checks_passed: bool | None = None,
    expected_file_count: int = 4,
) -> StkMinsDateReadiness:
    return StkMinsDateReadiness(
        trade_date=trade_date,
        ready=ready,
        materialized=ready if materialized is None else materialized,
        checks_passed=ready if checks_passed is None else checks_passed,
        reason="ready" if ready else "not_ready",
        failed_check_names=() if ready else ("integrity_check",),
        missing_file_paths=(),
        expected_file_count=expected_file_count,
        existing_file_count=expected_file_count if ready or materialized else 0,
    )


def _batch(
    statuses: dict[str, StkMinsDateReadiness],
    *,
    dataset: str,
    freq_count: int = 4,
) -> StkMinsBatchReadiness:
    return StkMinsBatchReadiness(
        dataset=dataset,
        expected_start_date=EXPECTED_DATES[0],
        expected_end_date=EXPECTED_DATES[-1],
        expected_count=len(statuses),
        freq_count=freq_count,
        elapsed_ms=8.0,
        statuses_by_trade_date=statuses,
    )


def _repair_status(*, ready: bool) -> GoldStkMinsQfqFactorRepairStatus:
    return GoldStkMinsQfqFactorRepairStatus(
        ready=ready,
        trade_date=EXPECTED_DATES[0],
        reason="ready" if ready else "not_ready",
        repair_required=False,
    )


class StkMinsQfqNineturnSensorTests(unittest.TestCase):
    def test_definition_is_stopped_bounded_and_tagged(self) -> None:
        sensor = gold_stk_mins_qfq_nineturn_update_job_sensor
        self.assertEqual(sensor.default_status, dg.DefaultSensorStatus.STOPPED)
        self.assertEqual(sensor.minimum_interval_seconds, 600)
        self.assertEqual(sensor.tags[SENSOR_DOMAIN_TAG], "quote_data")
        self.assertEqual(sensor.tags[SENSOR_TARGET_LAYER_TAG], "gold")
        self.assertEqual(sensor.tags[SENSOR_ROLE_TAG], "asset_update")

    def test_registered_gap_stops_before_target_readiness(self) -> None:
        target_readiness = Mock()
        context = _FakeContext((EXPECTED_DATES[0], EXPECTED_DATES[2]))
        with (
            patch.object(
                sensor_module,
                "_load_expected_trade_dates",
                return_value=EXPECTED_DATES,
            ),
            patch.object(
                sensor_module,
                "batch_gold_stk_mins_qfq_nineturn_readiness",
                target_readiness,
            ),
        ):
            result = gold_stk_mins_qfq_nineturn_update_job_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        target_readiness.assert_not_called()
        details = load_sensor_cursor(result.cursor)["details"]
        self.assertEqual(details["reason_code"], "missing_registered_partition")

    def test_target_check_failure_does_not_probe_upstream(self) -> None:
        target = _date_status(
            EXPECTED_DATES[0], ready=False, materialized=True, checks_passed=False
        )
        upstream = Mock()
        with (
            patch.object(
                sensor_module,
                "_load_expected_trade_dates",
                return_value=EXPECTED_DATES,
            ),
            patch.object(
                sensor_module,
                "batch_gold_stk_mins_qfq_nineturn_readiness",
                return_value=_batch(
                    {EXPECTED_DATES[0]: target},
                    dataset="gold_stk_mins_qfq_nineturn",
                ),
            ),
            patch.object(
                sensor_module,
                "batch_gold_stk_mins_qfq_nineturn_upstream_lake_readiness",
                upstream,
            ),
        ):
            result = gold_stk_mins_qfq_nineturn_update_job_sensor._raw_fn(
                _FakeContext()
            )

        self.assertEqual(result.run_requests, [])
        upstream.assert_not_called()
        self.assertEqual(
            load_sensor_cursor(result.cursor)["details"]["reason_code"],
            "target_check_failed",
        )

    def test_four_frequency_upstream_not_ready_blocks_repair_lookup(self) -> None:
        target = _date_status(EXPECTED_DATES[0], ready=False)
        upstream = _date_status(EXPECTED_DATES[0], ready=False)
        repair = Mock()
        with (
            patch.object(
                sensor_module,
                "_load_expected_trade_dates",
                return_value=EXPECTED_DATES,
            ),
            patch.object(
                sensor_module,
                "batch_gold_stk_mins_qfq_nineturn_readiness",
                return_value=_batch(
                    {EXPECTED_DATES[0]: target},
                    dataset="gold_stk_mins_qfq_nineturn",
                ),
            ),
            patch.object(
                sensor_module,
                "batch_gold_stk_mins_qfq_nineturn_upstream_lake_readiness",
                return_value=_batch(
                    {EXPECTED_DATES[0]: upstream},
                    dataset="gold_stk_mins_qfq_nineturn_upstream",
                ),
            ) as upstream_probe,
            patch.object(
                sensor_module,
                "gold_stk_mins_qfq_factor_repair_status",
                repair,
            ),
        ):
            result = gold_stk_mins_qfq_nineturn_update_job_sensor._raw_fn(
                _FakeContext()
            )

        self.assertEqual(result.run_requests, [])
        repair.assert_not_called()
        self.assertEqual(
            upstream_probe.call_args.kwargs["expected_trade_dates"],
            (EXPECTED_DATES[0],),
        )
        details = load_sensor_cursor(result.cursor)["details"]
        self.assertEqual(details["blocked_component"], "gold_stk_mins_qfq")

    def test_factor_repair_must_be_ready(self) -> None:
        target = _date_status(EXPECTED_DATES[0], ready=False)
        upstream = _date_status(EXPECTED_DATES[0], ready=True)
        with (
            patch.object(
                sensor_module,
                "_load_expected_trade_dates",
                return_value=EXPECTED_DATES,
            ),
            patch.object(
                sensor_module,
                "batch_gold_stk_mins_qfq_nineturn_readiness",
                return_value=_batch(
                    {EXPECTED_DATES[0]: target},
                    dataset="gold_stk_mins_qfq_nineturn",
                ),
            ),
            patch.object(
                sensor_module,
                "batch_gold_stk_mins_qfq_nineturn_upstream_lake_readiness",
                return_value=_batch(
                    {EXPECTED_DATES[0]: upstream},
                    dataset="gold_stk_mins_qfq_nineturn_upstream",
                ),
            ),
            patch.object(
                sensor_module,
                "gold_stk_mins_qfq_factor_repair_status",
                return_value=_repair_status(ready=False),
            ),
        ):
            result = gold_stk_mins_qfq_nineturn_update_job_sensor._raw_fn(
                _FakeContext()
            )

        self.assertEqual(result.run_requests, [])
        details = load_sensor_cursor(result.cursor)["details"]
        self.assertEqual(details["reason_code"], "factor_repair_not_ready")

    def test_ready_gates_submit_only_one_date_with_compact_cursor(self) -> None:
        target = _date_status(EXPECTED_DATES[0], ready=False)
        upstream = _date_status(EXPECTED_DATES[0], ready=True)
        with (
            patch.object(
                sensor_module,
                "_load_expected_trade_dates",
                return_value=EXPECTED_DATES,
            ),
            patch.object(
                sensor_module,
                "batch_gold_stk_mins_qfq_nineturn_readiness",
                return_value=_batch(
                    {EXPECTED_DATES[0]: target},
                    dataset="gold_stk_mins_qfq_nineturn",
                ),
            ),
            patch.object(
                sensor_module,
                "batch_gold_stk_mins_qfq_nineturn_upstream_lake_readiness",
                return_value=_batch(
                    {EXPECTED_DATES[0]: upstream},
                    dataset="gold_stk_mins_qfq_nineturn_upstream",
                ),
            ),
            patch.object(
                sensor_module,
                "gold_stk_mins_qfq_factor_repair_status",
                return_value=_repair_status(ready=True),
            ),
            patch.object(sensor_module, "_previous_partition_status", return_value=None),
        ):
            result = gold_stk_mins_qfq_nineturn_update_job_sensor._raw_fn(
                _FakeContext()
            )

        self.assertEqual(len(result.run_requests), 1)
        self.assertEqual(result.run_requests[0].partition_key, EXPECTED_DATES[0])
        self.assertEqual(
            result.run_requests[0].run_key,
            f"gold_stk_mins_qfq_nineturn_update:{EXPECTED_DATES[0]}",
        )
        cursor = load_sensor_cursor(result.cursor)
        self.assertEqual(cursor["details"]["reason_code"], "request_run")
        self.assertLess(len(result.cursor.encode("utf-8")), 2048)
        for forbidden in ("status_samples", "to_cursor_details", "missing_file_paths"):
            self.assertNotIn(forbidden, result.cursor)

    def test_previous_partition_must_be_ready(self) -> None:
        statuses = {
            EXPECTED_DATES[0]: _date_status(EXPECTED_DATES[0], ready=True),
            EXPECTED_DATES[1]: _date_status(EXPECTED_DATES[1], ready=False),
        }
        upstream = _date_status(EXPECTED_DATES[1], ready=True)
        with (
            patch.object(
                sensor_module,
                "_load_expected_trade_dates",
                return_value=EXPECTED_DATES,
            ),
            patch.object(
                sensor_module,
                "batch_gold_stk_mins_qfq_nineturn_readiness",
                return_value=_batch(
                    statuses,
                    dataset="gold_stk_mins_qfq_nineturn",
                ),
            ),
            patch.object(
                sensor_module,
                "batch_gold_stk_mins_qfq_nineturn_upstream_lake_readiness",
                return_value=_batch(
                    {EXPECTED_DATES[1]: upstream},
                    dataset="gold_stk_mins_qfq_nineturn_upstream",
                ),
            ),
            patch.object(
                sensor_module,
                "gold_stk_mins_qfq_factor_repair_status",
                return_value=GoldStkMinsQfqFactorRepairStatus(
                    ready=True,
                    trade_date=EXPECTED_DATES[1],
                    reason="ready",
                ),
            ),
            patch.object(
                sensor_module,
                "_previous_partition_status",
                return_value=_date_status(EXPECTED_DATES[0], ready=False),
            ),
        ):
            result = gold_stk_mins_qfq_nineturn_update_job_sensor._raw_fn(
                _FakeContext()
            )

        self.assertEqual(result.run_requests, [])
        self.assertEqual(
            load_sensor_cursor(result.cursor)["details"]["reason_code"],
            "previous_partition_not_ready",
        )

    def test_all_ready_skips_without_upstream_probe(self) -> None:
        statuses = {
            trade_date: _date_status(trade_date, ready=True)
            for trade_date in EXPECTED_DATES
        }
        upstream = Mock()
        with (
            patch.object(
                sensor_module,
                "_load_expected_trade_dates",
                return_value=EXPECTED_DATES,
            ),
            patch.object(
                sensor_module,
                "batch_gold_stk_mins_qfq_nineturn_readiness",
                return_value=_batch(
                    statuses,
                    dataset="gold_stk_mins_qfq_nineturn",
                ),
            ),
            patch.object(
                sensor_module,
                "batch_gold_stk_mins_qfq_nineturn_upstream_lake_readiness",
                upstream,
            ),
        ):
            result = gold_stk_mins_qfq_nineturn_update_job_sensor._raw_fn(
                _FakeContext()
            )

        self.assertEqual(result.run_requests, [])
        upstream.assert_not_called()
        self.assertEqual(
            load_sensor_cursor(result.cursor)["details"]["reason_code"], "all_ready"
        )


if __name__ == "__main__":
    unittest.main()
