import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
    build_registered_gap_status,
)
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.prod_db.index_daily import ProdIndexDailySourceReadiness
from orchestrator.defs.sensors.raw_index_daily_update_job_sensor import (
    raw_index_daily_update_job_sensor,
)


def _raw_batch_status(
    trade_dates: tuple[str, ...],
    *,
    ready_dates: tuple[str, ...],
    failed_dates: tuple[str, ...] = (),
) -> ContinuityBatchReadiness:
    ready_set = set(ready_dates)
    failed_set = set(failed_dates)
    statuses = {}
    for trade_date in trade_dates:
        if trade_date in ready_set:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            )
        elif trade_date in failed_set:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=True,
                checks_passed=False,
                reason="file_contract_failed",
                failed_check_names=("raw_index_daily_file_contract_check",),
            )
        else:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="missing_raw_index_daily_file",
                missing_check_names=("raw_index_daily_file_contract_check",),
            )
    return ContinuityBatchReadiness(
        expected_trade_dates=trade_dates,
        statuses_by_trade_date=statuses,
        elapsed_ms=1,
        scanned_file_count=len(ready_dates) + len(failed_dates),
    )


def _source_status(*, ready: bool) -> ProdIndexDailySourceReadiness:
    return ProdIndexDailySourceReadiness(
        trade_date="2026-06-02",
        expected_code_count=2,
        expected_code_set_hash="hash",
        returned_code_count=2 if ready else 1,
        source_row_count=2 if ready else 1,
        missing_code_count=0 if ready else 1,
        extra_code_count=0,
        duplicate_key_count=0,
        null_key_count=0,
        date_mismatch_count=0,
        missing_code_samples=() if ready else ("950228.SH",),
    )


class _FakeLakeRoot:
    def root(self):
        return Path("/fake/lake")

    def ensure_available_for_run(self):
        return None


class _FakeConnection:
    def __enter__(self):
        return object()

    def __exit__(self, *_args):
        return None


class _FakeDuckDB:
    def connect(self):
        return _FakeConnection()


class _FakeInstance:
    def __init__(
        self,
        *,
        trade_days: tuple[str, ...] = ("2026-06-01", "2026-06-02"),
        index_codes: tuple[str, ...] = ("000001.SH", "950228.SH"),
    ):
        self.dynamic_partitions = {
            cn_a_index_trade_days.name: set(trade_days),
            cn_a_index_ts_codes.name: set(index_codes),
        }

    def get_dynamic_partitions(self, name):
        return self.dynamic_partitions[name]


class _FakeContext:
    def __init__(
        self,
        *,
        trade_days: tuple[str, ...] = ("2026-06-01", "2026-06-02"),
        index_codes: tuple[str, ...] = ("000001.SH", "950228.SH"),
    ):
        self.instance = _FakeInstance(trade_days=trade_days, index_codes=index_codes)
        self.resources = SimpleNamespace(
            lake_root=_FakeLakeRoot(),
            duckdb=_FakeDuckDB(),
            prod_postgres=object(),
        )


def _registered_gap(
    *,
    expected_trade_dates: tuple[str, ...],
    registered_trade_dates: tuple[str, ...],
):
    expected_window = ContinuityExpectedDateWindow(
        expected_trade_dates=expected_trade_dates,
        min_trade_date="2000-01-01",
        max_trade_date=expected_trade_dates[-1] if expected_trade_dates else None,
        evaluated_at=datetime.now(),
        window_limit=10,
    )
    return expected_window, build_registered_gap_status(
        expected_trade_dates=expected_trade_dates,
        registered_trade_dates=registered_trade_dates,
    )


class RawIndexDailyUpdateJobSensorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._registered_gap_patcher = patch(
            "orchestrator.defs.sensors.raw_index_daily_update_job_sensor."
            "_index_trade_day_registered_gap",
            side_effect=lambda _context, evaluated_at, registered_trade_days: _registered_gap(
                expected_trade_dates=tuple(registered_trade_days),
                registered_trade_dates=tuple(registered_trade_days),
            ),
        )
        self.registered_gap_mock = self._registered_gap_patcher.start()

    def tearDown(self) -> None:
        self._registered_gap_patcher.stop()

    def test_sensor_definition_targets_new_raw_job_and_stays_stopped(self) -> None:
        self.assertEqual(raw_index_daily_update_job_sensor.name, "raw_index_daily_update_job_sensor")
        self.assertEqual(raw_index_daily_update_job_sensor.job_name, "raw_index_daily_update_job")
        self.assertEqual(raw_index_daily_update_job_sensor.default_status, dg.DefaultSensorStatus.STOPPED)

    def test_registered_gap_skips_before_readiness_and_source_probe(self) -> None:
        context = _FakeContext(trade_days=("2026-06-13", "2026-06-16"))
        self.registered_gap_mock.side_effect = (
            lambda _context, evaluated_at, registered_trade_days: _registered_gap(
                expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
                registered_trade_dates=tuple(registered_trade_days),
            )
        )
        with (
            patch(
                "orchestrator.defs.sensors.raw_index_daily_update_job_sensor."
                "raw_index_daily_lake_readiness_for_trade_dates",
            ) as raw_readiness,
            patch(
                "orchestrator.defs.sensors.raw_index_daily_update_job_sensor."
                "check_prod_index_daily_source_readiness",
            ) as source_probe,
        ):
            result = raw_index_daily_update_job_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("最早缺失日期为 2026-06-15", result.skip_reason.skip_message)
        raw_readiness.assert_not_called()
        source_probe.assert_not_called()

    def test_missing_recent_baseline_does_not_guess_start_date(self) -> None:
        trade_dates = ("2026-06-01", "2026-06-02")
        with (
            patch(
                "orchestrator.defs.sensors.raw_index_daily_update_job_sensor."
                "raw_index_daily_lake_readiness_for_trade_dates",
                return_value=_raw_batch_status(trade_dates, ready_dates=()),
            ),
            patch(
                "orchestrator.defs.sensors.raw_index_daily_update_job_sensor."
                "check_prod_index_daily_source_readiness",
            ) as source_probe,
        ):
            result = raw_index_daily_update_job_sensor._raw_fn(_FakeContext())

        self.assertEqual(result.run_requests, [])
        self.assertIn("缺少 raw_index_daily 已就绪基线", result.skip_reason.skip_message)
        source_probe.assert_not_called()

    def test_existing_failed_raw_checks_do_not_auto_overwrite(self) -> None:
        trade_dates = ("2026-06-01", "2026-06-02")
        with (
            patch(
                "orchestrator.defs.sensors.raw_index_daily_update_job_sensor."
                "raw_index_daily_lake_readiness_for_trade_dates",
                return_value=_raw_batch_status(
                    trade_dates,
                    ready_dates=("2026-06-01",),
                    failed_dates=("2026-06-02",),
                ),
            ),
            patch(
                "orchestrator.defs.sensors.raw_index_daily_update_job_sensor."
                "check_prod_index_daily_source_readiness",
            ) as source_probe,
        ):
            result = raw_index_daily_update_job_sensor._raw_fn(_FakeContext())

        self.assertEqual(result.run_requests, [])
        self.assertIn("blocking checks 未全绿", result.skip_reason.skip_message)
        source_probe.assert_not_called()

    def test_source_not_ready_does_not_submit_run(self) -> None:
        trade_dates = ("2026-06-01", "2026-06-02")
        with (
            patch(
                "orchestrator.defs.sensors.raw_index_daily_update_job_sensor."
                "raw_index_daily_lake_readiness_for_trade_dates",
                return_value=_raw_batch_status(
                    trade_dates,
                    ready_dates=("2026-06-01",),
                ),
            ),
            patch(
                "orchestrator.defs.sensors.raw_index_daily_update_job_sensor."
                "check_prod_index_daily_source_readiness",
                return_value=_source_status(ready=False),
            ),
        ):
            result = raw_index_daily_update_job_sensor._raw_fn(_FakeContext())

        self.assertEqual(result.run_requests, [])
        self.assertIn("source readiness 未满足", result.skip_reason.skip_message)

    def test_source_ready_submits_one_date_level_run(self) -> None:
        trade_dates = ("2026-06-01", "2026-06-02")
        with (
            patch(
                "orchestrator.defs.sensors.raw_index_daily_update_job_sensor."
                "raw_index_daily_lake_readiness_for_trade_dates",
                return_value=_raw_batch_status(
                    trade_dates,
                    ready_dates=("2026-06-01",),
                ),
            ),
            patch(
                "orchestrator.defs.sensors.raw_index_daily_update_job_sensor."
                "check_prod_index_daily_source_readiness",
                return_value=_source_status(ready=True),
            ),
        ):
            result = raw_index_daily_update_job_sensor._raw_fn(_FakeContext())

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, "2026-06-02")
        self.assertEqual(request.run_key, "raw_index_daily:2026-06-02")
        self.assertEqual(
            request.run_config,
            {"ops": {"raw_index_daily": {"config": {"write_mode": "replace"}}}},
        )


if __name__ == "__main__":
    unittest.main()
