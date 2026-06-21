import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityExpectedDateWindow,
    build_registered_gap_status,
)
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
        raw_started_code_count=1,
    )


def _ready_gap_audit_with_no_raw_history(
    trade_dates: tuple[str, ...],
) -> IndexDailyRawGapAudit:
    return IndexDailyRawGapAudit(
        trade_dates=trade_dates,
        registered_code_count=2,
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
        raw_started_code_count=1,
        no_raw_history_codes=("950228.SH",),
    )


def _gap_audit_with_middle_gap(trade_dates: tuple[str, ...]) -> IndexDailyRawGapAudit:
    return IndexDailyRawGapAudit(
        trade_dates=trade_dates,
        registered_code_count=1,
        trade_date_count=len(trade_dates),
        expected_pair_count=len(trade_dates),
        ready_pair_count=len(trade_dates) - 1,
        missing_file_codes=(),
        missing_trade_date_pair_count=1,
        missing_pair_count=1,
        first_missing_trade_date="2026-06-01",
        first_missing_code_count=1,
        first_missing_codes=("000001.SH",),
        missing_pair_samples=(("2026-06-01", "000001.SH"),),
        raw_started_code_count=1,
    )


def _ready_raw_file_status(trade_date: str) -> IndexDailyRawFileReadiness:
    return IndexDailyRawFileReadiness(
        trade_date=trade_date,
        registered_code_count=1,
        ready_code_count=1,
        missing_file_codes=(),
        missing_trade_date_codes=(),
    )


def _missing_raw_file_status(trade_date: str) -> IndexDailyRawFileReadiness:
    return IndexDailyRawFileReadiness(
        trade_date=trade_date,
        registered_code_count=1,
        ready_code_count=0,
        missing_file_codes=("950228.SH",),
        missing_trade_date_codes=(),
    )


class _FakeLakeRoot:
    def root(self):
        return Path("/fake/lake")


class _FakeInstance:
    def __init__(
        self,
        *,
        trade_days: tuple[str, ...] = ("2026-06-01", "2026-06-02"),
        index_codes: tuple[str, ...] = ("000001.SH",),
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
        index_codes: tuple[str, ...] = ("000001.SH",),
    ):
        self.instance = _FakeInstance(trade_days=trade_days, index_codes=index_codes)
        self.resources = SimpleNamespace(lake_root=_FakeLakeRoot(), duckdb=object())
        self.log = SimpleNamespace(warning=lambda *_args, **_kwargs: None)


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


class SilverIndexDailySensorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._registered_gap_patcher = patch(
            "orchestrator.defs.sensors.silver_index_daily_sensor._index_trade_day_registered_gap",
            side_effect=lambda _context, evaluated_at, registered_trade_days: _registered_gap(
                expected_trade_dates=tuple(registered_trade_days),
                registered_trade_dates=tuple(registered_trade_days),
            ),
        )
        self.registered_gap_mock = self._registered_gap_patcher.start()

    def tearDown(self) -> None:
        self._registered_gap_patcher.stop()

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

    def test_registered_gap_skips_before_raw_gap_audit_and_silver_selector(
        self,
    ) -> None:
        context = _FakeContext(trade_days=("2026-06-13", "2026-06-16"))
        self.registered_gap_mock.side_effect = (
            lambda _context, evaluated_at, registered_trade_days: _registered_gap(
                expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
                registered_trade_dates=tuple(registered_trade_days),
            )
        )
        with (
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "audit_index_daily_raw_gaps",
            ) as raw_gap_audit,
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "_first_not_ready_silver_trade_date",
            ) as silver_selector,
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "check_index_daily_raw_files_for_trade_date",
            ) as raw_status_check,
        ):
            result = silver_index_daily_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("最早缺失日期为 2026-06-15", result.skip_reason.skip_message)
        raw_gap_audit.assert_not_called()
        silver_selector.assert_not_called()
        raw_status_check.assert_not_called()

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

    def test_recent_continuity_gap_skips_without_target_presence_check(self) -> None:
        with (
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "audit_index_daily_raw_gaps",
                return_value=_gap_audit_with_middle_gap(("2026-06-01", "2026-06-02")),
            ),
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "_first_not_ready_silver_trade_date",
            ) as selector,
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "check_index_daily_raw_files_for_trade_date",
            ) as raw_status_check,
        ):
            result = silver_index_daily_sensor._raw_fn(_FakeContext())

        self.assertEqual(result.run_requests, [])
        self.assertIn("raw-by-code 仍存在有效空洞", result.skip_reason.skip_message)
        selector.assert_not_called()
        raw_status_check.assert_not_called()

    def test_no_raw_history_does_not_block_continuity_but_target_presence_blocks(
        self,
    ) -> None:
        missing_status = _status("2026-06-01", ready=False, materialized=False)

        with (
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "audit_index_daily_raw_gaps",
                return_value=_ready_gap_audit_with_no_raw_history(
                    ("2026-06-01", "2026-06-02")
                ),
            ),
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "_first_not_ready_silver_trade_date",
                return_value=("2026-06-01", missing_status),
            ),
            patch(
                "orchestrator.defs.sensors.silver_index_daily_sensor."
                "check_index_daily_raw_files_for_trade_date",
                return_value=_missing_raw_file_status("2026-06-01"),
            ),
        ):
            result = silver_index_daily_sensor._raw_fn(_FakeContext())

        self.assertEqual(result.run_requests, [])
        self.assertIn("raw-by-code 文件仍有缺失代码", result.skip_reason.skip_message)


if __name__ == "__main__":
    unittest.main()
