import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.sensors.index_daily_raw_file_readiness import (
    IndexDailyRawFileReadiness,
    IndexDailyRawGapAudit,
)
from orchestrator.defs.sensors.readiness import AssetReadinessStatus
from orchestrator.defs.sensors.silver_index_daily_sensor import (
    _first_not_ready_silver_trade_date,
    silver_index_daily_sensor,
)


def _status(
    trade_date: str,
    *,
    ready: bool,
    materialized: bool = True,
) -> AssetReadinessStatus:
    return AssetReadinessStatus(
        asset_key="silver_index_daily",
        partition_key=trade_date,
        ready=ready,
        materialized=materialized,
        checks_passed=ready,
        freshness_passed=ready,
        materialization_storage_id=1 if materialized else None,
        materialization_date="2026-06-02" if materialized else None,
        missing_check_names=() if ready else ("coverage",),
        failed_check_names=(),
        reason="ready" if ready else "not ready",
    )


def _ready_gap_audit(trade_dates: tuple[str, ...]) -> IndexDailyRawGapAudit:
    return IndexDailyRawGapAudit(
        trade_dates=trade_dates,
        registered_code_count=1,
        trade_date_count=len(trade_dates),
        expected_pair_count=len(trade_dates),
        ready_pair_count=len(trade_dates),
        missing_file_codes=(),
        missing_trade_date_pair_count=0,
        missing_pair_count=0,
        first_missing_trade_date=None,
        first_missing_code_count=0,
        first_missing_codes=(),
        missing_pair_samples=(),
    )


def _ready_raw_file_status(trade_date: str) -> IndexDailyRawFileReadiness:
    return IndexDailyRawFileReadiness(
        trade_date=trade_date,
        registered_code_count=1,
        ready_code_count=1,
        missing_file_codes=(),
        missing_trade_date_codes=(),
    )


class _FakeLakeRoot:
    def root(self):
        return Path("/fake/lake")


class _FakeInstance:
    def __init__(self):
        self.dynamic_partitions = {
            cn_a_index_trade_days.name: {"2026-06-01", "2026-06-02"},
            cn_a_index_ts_codes.name: {"000001.SH"},
        }

    def get_dynamic_partitions(self, name):
        return self.dynamic_partitions[name]


class _FakeContext:
    def __init__(self):
        self.instance = _FakeInstance()
        self.resources = SimpleNamespace(lake_root=_FakeLakeRoot(), duckdb=object())
        self.log = SimpleNamespace(warning=lambda *_args, **_kwargs: None)


class SilverIndexDailySensorTests(unittest.TestCase):
    def test_first_not_ready_uses_silver_selector(self) -> None:
        instance = object()
        trade_dates = ("2026-06-01", "2026-06-02", "2026-06-03")
        selected_status = _status("2026-06-02", ready=False)

        with patch(
            "orchestrator.defs.sensors.silver_index_daily_sensor."
            "select_first_not_ready_silver_index_daily_partition",
            return_value=("2026-06-02", selected_status),
        ) as selector:
            trade_date, status = _first_not_ready_silver_trade_date(
                instance,
                trade_dates,
            )

        selector.assert_called_once_with(instance, trade_dates)
        self.assertEqual(trade_date, "2026-06-02")
        self.assertIs(status, selected_status)

    def test_failed_check_status_does_not_submit_run(self) -> None:
        failed_status = _status("2026-06-01", ready=False, materialized=True)

        with (
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "audit_index_daily_raw_gaps",
                return_value=_ready_gap_audit(("2026-06-01", "2026-06-02")),
            ),
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "_first_not_ready_silver_trade_date",
                return_value=("2026-06-01", failed_status),
            ),
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "check_index_daily_raw_files_for_trade_date",
            ) as raw_status_check,
        ):
            result = silver_index_daily_sensor._raw_fn(_FakeContext())

        self.assertEqual(result.run_requests, [])
        self.assertIn("blocking checks 未全绿", result.skip_reason.skip_message)
        raw_status_check.assert_not_called()

    def test_missing_materialization_status_submits_run_when_raw_ready(self) -> None:
        missing_status = _status("2026-06-01", ready=False, materialized=False)

        with (
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "audit_index_daily_raw_gaps",
                return_value=_ready_gap_audit(("2026-06-01", "2026-06-02")),
            ),
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "_first_not_ready_silver_trade_date",
                return_value=("2026-06-01", missing_status),
            ),
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "check_index_daily_raw_files_for_trade_date",
                return_value=_ready_raw_file_status("2026-06-01"),
            ),
        ):
            result = silver_index_daily_sensor._raw_fn(_FakeContext())

        self.assertIsNone(result.skip_reason)
        self.assertEqual(len(result.run_requests), 1)
        self.assertEqual(result.run_requests[0].partition_key, "2026-06-01")
        self.assertEqual(result.run_requests[0].run_key, "silver_index_daily:2026-06-01")


if __name__ == "__main__":
    unittest.main()
